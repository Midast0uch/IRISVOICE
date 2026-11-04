"""The AUROC per consumer AND per label source (the active engine).

MEASURED 2026-11-04: review_verdict measures AUROC 0.4533 and tool_approval
0.5202 on the active engine, and in both the WRONG rows score HIGHER than
the right ones (mean_bad 0.746 vs mean_ok 0.700). The replay of the SAME
recorded states gives review_verdict 0.7015 with monotonic bands, so the
question is not the defect.

The label rule (scripts/calibrate_decision_threshold.py decision_label)
scores a row against its outside_label when it has one and against the
incumbent's answer otherwise. A cohort that mixes the two curves ranks
nothing. This measures each curve on its own.

Usage: python scripts/label_source_split.py [--engine ID]
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for p in (str(_REPO), str(_REPO / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

_spec = importlib.util.spec_from_file_location(
    "cer", _REPO / "scripts" / "consumer_enforcement_report.py")
_cer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cer)

from backend.memory.config import resolve_memory_store_path  # noqa: E402


def auroc(pairs: list[tuple[float, bool]]) -> float | None:
    """The rank-based AUROC (the probability a random wrong row scores lower)."""
    pos = [c for c, ok in pairs if ok]
    neg = [c for c, ok in pairs if not ok]
    if not pos or not neg:
        return None
    wins = 0.0
    for p in pos:
        for n in neg:
            wins += 1.0 if p > n else (0.5 if p == n else 0.0)
    return wins / (len(pos) * len(neg))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="")
    ap.add_argument("--stamps", default="")
    ap.add_argument("--min-rows", type=int, default=20)
    args = ap.parse_args()

    rows, skipped = _cer.load_rows(str(resolve_memory_store_path()), args.engine or None)
    if args.stamps:
        keep = set(s.strip() for s in args.stamps.split(",") if s.strip())
        rows = [r for r in rows if r.get("criteria_version") in keep]
    groups: dict[tuple[str, str], list[tuple[float, bool]]] = collections.defaultdict(list)
    for r in rows:
        groups[(r["consumer_id"], r.get("label_source", "?"))].append(
            (float(r["confidence"]), bool(r["correct"])))

    print(f"rows={len(rows)} skipped={skipped}")
    for (cid, src), pairs in sorted(groups.items()):
        if len(pairs) < args.min_rows:
            continue
        a = auroc(pairs)
        ok = sum(1 for _, o in pairs if o)
        print(f"  {cid:<22} {src:<10} n={len(pairs):<6} correct={ok:<6} "
              f"auroc={a if a is None else round(a, 4)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
