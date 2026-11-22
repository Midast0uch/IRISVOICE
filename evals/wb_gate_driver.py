#!/usr/bin/env python3
"""Round 6 A/B gate driver - browser cohorts, flag 0/1 interleaved, >= 5 rounds.

Replaces the lost scratch/wb_ab/r6gate/driver.py. Two efficiency fixes over the old
restart-per-block driver (measured 2026-11-17):

  1. NO backend restart per block. IRIS_WORKBENCH and IRIS_CLM_BASELINE are read at
     CALL TIME (kernel/planning.py, kernel/der/node.py, inference/clm_baseline.py), so
     the driver flips them between arms through POST /api/eval-flag in ONE backend
     process. Saves ~10-20 min of cold boots and removes restart flakiness.
  2. IRIS_EVAL_NO_DRAIN=1 for every run. The harness's post-reply drain waits ~31 s
     per task for TTS to finish speaking; reply_s is captured BEFORE the drain and
     browser cohorts render no documents. Saves ~2 h over a 240-run gate.

The bar and cohorts are in specs/clm-memory/design.md "Round 6 / Live gate".

Usage (run DETACHED - a full gate is ~3-4 h):
    python evals/wb_gate_driver.py --reps 5
    python evals/wb_gate_driver.py --reps 1 --quick          # smoke: 1 rep, 2 tasks/arm
    python evals/wb_gate_driver.py --reps 5 --tasks b01 b02  # custom task subset

Output:
    evals/results/wb_gate-<stamp>/blocks.json   driver block manifest
    evals/results/wb_gate-<stamp>/<arm>-r<rep>-<stamp>.json   per-block eval results
    prints the wb_ab_analysis.py command to run at the end.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HTTP = "http://127.0.0.1:8090"
RUN_EVALS = ROOT / "evals" / "run_evals.py"
ANALYSIS = ROOT / "evals" / "wb_ab_analysis.py"
RESULTS = ROOT / "evals" / "results"

# The three Round 6 cohorts (design.md "Live gate"). Re-checks are optional now
# (their fixes have guards) and left out of the default gate.
COHORT_TASKS = {
    "browser": [f"b{i:02d}" for i in range(1, 11)],
    "browser_goal": [f"g{i:02d}" for i in range(1, 5)],
    "browser_data": [f"d{i:02d}" for i in range(1, 5)],
}
ARMS = ("off", "on")  # the arm flag 0 / 1 (--arm-flag, default IRIS_WORKBENCH)
# CLM TG-2 (specs/clm-memory tasks.md): the no-regression cohort of every CLM gate
# (coding 8 + research 10 + memory 3, the T0.1 cohort, evals/results/20261111-175400)
# plus the `context` group (x01-x07), with IRIS_CLM_OFFLOAD flipped per arm.
NAMED_COHORTS = {
    "tg2": ["c01", "c03", "c05", "c08", "c10", "c11", "c12", "c15"]
           + [f"r{i:02d}" for i in range(1, 11)] + ["m01", "m02", "m03"]
           + [f"x{i:02d}" for i in range(1, 8)],
    "round6": sum(COHORT_TASKS.values(), []),
}


def _http(method: str, path: str, body: dict | None = None, timeout: float = 30) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        HTTP + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _backend_alive(timeout: float = 5) -> bool:
    try:
        with urllib.request.urlopen(HTTP + "/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _set_flag(name: str, value: str) -> None:
    _http("POST", "/api/eval-flag", {"name": name, "value": value})


def _task_ids(tasks: list[str], quick: bool) -> list[str]:
    """Resolve bare task ids (b01) to full ids (b01_example_more_info) from tasks.json."""
    data = json.loads((ROOT / "evals" / "tasks.json").read_text(encoding="utf-8"))
    all_tasks = {t["id"]: t for t in data["tasks"]}
    resolved = []
    for t in tasks:
        if t in all_tasks:
            resolved.append(t)
            continue
        hits = [tid for tid in all_tasks if tid.startswith(t + "_") or tid == t]
        if not hits:
            raise SystemExit(f"unknown task id: {t}")
        resolved.append(hits[0])
    if quick:
        # one representative per cohort: b01, g01, d01
        keep = []
        for prefix in ("b01", "g01", "d01"):
            keep += [r for r in resolved if r.startswith(prefix)]
        resolved = keep or resolved[:3]
    return resolved


def _run_block(task_ids: list[str], out_dir: Path, arm: str, rep: int) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log = out_dir / f"{arm}-r{rep}-{stamp}.log"
    cmd = [sys.executable, str(RUN_EVALS)]
    for t in task_ids:
        cmd += ["--task", t]
    cmd += ["--no-model-check"]
    env = os.environ.copy()
    env["IRIS_EVAL_NO_DRAIN"] = "1"
    # run_evals.py writes its JSON to evals/results/<stamp>.json and logs to stdout.
    # Snapshot the result files first, then find the NEW one after the run.
    before = set(RESULTS.glob("*.json"))
    print(f"[gate] arm={arm} rep={rep} tasks={len(task_ids)} -> {log.name}", flush=True)
    with log.open("w", encoding="utf-8") as fh:
        rc = subprocess.call(cmd, cwd=str(ROOT), env=env, stdout=fh, stderr=subprocess.STDOUT)
    new = [p for p in set(RESULTS.glob("*.json")) - before if p.name != "partial.json"]
    if not new:
        raise RuntimeError(f"run_evals.py wrote no result JSON (rc={rc}); see {log}")
    result = max(new, key=lambda p: p.stat().st_mtime)
    print(f"[gate]   done rc={rc} result={result.name}", flush=True)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--reps", type=int, default=5, help="rounds per arm (bar needs >= 5)")
    ap.add_argument("--quick", action="store_true", help="1 representative task per cohort")
    ap.add_argument("--tasks", nargs="*", default=None, help="override task ids (bare or full)")
    ap.add_argument("--cohort", choices=sorted(NAMED_COHORTS), default=None,
                    help="a named task set (tg2 = the CLM no-regression cohort + context group)")
    ap.add_argument("--arm-flag", default="IRIS_WORKBENCH",
                    help="the flag set 0 (off arm) / 1 (on arm); e.g. IRIS_CLM_OFFLOAD for TG-2")
    ap.add_argument("--no-web-toggle", action="store_true",
                    help="leave web mode as-is (runner sets it per browser cohort by default)")
    ap.add_argument("--page-seed", action="store_true",
                    help="Round 6 prototype: toggle IRIS_WB_PAGE_SEED per arm (on=1, off=0). "
                         "Off by default so the standard gate is unchanged.")
    ap.add_argument("--self-verify", action="store_true",
                    help="Round 6 option 1: toggle IRIS_WB_SELF_VERIFY per arm (on=1, off=0). "
                         "Off by default so the standard gate is unchanged.")
    ap.add_argument("--two-call", action="store_true",
                    help="Round 6 option 3: toggle IRIS_WB_TWO_CALL per arm (on=1, off=0). "
                         "One model response with two run_python calls (gather + compute). "
                         "Off by default so the standard gate is unchanged.")
    ap.add_argument("--see-gather", action="store_true",
                    help="Round 6 option 3b: toggle IRIS_WB_SEE_GATHER per arm (on=1, off=0). "
                         "Model sees the gather result before writing compute (two model calls). "
                         "Off by default so the standard gate is unchanged.")
    args = ap.parse_args()

    if not _backend_alive():
        print("backend not answering on 127.0.0.1:8090 - start it with: npm run iris:start:backend",
              file=sys.stderr)
        return 2

    task_ids = _task_ids(args.tasks or NAMED_COHORTS[args.cohort or "round6"], args.quick)
    # The values before the gate, restored after it: the flags are ON by default since
    # 2026-11-22, and the old finally left IRIS_WORKBENCH / IRIS_WB_TWO_CALL at 0.
    try:
        before_flags = {k: v for k, v in _http("GET", "/api/eval-flag").items()}
    except Exception as exc:
        print(f"[gate] cannot read the flags ({exc}); refusing to run without a restore point",
              file=sys.stderr)
        return 2
    print(f"[gate] arm flag {args.arm_flag}; flags before: {before_flags}", flush=True)
    print(f"[gate] {len(task_ids)} tasks, {args.reps} reps x {len(ARMS)} arms "
          f"= {len(task_ids) * args.reps * len(ARMS)} runs", flush=True)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = RESULTS / f"wb_gate-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Baseline logging on for the whole gate; workbench flag flips per arm.
    _set_flag("IRIS_CLM_BASELINE", "1")
    if args.page_seed:
        _set_flag("IRIS_WB_PAGE_SEED", "1")
    if args.self_verify:
        _set_flag("IRIS_WB_SELF_VERIFY", "1")
    if args.two_call:
        _set_flag("IRIS_WB_TWO_CALL", "1")
    if args.see_gather:
        _set_flag("IRIS_WB_SEE_GATHER", "1")
    blocks = []
    try:
        for rep in range(1, args.reps + 1):
            for arm in ARMS:
                _set_flag(args.arm_flag, "1" if arm == "on" else "0")
                if args.page_seed:
                    # The seed only fires in code mode (on arm); keep it off on the
                    # off arm so the baseline is byte-for-byte the standard gate.
                    _set_flag("IRIS_WB_PAGE_SEED", "1" if arm == "on" else "0")
                if args.self_verify:
                    _set_flag("IRIS_WB_SELF_VERIFY", "1" if arm == "on" else "0")
                if args.two_call:
                    _set_flag("IRIS_WB_TWO_CALL", "1" if arm == "on" else "0")
                if args.see_gather:
                    _set_flag("IRIS_WB_SEE_GATHER", "1" if arm == "on" else "0")
                result_file = _run_block(task_ids, out_dir, arm, rep)
                blocks.append({"arm": arm, "rep": rep, "results": [str(result_file)]})
    finally:
        # Restore every flag to its value before the gate ("" = unset -> "0").
        for name, value in before_flags.items():
            try:
                _set_flag(name, value if value in ("0", "1") else "0")
            except Exception as exc:
                print(f"[gate] WARN could not restore {name}={value!r}: {exc}", file=sys.stderr)
    blocks_file = out_dir / "blocks.json"
    blocks_file.write_text(json.dumps(blocks, indent=1), encoding="utf-8")
    print(f"\n[gate] blocks: {blocks_file}")
    print(f"[gate] analyse with:")
    print(f'  python evals/wb_ab_analysis.py "{blocks_file}" --pairs off:on')
    return 0


if __name__ == "__main__":
    sys.exit(main())
