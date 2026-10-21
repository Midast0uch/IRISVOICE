#!/usr/bin/env python3
"""Replay the needs_action cohort through candidate questions (offline).

THE METHODOLOGY INSTRUMENT (2026-10-20). Every question revision v4-v7 was
found and proven here, not in traffic: parse the backend log's
``[needs_action]`` lines (goal, expected, label per site - the DB row does
not store the frame), score each distinct input through the real d1 under a
candidate wording, and judge the result with ``fit_consumer(acting="no")``
so the verdict is the bar's own, out-of-fold, acting-aware.

Cost: minutes on the recorded cohort. A traffic pass costs ~2 hours and can
only confirm - never diagnose (oracle.md 7.2a).

Usage:
  python scripts/replay_needs_action.py                     # live question only
  python scripts/replay_needs_action.py --variants name="..." [name="..." ...]
  python scripts/replay_needs_action.py --log <backend log>  # default: newest

Exit 0 always: a replay is a measurement, not a gate.
"""
from __future__ import annotations

import argparse
import ast
import glob
import os
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
if str(_REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO / "scripts"))

import backend.agent.decision_engine as de  # noqa: E402
from backend.agent.surface_shadow import SURFACE_CONSUMERS  # noqa: E402
from fit_oracle_calibration import fit_consumer  # noqa: E402

LINE_RE = re.compile(
    r"\[needs_action\] step=(\S+) label=(\S+) goal=(.*?) expected=(.*?)\s*$")


def newest_log(explicit: str | None) -> str:
    if explicit:
        return explicit
    logs = sorted(glob.glob(str(_REPO / ".iris-logs" / "backend-*.log")),
                  key=os.path.getmtime)
    for path in reversed(logs):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if "[needs_action]" in line:
                    return path
    raise SystemExit("no backend log carries [needs_action] lines")


def load_pairs(path: str) -> dict:
    """Distinct (goal, expected) -> label, from the log's diagnostic lines."""
    pairs: dict = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = LINE_RE.search(line)
            if not m:
                continue
            goal = ast.literal_eval(m.group(3).strip())
            expected = ast.literal_eval(m.group(4).strip())
            pairs[(goal, expected)] = m.group(2) == "True"
    return pairs


def judge(rows: list) -> tuple:
    """The bar's own verdict on replayed rows: the entry and the failed clauses."""
    entry = fit_consumer(rows, acting="no")
    o = entry["oof"]
    checks = [
        ("rows>=100", entry["rows_distinct"] >= 100),
        ("minority>=5%", min(entry["classes"]["correct"],
                             entry["classes"]["wrong"])
         / max(1, entry["rows_distinct"]) >= 0.05),
        ("auroc>=0.65", (o["auroc"] or 0) >= 0.65),
        ("threshold", entry["threshold"] is not None),
        ("above>=50", entry["rows_above"] >= 50),
        ("prec>=0.90", (o["precision_at_t"] or 0) >= 0.90),
        ("wilson>=0.85", (o["wilson_lb"] or 0) >= 0.85),
        ("ece<=0.05", (o["ece"] or 1) <= 0.05),
        ("act_rows>=50", o.get("acting_rows_above") or 0 >= 50),
        ("act_prec>=0.90", (o.get("acting_precision") or 0) >= 0.90),
        ("act_wilson>=0.85", (o.get("acting_wilson_lb") or 0) >= 0.85),
    ]
    return entry, [name for name, ok in checks if not ok]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--log", help="backend log to read (default: newest with lines)")
    ap.add_argument("--variants", nargs="*", default=[],
                    metavar='name="question text"',
                    help="candidate questions beside the live one")
    args = ap.parse_args()

    path = newest_log(args.log)
    pairs = load_pairs(path)
    print(f"log: {path}")
    print(f"distinct recorded inputs: {len(pairs)} "
          f"(label True: {sum(pairs.values())}, "
          f"False: {len(pairs) - sum(pairs.values())})")

    variants = {"live": SURFACE_CONSUMERS["needs_action"]}
    for item in args.variants:
        name, _, q = item.partition("=")
        if not q:
            raise SystemExit(f'bad variant {item!r}: expected name="question"')
        variants[name] = q

    eng = de.get_decision_engine()
    for name, q in variants.items():
        de.register_declared("needs_action", q, ("yes", "no"))
        rows = []
        for (g, e), lab in pairs.items():
            n = eng.noul("needs_action", g, {"goal": g, "expected": e},
                         true_label="yes", false_label="no")
            if n is None:
                continue
            said = bool(n.true(0.5))
            rows.append({
                "confidence": round(max(n.probability, 1 - n.probability), 4),
                "correct": said == lab,
                "chosen": said,
                "repeats": 1,
            })
        entry, failing = judge(rows)
        o = entry["oof"]
        print(f"\n=== {name}")
        print(f"  rows={entry['rows_distinct']} classes={entry['classes']}")
        print(f"  OOF auroc={o['auroc']} ece={o['ece']}")
        print(f"  t={entry['threshold']} above={entry['rows_above']} "
              f"prec={o['precision_at_t']} wilson={o['wilson_lb']}")
        print(f"  ACTING rows={o.get('acting_rows_above')} "
              f"prec={o.get('acting_precision')} "
              f"wilson={o.get('acting_wilson_lb')}")
        print(f"  failing: {failing if failing else 'NONE - BAR MET'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
