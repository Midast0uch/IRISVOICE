"""Execution pass-rate harness (Phase 0 of the 2026-09-29 execution audit).

Drives REAL turns through the running backend, exactly as the UI does, and
scores each one with a checker the agent never sees:

  coding   : a fresh copy of a small repo per task, sent through the developer
             `/run` path (`dev_cli`, the only path that binds a workdir). After
             the turn, the task's hidden tests are copied in and run with pytest.
  research : a personal-mode chat turn with web access on. The reply text plus
             any rendered document must match every fact pattern.

Each task gets its own visible thread titled "[eval] <id>", so nothing lands in
an existing conversation.

The harness changes three pieces of app state for the run and restores two:
  - launcher mode   (switched per group, restored at the end)
  - project list    (the eval root is registered so run_command may use it;
                     restored at the end)
  - web mode        (turned ON for research; left on, it is an in-memory toggle
                     the UI re-sends)

Usage:
    python evals/run_evals.py                      # all tasks
    python evals/run_evals.py --group coding
    python evals/run_evals.py --task c01_fix_off_by_one --task r02_websocket_rfc
    python evals/run_evals.py --record-baseline    # also writes evals/baseline.json

Requires the backend on 127.0.0.1:8090 and, when the tool role is bound to a
local model, that model's server accepting connections.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

import websockets

EVALS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALS_DIR.parent
TASKS_FILE = EVALS_DIR / "tasks.json"
FIXTURES_DIR = EVALS_DIR / "fixtures"
RESULTS_DIR = EVALS_DIR / "results"
BASELINE_FILE = EVALS_DIR / "baseline.json"
PARTIAL_FILE = RESULTS_DIR / "partial.json"  # rewritten after every task
IRIS_CONFIG = REPO_ROOT / "data" / "iris_config.json"

# 127.0.0.1, not localhost: localhost resolves to ::1 first on this machine and
# the backend binds IPv4 (see scripts/accumulate_rows.py).
HTTP_BASE = "http://127.0.0.1:8090"
WS_BASE = "ws://127.0.0.1:8090/ws"
LOCAL_MODEL_PORT = int(os.environ.get("IRIS_LOCAL_PORT", "8082"))

# Work copies live OUTSIDE the IRIS repo: a workdir inside the repo triggers the
# self-edit worktree routing, which would test a different path.
EVAL_ROOT = Path(tempfile.gettempdir()) / "iris-evals"
EVAL_PROJECT_ID = "iris-evals"
HIDDEN_DIRNAME = "_eval_hidden"

# Repo paths that the running backend writes on its own; changes there are not
# evidence that the agent wrote into the wrong tree.
_LEAK_NOISE_PREFIXES = (
    "data/", "backend/data/", ".mcm/", "logs/", ".iris-pids/", "temp/",
    "benchmarks/", "evals/results/", ".workbuddy-ai/", "screenshots/",
    ".iris-worktree/",  # the developer-mode switch builds this self-edit worktree
)

# Reply prefixes that mean the turn failed rather than answered.
_ERROR_REPLY_MARKERS = (
    "[iris error", "agent turn failed", "agent kernel is not available",
    "developer cli error", "web search is currently disabled",
    "iris couldn't generate a response", "i wasn't able to generate a response",
)

_WEB_TOOL_HINTS = ("search", "crawl", "open_url", "browse", "fetch", "web")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("evals")


# ── small HTTP helpers (stdlib only) ─────────────────────────────────────────

def _http(method: str, path: str, body: dict | None = None, timeout: float = 15.0) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        HTTP_BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8") or "{}"
    return json.loads(raw)


def _backend_alive(patience_s: float = 180.0) -> bool:
    """True if the backend answers within `patience_s`.

    A backend still working through a turn the harness already timed out on
    can miss one 30 s health check; that is busy, not dead.
    """
    deadline = time.monotonic() + patience_s
    while True:
        try:
            _http("GET", "/health", timeout=30)
            return True
        except Exception:
            if time.monotonic() >= deadline:
                return False
            time.sleep(10)


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3):
            return True
    except OSError:
        return False


def _tool_role_is_local() -> bool:
    try:
        cfg = json.loads(IRIS_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    for binding in cfg.get("role_bindings") or []:
        if binding.get("role") == "tool_execution":
            return str(binding.get("instance_id", "")).startswith("local:")
    return False


def _model_bindings() -> list:
    try:
        cfg = json.loads(IRIS_CONFIG.read_text(encoding="utf-8"))
        return [
            {"role": b.get("role"), "instance": b.get("instance_id"),
             "model": b.get("model_override")}
            for b in cfg.get("role_bindings") or []
        ]
    except (OSError, ValueError):
        return []


# ── leak guard ───────────────────────────────────────────────────────────────

def _repo_status() -> set:
    """Changed/untracked paths in the IRIS repo, minus backend-owned noise."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("leak guard: git status failed: %s", exc)
        return set()
    paths = set()
    for line in out.splitlines():
        path = line[3:].strip().strip('"').replace("\\", "/")
        if not path.startswith(_LEAK_NOISE_PREFIXES):
            paths.add(line[:2] + " " + path)
    return paths


# ── one turn over the WebSocket ──────────────────────────────────────────────

async def _run_turn(task: dict, conv_id: str, workdir: Path | None, timeout_s: float) -> dict:
    """Send one task and collect everything until the turn's final reply."""
    client = f"eval-{task['id']}-{uuid.uuid4().hex[:6]}"
    url = f"{WS_BASE}/{client}?session_id={client}"
    record: dict = {
        "reply": "", "documents": [], "event_counts": {}, "tools": [],
        "permissions": 0, "questions": 0, "timed_out": False, "ws_error": None,
    }
    prompt = task["prompt"].replace("{workdir}", str(workdir) if workdir else "")

    # ping_interval=None: the library's own keepalive closed the socket (1011)
    # while the backend was busy mid-turn. The server runs its own heartbeat,
    # which is answered below, so liveness is still checked.
    async with websockets.connect(url, max_size=16 * 1024 * 1024, ping_interval=None) as ws:
        await ws.send(json.dumps({"type": "new_conversation",
                                  "payload": {"conversation_id": conv_id}}))
        if task["group"] == "research":
            await ws.send(json.dumps({"type": "set_web_mode", "payload": {"enabled": True}}))

        if task["path"] == "dev_cli":
            await ws.send(json.dumps({"type": "dev_cli",
                                      "payload": {"query": prompt, "workdir": str(workdir)}}))
            final_types = {"text_response"}
        else:
            await ws.send(json.dumps({"type": "text_message",
                                      "payload": {"text": prompt, "conversation_id": conv_id}}))
            final_types = {"chat_message", "text_response"}

        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                record["timed_out"] = True
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                record["timed_out"] = True
                break
            except websockets.ConnectionClosed as exc:
                record["ws_error"] = f"connection closed: {exc}"
                break
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            mtype = msg.get("type", "")
            payload = msg.get("payload") if isinstance(msg.get("payload"), dict) else msg
            record["event_counts"][mtype] = record["event_counts"].get(mtype, 0) + 1

            if mtype == "ping":
                await ws.send(json.dumps({"type": "pong", "payload": {}}))
            elif mtype == "permission:request":
                # The eval works only inside its own throwaway copy, so every
                # request is granted; `confirm` covers the destructive tier.
                record["permissions"] += 1
                action = "confirm" if payload.get("requires_confirmation") else "grant"
                await ws.send(json.dumps({"type": "notification_response", "payload": {
                    "notification_id": payload.get("request_id", ""), "action": action}}))
            elif mtype == "question:ask":
                record["questions"] += 1
                questions = payload.get("questions") or [payload]
                for q in questions:
                    options = q.get("options") or []
                    answer = options[0] if options else "Use your best judgement and continue."
                    if isinstance(answer, dict):
                        answer = answer.get("label") or answer.get("value") or str(answer)
                    await ws.send(json.dumps({"type": "question_response", "payload": {
                        "question_id": q.get("question_id", ""), "answer": str(answer)}}))
            elif mtype.startswith("tool:"):
                name = payload.get("tool") or payload.get("tool_name") or payload.get("name")
                if name and mtype == "tool:call":
                    record["tools"].append(str(name))
            elif mtype == "document:render":
                content = payload.get("content")
                if isinstance(content, str):
                    record["documents"].append(content)
            elif mtype in final_types:
                text = payload.get("content") or payload.get("text") or ""
                if mtype == "chat_message" and payload.get("role") not in (None, "assistant", "error"):
                    continue
                if payload.get("role") == "error" and not text.lower().startswith("[iris error"):
                    text = "[IRIS error] " + text
                record["reply"] = text
                # Documents are emitted before the final reply; give a late
                # document frame a moment to arrive before closing.
                try:
                    while True:
                        extra = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
                        if extra.get("type") == "document:render":
                            p = extra.get("payload") or {}
                            if isinstance(p.get("content"), str):
                                record["documents"].append(p["content"])
                except (asyncio.TimeoutError, websockets.ConnectionClosed, ValueError):
                    pass
                break
    return record


# ── checking ─────────────────────────────────────────────────────────────────

def _is_error_reply(text: str) -> bool:
    head = text.strip().lower()[:200]
    return not head or any(head.startswith(m) or m in head[:80] for m in _ERROR_REPLY_MARKERS)


def _check_patterns(task: dict, text: str) -> list:
    missing = []
    for pattern in task.get("reply_patterns") or []:
        if not re.search(pattern, text, re.IGNORECASE):
            missing.append(pattern)
    return missing


def _run_hidden_tests(task: dict, workdir: Path) -> tuple:
    hidden_src = FIXTURES_DIR / task["id"] / "hidden"
    if not hidden_src.is_dir():
        return True, "no hidden tests"
    target = workdir / HIDDEN_DIRNAME
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(hidden_src, target)
    # Shared helpers, plus the untouched fixture repo so a test can prove a
    # file the agent was told not to change is still byte-for-byte original.
    shutil.copy2(FIXTURES_DIR / "_shared" / "conftest.py", target / "conftest.py")
    shutil.copytree(FIXTURES_DIR / task["id"] / "repo", target / "originals")
    env = dict(os.environ, EVAL_WORKDIR=str(workdir), PYTHONDONTWRITEBYTECODE="1")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             "--rootdir", str(target), "--ignore", str(target / "originals"), str(target)],
            cwd=workdir, capture_output=True, text=True, timeout=180, env=env,
        )
    except subprocess.TimeoutExpired:
        return False, "hidden tests timed out"
    tail = (proc.stdout or proc.stderr).strip().splitlines()[-1:] or [""]
    return proc.returncode == 0, tail[0][:200]


def _prepare_workdir(task: dict, run_dir: Path) -> Path:
    workdir = run_dir / task["id"]
    shutil.copytree(FIXTURES_DIR / task["id"] / "repo", workdir)
    return workdir


# ── the run ──────────────────────────────────────────────────────────────────

def _load_tasks(groups: list, ids: list) -> list:
    tasks = json.loads(TASKS_FILE.read_text(encoding="utf-8"))["tasks"]
    if groups:
        tasks = [t for t in tasks if t["group"] in groups]
    if ids:
        tasks = [t for t in tasks if t["id"] in ids]
    return tasks


def _preflight(tasks: list, check_model: bool) -> str | None:
    try:
        _http("GET", "/health", timeout=5)
    except Exception as exc:
        return f"backend is not answering on {HTTP_BASE}: {exc}"
    if check_model and _tool_role_is_local() and not _port_open(LOCAL_MODEL_PORT):
        return (f"the tool role is bound to a local model, but nothing accepts "
                f"connections on 127.0.0.1:{LOCAL_MODEL_PORT}. Load the model in the "
                f"Models card, or pass --no-model-check to measure without it.")
    missing = [t["id"] for t in tasks
               if t["group"] == "coding" and not (FIXTURES_DIR / t["id"] / "repo").is_dir()]
    if missing:
        return f"fixtures missing for: {', '.join(missing)}"
    return None


async def _run(tasks: list, keep: bool, done: list) -> list:
    run_id = time.strftime("%Y%m%d-%H%M%S")
    run_dir = EVAL_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    original_mode = _http("GET", "/api/mode").get("mode")
    # Restore the STORED list, not GET's view of it: with no stored projects
    # GET synthesizes a default entry, which must not be written back.
    try:
        original_projects = json.loads(IRIS_CONFIG.read_text(encoding="utf-8")).get("projects") or []
    except (OSError, ValueError):
        original_projects = []
    eval_projects = [p for p in original_projects if p.get("id") != EVAL_PROJECT_ID] + [{
        "id": EVAL_PROJECT_ID, "name": "IRIS evals", "path": str(EVAL_ROOT),
        "mode": "developer", "driveType": "local",
    }]
    _http("POST", "/api/projects", {"projects": eval_projects})
    current_mode = None
    results = list(done)
    try:
        for i, task in enumerate(tasks, 1):
            if task["mode"] != current_mode:
                # Developer mode sets up a git worktree (bounded at 20 s server-side).
                _http("POST", "/api/mode", {"mode": task["mode"]}, timeout=60)
                current_mode = task["mode"]
            log.info("[%d/%d] %s (%s, %s)", i, len(tasks), task["id"], task["group"], task["mode"])

            workdir = _prepare_workdir(task, run_dir) if task["group"] == "coding" else None
            before = _repo_status() if task["group"] == "coding" else set()

            started = time.monotonic()
            conv_id = None
            try:
                # A backend still busy with the previous turn can be slow here;
                # that fails this task, never the whole run.
                conv = _http("POST", "/api/conversations",
                             {"title": f"[eval] {task['id']}"}, timeout=90)
                conv_id = conv.get("id") or conv.get("conversation_id")
                rec = await _run_turn(task, conv_id, workdir, float(task.get("timeout_s", 900)))
            except Exception as exc:  # a broken socket is a failed task, not a crashed run
                rec = {"reply": "", "documents": [], "event_counts": {}, "tools": [],
                       "permissions": 0, "questions": 0, "timed_out": False,
                       "ws_error": f"{type(exc).__name__}: {exc}"}
            seconds = round(time.monotonic() - started, 1)

            text = "\n\n".join([rec["reply"], *rec["documents"]])
            notes = []
            if rec["timed_out"]:
                notes.append("timed out")
            if rec["ws_error"]:
                notes.append(rec["ws_error"])
            if _is_error_reply(rec["reply"]) and not rec["documents"]:
                notes.append("error or empty reply")
            missing = _check_patterns(task, text)
            if missing:
                notes.append(f"missing: {missing}")
            passed = not notes
            if workdir is not None:
                ok, detail = _run_hidden_tests(task, workdir)
                notes.append(f"hidden: {detail}")
                passed = passed and ok
                leaks = sorted(_repo_status() - before)
                if leaks:
                    notes.append(f"LEAK into IRIS repo: {leaks[:5]}")
            web_used = any(h in t.lower() for t in rec["tools"] for h in _WEB_TOOL_HINTS) or any(
                k.startswith("crawler_") for k in rec["event_counts"])

            results.append({
                "id": task["id"], "group": task["group"], "passed": passed,
                "seconds": seconds, "notes": notes, "conversation_id": conv_id,
                "workdir": str(workdir) if workdir else None,
                "tools": rec["tools"], "web_used": web_used,
                "permissions": rec["permissions"], "questions": rec["questions"],
                "reply_head": rec["reply"][:400], "event_counts": rec["event_counts"],
            })
            log.info("    %s in %.0fs  %s", "PASS" if passed else "FAIL", seconds, "; ".join(notes))
            _write_results(results, PARTIAL_FILE)
            if not passed and not _backend_alive():
                # Every later task would fail for a reason that says nothing
                # about the agent. Stop; `--resume` continues from here.
                results.pop()
                _write_results(results, PARTIAL_FILE)
                log.error("backend stopped answering during %s; run stopped. "
                          "Restart the backend and rerun with --resume.", task["id"])
                break
    finally:
        try:
            _http("POST", "/api/projects", {"projects": original_projects}, timeout=90)
            if original_mode:
                _http("POST", "/api/mode", {"mode": original_mode}, timeout=60)
        except Exception as exc:
            log.error("could not restore mode/projects: %s (mode was %r)", exc, original_mode)
        if not keep:
            shutil.rmtree(run_dir, ignore_errors=True)
    return results


def _write_results(results: list, path: Path) -> dict:
    payload = {
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "models": _model_bindings(),
        "summary": _summary(results),
        "results": results,
    }
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _summary(results: list) -> dict:
    groups: dict = {}
    for r in results:
        g = groups.setdefault(r["group"], {"passed": 0, "total": 0})
        g["total"] += 1
        g["passed"] += int(r["passed"])
    return groups


def main() -> int:
    ap = argparse.ArgumentParser(description="IRIS execution pass-rate harness")
    ap.add_argument("--group", action="append", choices=["coding", "research"], default=[])
    ap.add_argument("--task", action="append", default=[], help="task id (repeatable)")
    ap.add_argument("--record-baseline", action="store_true")
    ap.add_argument("--keep-workdirs", action="store_true")
    ap.add_argument("--no-model-check", action="store_true")
    ap.add_argument("--resume", action="store_true",
                    help="skip tasks already recorded in results/partial.json")
    args = ap.parse_args()

    tasks = _load_tasks(args.group, args.task)
    done: list = []
    if args.resume and PARTIAL_FILE.is_file():
        done = json.loads(PARTIAL_FILE.read_text(encoding="utf-8")).get("results") or []
        finished = {r["id"] for r in done}
        tasks = [t for t in tasks if t["id"] not in finished]
        log.info("resuming: %d task(s) already recorded, %d to run", len(done), len(tasks))
    if not tasks and not done:
        log.error("no tasks selected")
        return 2
    problem = _preflight(tasks, check_model=not args.no_model_check)
    if problem:
        log.error("preflight: %s", problem)
        return 4

    results = asyncio.run(_run(tasks, args.keep_workdirs, done))
    summary = _summary(results)

    print("\n" + "-" * 72)
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['id']:<28} {r['seconds']:>7.0f}s  "
              f"{'web ' if r['web_used'] else ''}{'; '.join(r['notes'])[:120]}")
    print("-" * 72)
    for group, g in summary.items():
        print(f"{group:<10} {g['passed']}/{g['total']}")

    out = RESULTS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    _write_results(results, out)
    PARTIAL_FILE.unlink(missing_ok=True)
    print(f"results: {out}")
    if args.record_baseline:
        _write_results(results, BASELINE_FILE)
        print(f"baseline: {BASELINE_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
