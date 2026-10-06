#!/usr/bin/env python3
"""Fit the Oracle calibration map, offline (Stage A, 2026-10-05).

WHAT IT DOES
    For each (active backend id, consumer) it reads the DISTINCT ledger rows
    (`consumer_enforcement_report.load_rows`: binary rows normalised to
    confidence-in-the-chosen-answer, repeats collapsed) and fits

      * an isotonic map  confidence -> P(row agrees with the incumbent),
      * the smallest threshold on the calibrated scale whose precision holds,

    then scores both HONESTLY with 5-fold out-of-fold predictions (a map is never
    judged on the rows it was fitted on): ECE (10 bins), Brier, AUROC.

    Output: benchmarks/oracle_calibration.json, read at runtime by
    `backend.agent.oracle_calibration`. Nothing decides from it yet (Stage A).

WHY ISOTONIC WITH A MINIMUM BLOCK
    The raw score is rank-informative at best, so the map must be monotone and
    nothing else is assumed (no sigmoid shape). Plain pool-adjacent-violators
    fits one step per run of equal outcomes and overfits a few hundred rows;
    pooling any block under MIN_BLOCK = 20 rows into its closest neighbour (a
    step at 20 rows has a standard error of about 0.11) keeps every step
    supported by evidence. Pure Python: no new dependency, and the data is a few
    thousand points at most.

THE LABEL
    `calibrate_decision_threshold.decision_label` - agreement with the
    incumbent (brain_choice / brain_bool); a dispatched row, its event outcome.
    The label is the incumbent's answer, not ground truth: a calibrated
    "P(agrees)" is only as good as the incumbent.

Usage:
    python scripts/fit_oracle_calibration.py --dry-run   # print, write nothing
    python scripts/fit_oracle_calibration.py             # write the json
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from backend.agent.consumer_bar import (  # noqa: E402
    MIN_PRECISION,
    MIN_ROWS_ABOVE,
    MIN_WILSON_LB,
)
from backend.agent.oracle_calibration import CALIBRATION_PATH, apply_knots  # noqa: E402

# REQ-18 AC18.1: the project's ONE ECE/Brier/AUROC implementation.
from scripts.calibrate_decision_threshold import _auroc, _ece_brier  # noqa: E402

MIN_BLOCK = 20
FOLDS = 5
# Below two blocks of evidence there is nothing to fit: a map would be one
# constant and its out-of-fold score would measure the fold split, not the map.
MIN_FIT_ROWS = 2 * MIN_BLOCK
LABEL_SOURCE = "agreement with the incumbent (brain_choice/brain_bool)"


def wilson_lb(k: int, n: int, z: float = 1.96) -> float:
    """Lower bound of the Wilson score interval for k successes in n (95%)."""
    if n <= 0:
        return 0.0
    p = k / n
    z2 = z * z
    centre = p + z2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return (centre - margin) / (1 + z2 / n)


def fit_isotonic(
    xs: Sequence[float], ys: Sequence[float], min_block: int = MIN_BLOCK,
) -> List[List[float]]:
    """Monotone (non-decreasing) knots ``[[x, y], ...]``; [] for no data.

    Equal x are one point (weighted), pool-adjacent-violators makes y monotone,
    then any block under ``min_block`` rows is pooled into the neighbour whose y
    is closest. Pooling adjacent blocks of a monotone sequence keeps it
    monotone. A knot sits at the block's mean x and mean y.
    """
    blocks: List[List[float]] = []  # [n, sum_x, sum_y]
    for x, y in sorted(zip(xs, ys)):
        if blocks and blocks[-1][3] == x:
            blocks[-1][0] += 1
            blocks[-1][1] += x
            blocks[-1][2] += y
        else:
            blocks.append([1, x, y, x])  # 4th slot: the group's own x
    for b in blocks:
        del b[3:]

    def mean_y(b): return b[2] / b[0]

    def pool(a, b): return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]

    stack: List[List[float]] = []
    for b in blocks:
        stack.append(b)
        while len(stack) >= 2 and mean_y(stack[-2]) >= mean_y(stack[-1]):
            top = stack.pop()
            stack[-1] = pool(stack[-1], top)
    while len(stack) > 1:
        small = min(range(len(stack)), key=lambda i: stack[i][0])
        if stack[small][0] >= min_block:
            break
        cand = [j for j in (small - 1, small + 1) if 0 <= j < len(stack)]
        j = min(cand, key=lambda j: abs(mean_y(stack[j]) - mean_y(stack[small])))
        lo, hi = min(small, j), max(small, j)
        stack[lo:hi + 1] = [pool(stack[lo], stack[hi])]
    return [[round(b[1] / b[0], 6), round(mean_y(b), 6)] for b in stack]


def pick_threshold(
    cal: Sequence[float], correct: Sequence[bool],
    *, min_rows: int = MIN_ROWS_ABOVE, min_precision: float = MIN_PRECISION,
    min_wilson: float = MIN_WILSON_LB,
) -> Optional[Tuple[float, int, int]]:
    """Smallest t with precision(cal >= t) >= min_precision, Wilson LB >=
    min_wilson, and at least min_rows rows at/above it; ``(t, n_above, k)`` or
    None. Walks the distinct values from the top, so the last qualifying value
    is the smallest."""
    order = sorted(range(len(cal)), key=lambda i: cal[i], reverse=True)
    best = None
    k = 0
    i = 0
    while i < len(order):
        v = cal[order[i]]
        j = i
        while j < len(order) and cal[order[j]] == v:
            k += 1 if correct[order[j]] else 0
            j += 1
        if j >= min_rows and k / j >= min_precision and wilson_lb(k, j) >= min_wilson:
            best = (v, j, k)
        i = j
    return best


def oof_calibrated(
    xs: Sequence[float], correct: Sequence[bool],
    folds: int = FOLDS, min_block: int = MIN_BLOCK, seed: int = 0,
) -> List[float]:
    """Each row's calibrated confidence from a map that never saw that row.

    Stratified by label so a small minority is spread across folds."""
    rng = random.Random(seed)
    fold_of = [0] * len(xs)
    for label in (True, False):
        idx = [i for i in range(len(xs)) if bool(correct[i]) is label]
        rng.shuffle(idx)
        for pos, i in enumerate(idx):
            fold_of[i] = pos % folds
    out = [0.0] * len(xs)
    for f in range(folds):
        train = [i for i in range(len(xs)) if fold_of[i] != f]
        knots = fit_isotonic([xs[i] for i in train],
                             [1.0 if correct[i] else 0.0 for i in train], min_block)
        for i in range(len(xs)):
            if fold_of[i] == f:
                out[i] = round(apply_knots(knots, xs[i]), 4) if knots else 0.0
    return out


def fit_consumer(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The calibration entry for ONE consumer's distinct rows of one backend.

    ``rows`` carry ``confidence`` (in the chosen answer) and ``correct``; a row
    may carry ``repeats`` (how many ledger rows it stands for)."""
    data = sorted((float(r["confidence"]), bool(r["correct"])) for r in rows)
    xs = [d[0] for d in data]
    ok = [d[1] for d in data]
    a, b = sum(ok), len(ok) - sum(ok)
    entry: Dict[str, Any] = {
        "method": "isotonic",
        "knots": [],
        "threshold": None,
        "rows_distinct": len(data),
        "rows_raw": sum(int(r.get("repeats", 1)) for r in rows),
        "rows_above": 0,
        "oof": {"ece": None, "brier": None, "auroc": None,
                "precision_at_t": None, "wilson_lb": None},
        "classes": {"correct": a, "wrong": b},
        "fitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "label_source": LABEL_SOURCE,
    }
    if len(data) < MIN_FIT_ROWS or a == 0 or b == 0:
        return entry  # nothing honest to fit; the bar's own clauses name why
    entry["knots"] = fit_isotonic(xs, [1.0 if v else 0.0 for v in ok])
    cal = oof_calibrated(xs, ok)
    scored = [{"confidence": c, "correct": v} for c, v in zip(cal, ok)]
    ece, brier = _ece_brier(scored)
    entry["oof"].update(ece=ece, brier=brier, auroc=_auroc(scored))
    pick = pick_threshold(cal, ok)
    if pick is not None:
        t, n_above, k = pick
        entry["threshold"] = t
        entry["rows_above"] = n_above
        entry["oof"].update(precision_at_t=round(k / n_above, 4),
                            wilson_lb=round(wilson_lb(k, n_above), 4))
    return entry


def fit_all(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """consumer id -> entry, for rows already scoped to ONE backend."""
    by: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["consumer_id"], []).append(r)
    return {cid: fit_consumer(grp) for cid, grp in sorted(by.items())}


def main() -> int:
    ap = argparse.ArgumentParser(description="Fit the Oracle calibration map.")
    from _app_store import app_store_path  # the configured store, not a stale copy

    ap.add_argument("--db", default=app_store_path())
    ap.add_argument("--out", default=str(CALIBRATION_PATH))
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    args = ap.parse_args()

    # Lazy: the report imports this module for fit_consumer.
    from scripts.consumer_enforcement_report import load_rows, thresholds_by_consumer

    db = Path(args.db)
    if not db.is_file():
        print(f"UNVERIFIED: db not found: {db}")
        return 4
    _, config = thresholds_by_consumer()
    backend_id = config.get("backend_id")
    if not backend_id:
        print("UNVERIFIED: active backend id unresolved; a map belongs to one backend")
        return 4
    try:
        rows, skipped = load_rows(str(db), backend_id)
    except sqlite3.Error as e:
        print(f"UNVERIFIED: cannot read ledger ({e})")
        return 4

    fitted = fit_all(rows)
    print(f"backend={backend_id} distinct_rows={len(rows)} skipped={skipped}")
    for cid, e in fitted.items():
        o = e["oof"]
        print(f"[{cid}] distinct={e['rows_distinct']} raw={e['rows_raw']} "
              f"classes={e['classes']} knots={len(e['knots'])} "
              f"oof_auroc={o['auroc']} oof_ece={o['ece']} threshold={e['threshold']} "
              f"above={e['rows_above']} precision@t={o['precision_at_t']} "
              f"wilson_lb={o['wilson_lb']}")
    if args.dry_run:
        print("dry run: nothing written")
        return 0

    out = Path(args.out)
    try:  # keep other backends' maps; this run replaces only its own
        doc = json.loads(out.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            doc = {}
    except Exception:  # noqa: BLE001 - absent/unreadable = start fresh
        doc = {}
    doc[backend_id] = fitted
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
