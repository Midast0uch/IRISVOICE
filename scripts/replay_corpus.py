#!/usr/bin/env python3
"""Replay the whole trace corpus in one command.

specs/der-ground-truth/ REQ-8 (T16/T17).

    python scripts/replay_corpus.py
    python scripts/replay_corpus.py --dir tests/traces

Headless. Exits non-zero on any contract break, so this is CI-shaped: a DER
change is checked against real recorded history without a manual reproduction.

WHAT IT ASSERTS (REQ-8 AC2, extending the existing harness invariants):
  B-1  every trace declares its schema version
  B-2  every started card reaches EXACTLY ONE terminal frame — the invariant
       `scripts/validate_der_cli_harness.py` already pins, extended here across
       every termination cause (T22 / REQ-10 AC3)
  B-3  row ordering keys are present, unique, and ascending (REQ-17)
  B-4  gaps are DECLARED, never silently absent

AC4: coverage is reported — how many traces, of which outcome classes. A corpus
whose composition is invisible can silently stop covering the case it was added
for. AC5: this does NOT replace `validate_store_invariants.py`, which runs
against the LIVE store. A corpus proves the code handles recorded history; only
the live store proves today's recording is honest.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Tuple

DEFAULT_DIR = os.path.join("tests", "traces")


def load(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def check(trace: Dict[str, Any]) -> List[str]:
    """Return a list of contract breaks. Empty means conformant."""
    breaks: List[str] = []
    frames = trace.get("frames") or []

    if trace.get("_schema_version") is None:
        breaks.append("B-1: no _schema_version - cannot tell which scheme minted this")

    starts = [f for f in frames if f.get("event") == "task:start"]
    terminals = [f for f in frames if f.get("event") in ("task:done", "task:fail")]
    started = {f.get("card_id") for f in starts if f.get("card_id")}
    for card in started:
        n = sum(1 for f in terminals if f.get("card_id") == card)
        if n == 0:
            breaks.append(f"B-2: card {card} started but never reached a terminal frame")
        elif n > 1:
            breaks.append(f"B-2: card {card} reached {n} terminal frames; exactly one allowed")

    for f in starts:
        seqs = [s.get("seq") for s in (f.get("steps") or [])]
        if any(s is None for s in seqs):
            breaks.append("B-3: a task:start row carries no ordering key (seq)")
        else:
            if len(set(seqs)) != len(seqs):
                breaks.append(f"B-3: ordering keys collide within one card: {seqs}")
            if seqs != sorted(seqs):
                breaks.append(f"B-3: ordering keys are not ascending: {seqs}")

    if "_gaps" not in trace:
        breaks.append("B-4: no _gaps field - an incomplete record would be invisible")

    return breaks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=DEFAULT_DIR)
    args = ap.parse_args()

    if not os.path.isdir(args.dir):
        print(f"corpus directory not found: {args.dir}")
        return 1
    files = sorted(f for f in os.listdir(args.dir) if f.endswith(".json"))
    if not files:
        print(f"corpus is EMPTY: {args.dir}")
        print("An empty corpus proves nothing - export traces first "
              "(scripts/export_der_traces.py).")
        return 1

    total_breaks = 0
    gap_traces = 0
    rows: List[Tuple[str, int, int, int]] = []
    for name in files:
        trace = load(os.path.join(args.dir, name))
        breaks = check(trace)
        gaps = trace.get("_gaps") or []
        if gaps:
            gap_traces += 1
        total_breaks += len(breaks)
        rows.append((name, len(trace.get("frames") or []), len(gaps), len(breaks)))
        if breaks:
            print(f"FAIL {name}")
            for b in breaks:
                print(f"     {b}")

    print()
    print(f"{'TRACE':<46}{'FRAMES':>7}{'GAPS':>6}{'BREAKS':>8}")
    print("-" * 68)
    for name, nf, ng, nb in rows:
        print(f"{name[:44]:<46}{nf:>7}{ng:>6}{nb:>8}")
    print("-" * 68)
    # AC4: coverage is reported, and AC-edge: what is missing is stated.
    print(f"{len(files)} trace(s) - {gap_traces} carry declared gaps - "
          f"{total_breaks} contract break(s)")
    if gap_traces:
        print("\nNOTE: declared gaps are historical, not failures. Traces exported "
              "from a pre-T4 store have no execution history to carry; they are "
              "kept as regression fixtures of exactly that condition.")
    return 1 if total_breaks else 0


if __name__ == "__main__":
    sys.exit(main())
