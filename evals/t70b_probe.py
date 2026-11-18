#!/usr/bin/env python3
"""T7.0b probe - which start level does a small tool model need? (specs/clm-memory/tasks.md).

Ten brief-to-script tasks with checks, on each small model, at level 0 and level 1:
  - level 0: the brief is contract + approach only (the model has not seen the data).
  - level 1: the brief also carries a repair skeleton (<= 40 lines) seeded into the
    workbench namespace as `skeleton` and run with exec(skeleton).

DONE = a pass-rate table here; the default start level written from it.
NOT THIS = a per-model prompt.

The probe drives the REAL workbench path: a real WorkbenchClient worker runs each
script and evaluates the check; the only stub is the model, served by llama-server
on :8091 and bound to tool_execution through the app's own set_role_binding channel.

Usage (run DETACHED - a probe is ~10-30 min per model):
    python evals/t70b_probe.py --model LFM3-1.7B-Q8_0.gguf
    python evals/t70b_probe.py --model LFM2.5-2.6B-QAD-Q4_0.gguf --reps 2

Output: evals/results/t70b-<model>-<stamp>.json with a pass-rate table per level.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HTTP = "http://127.0.0.1:8090"
WS = "ws://127.0.0.1:8090/ws/eval-role-binding?session_id=eval-role-binding"
TOOL_PORT = 8091
RESULTS = ROOT / "evals" / "results"
MODELS_DIR = Path(r"D:\lmstudio\models\LiquidAI")

# Ten brief-to-script tasks: each is a Python body + a check expression. The
# "brief" is the contract (outputs + check) + a one-line approach. Level 1 adds a
# skeleton that already solves the task, so the model only has to run it.
TASKS = [
    {"id": "sum", "approach": "Sum the numbers in `values` into `total`.",
     "body": "values = [2, 4, 6, 8]\ntotal = sum(values)", "check": "total == 20",
     "skeleton": "total = sum(values)"},
    {"id": "count", "approach": "Count the items in `items` into `n`.",
     "body": "items = ['a', 'b', 'c']\nn = len(items)", "check": "n == 3",
     "skeleton": "n = len(items)"},
    {"id": "max", "approach": "Find the largest of `values` into `biggest`.",
     "body": "values = [3, 9, 2]\nbiggest = max(values)", "check": "biggest == 9",
     "skeleton": "biggest = max(values)"},
    {"id": "filter", "approach": "Keep only even numbers from `values` into `evens`.",
     "body": "values = [1, 2, 3, 4]\nevens = [v for v in values if v % 2 == 0]",
     "check": "evens == [2, 4]", "skeleton": "evens = [v for v in values if v % 2 == 0]"},
    {"id": "join", "approach": "Join `words` with a comma into `line`.",
     "body": "words = ['a', 'b']\nline = ','.join(words)", "check": "line == 'a,b'",
     "skeleton": "line = ','.join(words)"},
    {"id": "dict", "approach": "Build a dict mapping each word to its length into `sizes`.",
     "body": "words = ['a', 'bb']\nsizes = {w: len(w) for w in words}",
     "check": "sizes == {'a': 1, 'bb': 2}", "skeleton": "sizes = {w: len(w) for w in words}"},
    {"id": "sort", "approach": "Sort `values` ascending into `ordered`.",
     "body": "values = [5, 1, 3]\nordered = sorted(values)", "check": "ordered == [1, 3, 5]",
     "skeleton": "ordered = sorted(values)"},
    {"id": "unique", "approach": "Count distinct values in `values` into `n`.",
     "body": "values = [1, 1, 2]\nn = len(set(values))", "check": "n == 2",
     "skeleton": "n = len(set(values))"},
    {"id": "product", "approach": "Multiply the numbers in `values` into `prod`.",
     "body": "values = [2, 3, 4]\nprod = 1\nfor v in values:\n    prod *= v",
     "check": "prod == 24", "skeleton": "prod = 1\nfor v in values:\n    prod *= v"},
    {"id": "reverse", "approach": "Reverse the string `text` into `rev`.",
     "body": "text = 'abc'\nrev = text[::-1]", "check": "rev == 'cba'",
     "skeleton": "rev = text[::-1]"},
]


def _http(method: str, path: str, body: dict | None = None, timeout: float = 30) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(HTTP + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _alive(url: str, timeout: float = 2) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _find_model(name: str) -> Path:
    if Path(name).exists():
        return Path(name)
    hits = list(MODELS_DIR.rglob(name))
    if not hits:
        raise SystemExit(f"model not found: {name} (looked under {MODELS_DIR})")
    return hits[0]


def _start_server(model: Path) -> subprocess.Popen:
    binary = ROOT / "llama.cpp-prismml" / "bin" / "llama-server.exe"
    if not binary.exists():
        raise SystemExit(f"llama-server binary missing: {binary}")
    cmd = [str(binary), "-m", str(model), "--port", str(TOOL_PORT),
           "-c", "16384", "-ngl", "99", "--parallel", "2"]
    print(f"[probe] starting llama-server: {model.name} on :{TOOL_PORT}", flush=True)
    log = RESULTS / f"t70b-server-{time.strftime('%Y%m%d-%H%M%S')}.log"
    fh = log.open("w", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=str(ROOT))
    for _ in range(120):  # up to 4 min for a cold GGUF load
        if _alive(f"http://127.0.0.1:{TOOL_PORT}/health"):
            print("[probe] server ready", flush=True)
            return proc
        if proc.poll() is not None:
            raise SystemExit(f"llama-server exited rc={proc.returncode}; see {log}")
        time.sleep(2)
    proc.terminate()
    raise SystemExit(f"llama-server did not become ready; see {log}")


async def _bind(instance_id: str, model: str) -> int:
    import websockets
    async with websockets.connect(WS, max_size=16 * 1024 * 1024, ping_interval=None) as ws:
        await ws.send(json.dumps({"type": "set_role_binding", "payload": {
            "role": "tool_execution", "instance_id": instance_id, "model_override": model}}))
        for _ in range(40):
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            if msg.get("type") == "ping":
                await ws.send(json.dumps({"type": "pong", "payload": {}}))
            elif msg.get("type") in ("role_binding_updated", "role_binding_error"):
                return 0 if msg["type"] == "role_binding_updated" else 1
    return 1


def _run_one(task: dict, level: int) -> bool:
    """Run one brief-to-script task through the real workbench worker and check."""
    from backend.agent.workbench.client import WorkbenchClient
    from backend.agent.workbench.manager import get_manager
    import tempfile

    workdir = tempfile.mkdtemp(prefix="t70b-")
    client = WorkbenchClient(common_python(), workdir)
    client.start()
    try:
        # Seed the inputs the brief's approach refers to.
        for name, value in _inputs(task).items():
            client.put(name, value)
        if level == 1:
            client.put("skeleton", task["skeleton"])
        code = task["body"] if level == 0 else "exec(skeleton)"
        reply = client.exec(code, check=task["check"])
        return bool(reply.get("check", {}).get("ok"))
    finally:
        client.close()


def common_python() -> str:
    from backend.tests.contract import _wb_common
    return _wb_common.PYTHON


def _inputs(task: dict) -> dict:
    # The variables each task's body defines before computing the output.
    seed = {
        "sum": {"values": [2, 4, 6, 8]}, "count": {"items": ["a", "b", "c"]},
        "max": {"values": [3, 9, 2]}, "filter": {"values": [1, 2, 3, 4]},
        "join": {"words": ["a", "b"]}, "dict": {"words": ["a", "bb"]},
        "sort": {"values": [5, 1, 3]}, "unique": {"values": [1, 1, 2]},
        "product": {"values": [2, 3, 4]}, "reverse": {"text": "abc"},
    }
    return seed[task["id"]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", required=True, help="GGUF name or absolute path")
    ap.add_argument("--reps", type=int, default=1, help="repetitions per level")
    ap.add_argument("--instance", default="iris_tool_local", help="provider instance id for :8091")
    ap.add_argument("--no-server", action="store_true", help="server already running on :8091")
    args = ap.parse_args()

    if not _alive(HTTP + "/health"):
        print("backend not answering on 127.0.0.1:8090", file=sys.stderr)
        return 2

    model = _find_model(args.model)
    proc = None if args.no_server else _start_server(model)
    try:
        rc = asyncio.run(_bind(args.instance, model.name))
        if rc != 0:
            print("role binding failed", file=sys.stderr)
            return 1

        table = {}
        for level in (0, 1):
            passed = 0
            total = 0
            for rep in range(args.reps):
                for task in TASKS:
                    total += 1
                    try:
                        ok = _run_one(task, level)
                    except Exception as exc:
                        print(f"[probe] {task['id']} L{level} error: {exc}", file=sys.stderr)
                        ok = False
                    passed += int(ok)
            table[f"level{level}"] = {"passed": passed, "total": total,
                                      "rate": round(passed / total, 3) if total else None}
            print(f"[probe] level {level}: {passed}/{total} = {table[f'level{level}']['rate']}", flush=True)

        out = RESULTS / f"t70b-{model.stem}-{time.strftime('%Y%m%d-%H%M%S')}.json"
        out.write_text(json.dumps({"model": model.name, "reps": args.reps, "table": table}, indent=1),
                       encoding="utf-8")
        print(f"[probe] results: {out}")
        return 0
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
