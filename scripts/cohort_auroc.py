"""The cohort's AUROC from the RECORDED confidences (no model call).

MEASURED 2026-11-04: the replay of the recorded review_verdict states (the
live instruction, the live option texts) gives oof_auroc 0.8009 on a 600-row
spread sample, while the report's scoped cohort measures 0.4533 and the
incumbent group 0.3442. The fresh ask reproduces the recorded confidence
exactly (40/40 rows), so the question is not the difference - the ROW SET
or the LABEL is.

This computes the AUROC over the replay's own row set from the recorded
confidences, so the sample and the cohort are compared on the same rows.

Usage:
    python scripts/cohort_auroc.py --consumer review_verdict --engine ID --stamps S
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for p in (str(_REPO), str(_REPO / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from replay_consumer import load_rows  # noqa: E402


def auroc(pairs):
    pos = [c for c, ok in pairs if ok]
    neg = [c for c, ok in pairs if not ok]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consumer", required=True)
    ap.add_argument("--engine", default="")
    ap.add_argument("--stamps", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--since", default="", help="only rows created at/after this ISO stamp")
    args = ap.parse_args()
    stamps = set(s.strip() for s in args.stamps.split(",") if s.strip()) or None
    rows = load_rows(args.consumer, args.limit or 10 ** 9, stamps, args.engine)
    if args.since:
        rows = [r for r in rows if str(r.get("ts") or "") >= args.since]
    pairs = []
    for r in rows:
        pairs.append((float(r["confidence"]), r["chosen"] == r["ref"]))
    print("rows=%d auroc=%s" % (len(pairs), auroc(pairs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
