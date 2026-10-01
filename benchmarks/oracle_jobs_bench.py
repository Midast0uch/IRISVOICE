#!/usr/bin/env python3
"""Oracle decision latency per JOB (decision_engine.ORACLE_JOBS), real model.

Each job is driven through the engine's own `decide` - so the job input rule
(fields + text budget) applies exactly as live - with a LONG input, so the
budget is what bounds the cost. Writes benchmarks/oracle_jobs.json.

Target (owner, 2026-10-01): decisions the reply waits for (interpret, route,
guard) under 150 ms at p50 where the model allows; every job bounded by its
budget (judge_goal at 128 ids is the slowest by design).

MEASUREMENT RULE: keep the machine quiet (no eval, no test run).
Usage: python benchmarks/oracle_jobs_bench.py [--reps 9]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from backend.agent.decision_engine import ORACLE_JOBS, get_decision_engine  # noqa: E402

_LONG = ("the agent read utils.py then edited the range loop in the parser module "
         "ran pytest which reported three passed tests and wrote a summary of the "
         "fix for the user including the file names and the command output ") * 12

# One representative consumer per job, with the option shape it uses live.
_CASES = {
    "interpret": ("mode", ["quick", "spec", "implement", "review"]),
    "route": ("tool_choice", ["read_file", "edit_file", "grep_files", "run_command",
                              "DELEGATE", "NONE"]),
    "guard": ("click_safety", ["safe", "unsafe", "unsure"]),
    "judge_step": ("review_verdict", ["PASS", "FAIL", "RETRY"]),
    "judge_goal": ("done", ["yes", "no"]),
    "shape": ("presentation", ["plain_text", "markdown", "artifact"]),
    "classify_event": ("event_family", ["problem", "safety", "memory", "delivery"]),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=9)
    args = ap.parse_args()
    eng = get_decision_engine()
    eng.decide("tool_choice", ["read_file", "NONE"], {"goal": "warm up"})
    out = {"model": eng.model_id, "reps": args.reps, "jobs": {}}
    for job, (consumer, opts) in _CASES.items():
        frame = {"goal": _LONG, "evidence": _LONG, "open_facts": ["tests pass"],
                 "coverage": 0.5}
        eng.decide(consumer, opts, frame)  # register + warm this shape
        lat = []
        for _ in range(args.reps):
            t = time.perf_counter()
            ds = eng.decide(consumer, opts, frame)
            lat.append((time.perf_counter() - t) * 1000)
            assert ds is not None, f"{consumer} returned None"
        out["jobs"][job] = {
            "consumer": consumer, "budget_ids": ORACLE_JOBS[job].budget_ids,
            "labels": len(opts), "p50_ms": round(statistics.median(lat), 1),
            "max_ms": round(max(lat), 1),
        }
        print(f"{job:15s} {consumer:15s} budget={ORACLE_JOBS[job].budget_ids:4d} "
              f"labels={len(opts)} p50={statistics.median(lat):7.1f} ms max={max(lat):7.1f}")
    (_REPO / "benchmarks" / "oracle_jobs.json").write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
