#!/usr/bin/env python3
"""Event curation report - EVENT_TAXONOMY section 8, the measurements to read BEFORE
Wormhole / Aperture / NodeChains build on the event stream.

WHAT IT PRINTS (from the `memory_events` table of the app store)
    - events per family and label
    - label_source mix (rule / user / oracle / brain)
    - the unclassified rate (family NULL = Layer 3) and its top labels
    - the share of episodes with OUTSIDE evidence (test / completion / user / recurrence /
      corroboration on a label that is a fact: label_source rule or user). Outside-kind
      evidence on a guessed label (oracle / brain) is reported separately, never counted.
    - recall attribution coverage: delivered recalls that reached a HELPED / MISLED outcome
    - landmark promotions vs stale vs demotions

READ-ONLY: the store is opened with mode=ro. Never writes, never hits the network.

Usage:
    python scripts/event_curation_report.py            # the configured app store
    python scripts/event_curation_report.py --json     # machine readable
    python scripts/event_curation_report.py --db PATH  # another store
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
if str(_REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO / "scripts"))


def _pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def render(rep: dict) -> str:
    if not rep.get("events"):
        return "memory_events: no events (table missing or empty)"
    ep, ra, lm, un = rep["episodes"], rep["recall_attribution"], rep["landmarks"], rep["unclassified"]
    lines = [f"events: {rep['events']}", "", "per family:"]
    lines += [f"  {fam:<14}{n}" for fam, n in sorted(rep["by_family"].items(), key=lambda kv: -kv[1])]
    lines += ["", "per label:"]
    lines += [f"  {(r['family'] or '(none)'):<12}{r['label']:<24}{r['n']}" for r in rep["by_label"]]
    lines += ["", "label_source mix: " + ", ".join(f"{k}={v}" for k, v in sorted(rep["label_source"].items()))]
    lines += ["", f"unclassified (family NULL): {un['n']} ({_pct(un['rate'])})"]
    lines += [f"  {t['label']:<28}{t['n']}" for t in un["top_labels"]]
    lines += [
        "",
        f"episodes: {ep['total']}",
        f"  with outside evidence (fact labels only): {ep['with_outside_evidence']} "
        f"({_pct(ep['share_with_outside_evidence'])})",
        f"  guessed-outside only (oracle/brain labels, NOT counted): {ep['guessed_outside_only']} "
        f"({_pct(ep['share_guessed_outside_only'])})",
        "",
        f"recall attribution: delivered={ra['delivered']} helped={ra['helped']} "
        f"misled={ra['misled']} coverage={_pct(ra['coverage'])}",
        f"landmarks: promoted={lm['promoted']} stale={lm['stale']} demoted={lm['demoted']}",
    ]
    return "\n".join(lines)


def main() -> int:
    from _app_store import app_store_path  # the configured store, not a stale copy

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=None, help="store path (default: the configured app store)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    from backend.memory.event_export import curation_report

    conn = sqlite3.connect(f"file:{args.db or app_store_path()}?mode=ro", uri=True)
    try:
        rep = curation_report(conn)
    finally:
        conn.close()
    print(json.dumps(rep, indent=2) if args.json else render(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
