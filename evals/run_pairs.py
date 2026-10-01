#!/usr/bin/env python3
"""Two coding tasks at the SAME time - the multi-session coupling gate.

docs/CADUCEAN_LIVE_TEST_PLAN.md T4 + T8: coupling (IRIS_COUPLING_ENABLED) nudges each
concurrent session's Caducean state; one session cannot couple, and the normal eval
runs one task at a time. This runs the coding tasks in PAIRS (both concurrently), with
the runner's own workdir, turn and hidden-test code (run_evals.py), so pass/reply_s are
scored exactly as in a normal run. Run it once per backend config:

    Config B: IRIS_COUPLING_ENABLED=0 (or unset) on the backend
    Config C: IRIS_COUPLING_ENABLED=1 on the backend (restart in between)

Coding tasks only: the mode is global, coding needs developer mode, research personal.
Both sessions of a pair are in the `der` domain (c_eff 1.0, a rational 1:1 pair).

Usage: python evals/run_pairs.py --label coupling_off
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_evals as R  # noqa: E402


async def _one(task: dict, run_dir: Path) -> dict:
    workdir = R._prepare_workdir(task, run_dir)
    started = time.monotonic()
    conv_id, rec = None, None
    try:
        conv = R._http("POST", "/api/conversations", {"title": f"[pair] {task['id']}"}, timeout=90)
        conv_id = conv.get("id") or conv.get("conversation_id")
        rec = await R._run_turn(task, conv_id, workdir, float(task.get("timeout_s", 900)))
    except Exception as exc:  # a broken socket is a failed task, not a crashed run
        rec = {"reply": "", "documents": [], "event_counts": {}, "tools": [],
               "timed_out": False, "ws_error": f"{type(exc).__name__}: {exc}"}
    reply_s = round(rec["reply_at"] - started, 1) if rec.get("reply_at") else None
    notes = []
    if rec.get("timed_out"):
        notes.append("timed out")
    if rec.get("ws_error"):
        notes.append(rec["ws_error"])
    if R._is_error_reply(rec.get("reply", "")) and not rec.get("documents"):
        notes.append("error or empty reply")
    ok, detail = await asyncio.to_thread(R._run_hidden_tests, task, workdir)
    notes.append(f"hidden: {detail}")
    passed = ok and len(notes) == 1
    return {"id": task["id"], "passed": passed, "reply_s": reply_s,
            "seconds": round(time.monotonic() - started, 1), "notes": notes,
            "conversation_id": conv_id, "event_counts": rec.get("event_counts", {})}


async def _run(label: str) -> Path:
    tasks = R._load_tasks(["coding"], [])[:14]
    run_dir = R.EVAL_ROOT / f"pairs-{time.strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    original_mode = R._http("GET", "/api/mode").get("mode")
    try:
        original_projects = json.loads(R.IRIS_CONFIG.read_text(encoding="utf-8")).get("projects") or []
    except (OSError, ValueError):
        original_projects = []
    R._http("POST", "/api/projects", {"projects": [p for p in original_projects
                                                   if p.get("id") != R.EVAL_PROJECT_ID] + [{
        "id": R.EVAL_PROJECT_ID, "name": "IRIS evals", "path": str(R.EVAL_ROOT),
        "mode": "developer", "driveType": "local"}]})
    results = []
    try:
        R._http("POST", "/api/mode", {"mode": "developer"}, timeout=60)
        for i in range(0, len(tasks), 2):
            pair = tasks[i:i + 2]
            R.log.info("[pair %d/%d] %s", i // 2 + 1, len(tasks) // 2,
                       " + ".join(t["id"] for t in pair))
            t0 = time.monotonic()
            got = await asyncio.gather(*(_one(t, run_dir) for t in pair))
            for g in got:
                g["pair"] = i // 2
                R.log.info("    %s %s reply %ss  %s", "PASS" if g["passed"] else "FAIL",
                           g["id"], g["reply_s"], "; ".join(g["notes"]))
            R.log.info("    pair wall %.1fs", time.monotonic() - t0)
            results += got
    finally:
        try:
            R._http("POST", "/api/projects", {"projects": original_projects}, timeout=90)
            if original_mode:
                R._http("POST", "/api/mode", {"mode": original_mode}, timeout=60)
        except Exception as exc:
            R.log.error("could not restore mode/projects: %s", exc)
        shutil.rmtree(run_dir, ignore_errors=True)
    out = R.RESULTS_DIR / f"pairs-{label}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"label": label, "results": results}, indent=1), encoding="utf-8")
    passed = sum(1 for r in results if r["passed"])
    total_reply = sum(r["reply_s"] or 0 for r in results)
    R.log.info("DONE %s: %d/%d passed, reply sum %.0fs -> %s", label, passed, len(results),
               total_reply, out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    args = ap.parse_args()
    if not R._backend_alive(30):
        R.log.error("backend not answering")
        return 2
    asyncio.run(_run(args.label))
    return 0


if __name__ == "__main__":
    sys.exit(main())
