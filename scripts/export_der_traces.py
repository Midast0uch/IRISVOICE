#!/usr/bin/env python3
"""Export recorded DER sessions as replayable trace files.

specs/der-ground-truth/ REQ-7 (T15).

    python scripts/export_der_traces.py --list
    python scripts/export_der_traces.py --session <id> --out tests/traces/
    python scripts/export_der_traces.py --outcome failure --limit 10 --out tests/traces/
    python scripts/export_der_traces.py --since 2026-08-01 --out tests/traces/

THE POINT
---------
`scripts/validate_der_cli_harness.py` already CONSUMES a trace file and documents
its format. What never existed was a PRODUCER: nothing turned a recorded session
in `data/memory.db` into that format. So every DER investigation started with a
manual reproduction.

This closes that loop. Export once, replay forever — a newly observed defect
becomes a permanent regression fixture instead of a note in a pin.

READ-ONLY, headless, no application (Decisions Locked 2).

TWO DELIBERATE PROPERTIES
-------------------------
* **Redaction (AC4).** User content is omitted, not included-then-stripped, so a
  corpus can be committed. An uncommittable corpus is not a regression suite.
* **Gaps are marked, never interpolated (AC5).** Where the record is incomplete
  the trace says so. A missing terminal frame is exactly the kind of defect the
  corpus should PRESERVE, not smooth over.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1


def _conn(db: str) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _tables(c: sqlite3.Connection) -> set:
    return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def list_sessions(c: sqlite3.Connection, limit: int, outcome: Optional[str],
                  since: Optional[str]) -> List[sqlite3.Row]:
    if "episodes" not in _tables(c):
        return []
    where, params = [], []
    if outcome:
        where.append("outcome_type = ?")
        params.append(outcome)
    if since:
        where.append("timestamp >= ?")
        params.append(since)
    sql = ("SELECT session_id, MIN(timestamp) AS started, COUNT(*) AS episodes, "
           "GROUP_CONCAT(DISTINCT outcome_type) AS outcomes FROM episodes")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY session_id ORDER BY started DESC LIMIT ?"
    params.append(limit)
    return list(c.execute(sql, params))


def export_session(c: sqlite3.Connection, session_id: str) -> Dict[str, Any]:
    """Build one trace in the format validate_der_cli_harness.py consumes."""
    t = _tables(c)
    frames: List[Dict[str, Any]] = []
    gaps: List[str] = []

    commits = []
    if "der_commits" in t:
        commits = list(c.execute(
            "SELECT step_id, verified_label, ts FROM der_commits "
            "WHERE session_id = ? ORDER BY ts", (session_id,)))
    traces = []
    if "der_fan_traces" in t:
        traces = list(c.execute(
            "SELECT step_id, tool, outcome, u, xi, ts FROM der_fan_traces "
            "WHERE session_id = ? ORDER BY ts", (session_id,)))
    if not traces:
        # REQ-7 AC5: say so. Pre-T4 stores have NO execution history at all, and
        # a trace that quietly omitted that would misrepresent the run.
        gaps.append("no der_fan_traces rows for this session - the execution "
                    "history was not recorded (pre-T4 store)")

    card_id = f"card_{session_id}"
    frames.append({
        "event": "task:start",
        "task_id": session_id,
        "card_id": card_id,
        "card_relation": "new",
        "conversation_id": session_id,
        "agent_id": session_id,
        "project_id": None,
        "origin": "initial",
        # REQ-7 AC4: shape only. No description text, no plan title, no user
        # content of any kind - the harness asserts on identity and ordering.
        "steps": [
            {"id": r["step_id"], "status": "pending", "seq": i + 1}
            for i, r in enumerate(traces or commits)
        ],
        "total_steps": len(traces or commits),
    })

    for i, r in enumerate(traces or commits):
        frames.append({
            "event": "task:progress",
            "task_id": session_id,
            "card_id": card_id,
            "conversation_id": session_id,
            "step_id": r["step_id"],
            "step_done": True,
            "seq": i + 1,
            "tool": (r["tool"] if "tool" in r.keys() else None),
            "outcome": (r["outcome"] if "outcome" in r.keys()
                        else r["verified_label"]),
        })

    exits = []
    if "caducean_session_exits" in t:
        cols = {x[1] for x in c.execute("PRAGMA table_info(caducean_session_exits)")}
        sel = "natural_exit" + (", termination_cause" if "termination_cause" in cols else "")
        exits = list(c.execute(
            f"SELECT {sel} FROM caducean_session_exits WHERE session_id = ? "
            "ORDER BY ts DESC LIMIT 1", (session_id,)))

    if exits:
        e = exits[0]
        natural = bool(e["natural_exit"])
        frames.append({
            "event": "task:done" if natural else "task:fail",
            "task_id": session_id,
            "card_id": card_id,
            "conversation_id": session_id,
            "termination_cause": (e["termination_cause"]
                                  if "termination_cause" in e.keys() else None),
        })
    else:
        # A run with no terminal frame is a REAL defect shape. Preserve it.
        gaps.append("no session exit recorded - this run has NO terminal frame")

    return {
        "_schema_version": SCHEMA_VERSION,
        "_session_id": session_id,
        "_gaps": gaps,
        "_redacted": True,
        "frames": frames,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.path.join("data", "memory.db"))
    ap.add_argument("--session")
    ap.add_argument("--outcome", help="filter by episode outcome_type (e.g. failure)")
    ap.add_argument("--since", help="ISO date lower bound")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--out", help="directory to write trace files into")
    ap.add_argument("--list", action="store_true", dest="do_list")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"store not found: {args.db}")
        return 1
    c = _conn(args.db)
    try:
        if args.do_list or not (args.session or args.outcome or args.since):
            rows = list_sessions(c, args.limit, args.outcome, args.since)
            if not rows:
                print("no sessions matched")
                return 1
            print(f"{'SESSION':<40}{'STARTED':<22}{'EPS':>5}  OUTCOMES")
            for r in rows:
                print(f"{str(r['session_id'])[:38]:<40}{str(r['started'])[:20]:<22}"
                      f"{r['episodes']:>5}  {r['outcomes']}")
            return 0

        targets = ([args.session] if args.session
                   else [r["session_id"] for r in
                         list_sessions(c, args.limit, args.outcome, args.since)])
        if not targets:
            print("no sessions matched - nothing exported")
            return 1

        wrote = 0
        for sid in targets:
            trace = export_session(c, sid)
            if not trace["frames"]:
                # REQ-7 edge case: never a silent empty file.
                print(f"  SKIP {sid}: produced no frames")
                continue
            if args.out:
                os.makedirs(args.out, exist_ok=True)
                path = os.path.join(args.out, f"trace_{sid}.json")
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(trace, fh, indent=2)
                gap = f"  ({len(trace['_gaps'])} gap(s))" if trace["_gaps"] else ""
                print(f"  wrote {path} - {len(trace['frames'])} frames{gap}")
                for g in trace["_gaps"]:
                    print(f"      GAP: {g}")
            else:
                print(json.dumps(trace, indent=2))
            wrote += 1
        if wrote == 0:
            print("nothing exported")
            return 1
        print(f"\n{wrote} trace(s) exported.")
        return 0
    finally:
        c.close()


if __name__ == "__main__":
    sys.exit(main())
