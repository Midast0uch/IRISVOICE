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
    MIN_ACTING_ROWS_ABOVE,
    MIN_PRECISION,
    MIN_ROWS_ABOVE,
    MIN_WILSON_LB,
)
from backend.agent.oracle_calibration import CALIBRATION_PATH, apply_knots  # noqa: E402

# REQ-18 AC18.1: the project's ONE ECE/Brier/AUROC implementation.
from scripts.calibrate_decision_threshold import _auroc, _ece_brier  # noqa: E402

MIN_BLOCK = 20
FOLDS = 5

# The OWNER's policy threshold per consumer, in RAW confidence units. The bar
# picks the LOWEST calibrated threshold that meets its precision floor (maximum
# coverage, policy A). `tool_choice` runs policy B - obey only when confident -
# so its threshold is the calibrated value at this raw confidence instead.
# Measured 2026-11-07 (action-class label): raw 0.70 selects 122 of 290 rows at
# 95.9% precision (Wilson 90.8%) vs 90.7% overall. Only applies when that
# consumer's rows are fitted; the bar still checks every other clause.
# 2026-11-10: tool_choice is certified as the CLASS ROLE - its confidence is
# the class margin (consumer_enforcement_report.class_margin_confidence) and its
# policy point is the live class gate, CLASS_MARGIN_MIN (0.30): the bar measures
# precision exactly where the app acts (753 rows above at 0.936 on tc-decide-v9).
from backend.agent.tool_choice_action_class import CLASS_MARGIN_MIN  # noqa: E402

POLICY_RAW_THRESHOLD = {"tool_choice": CLASS_MARGIN_MIN}
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
    *,
    min_rows: int = MIN_ROWS_ABOVE, min_precision: float = MIN_PRECISION,
    min_wilson: float = MIN_WILSON_LB,
    chosen: Optional[Sequence[Any]] = None, acting_key: Optional[str] = None,
    min_acting_rows: int = MIN_ACTING_ROWS_ABOVE,
) -> Optional[Tuple[float, int, int]]:
    """Smallest t with precision(cal >= t) >= min_precision, Wilson LB >=
    min_wilson, and at least min_rows rows at/above it; ``(t, n_above, k)`` or
    None. Walks the distinct values from the top, so the last qualifying value
    is the smallest.

    ACTING SIDE (2026-10-20): when ``chosen`` and ``acting_key`` are given,
    a threshold must ALSO hold the acting clauses at/above it (rows >=
    min_acting_rows, precision >= min_precision, Wilson LB >= min_wilson).
    Without this the clean non-acting side drags the pick to the floor and
    clause 8 judges every acting answer ever given, including the weak ones
    the threshold was supposed to exclude - the measured case (needs_action:
    yes side 0.98 clean, threshold picked at 0.4762, acting side 0.8172
    judged there). The pick can only move UP, so this makes enforcement more
    restrictive, never less."""
    order = sorted(range(len(cal)), key=lambda i: cal[i], reverse=True)
    best = None
    k = 0
    i = 0
    ka = 0  # correct acting rows at/above the current value
    ja = 0  # acting rows at/above the current value
    while i < len(order):
        v = cal[order[i]]
        j = i
        while j < len(order) and cal[order[j]] == v:
            k += 1 if correct[order[j]] else 0
            if chosen is not None and acting_key is not None \
                    and _answer_key(chosen[order[j]]) == acting_key:
                ja += 1
                ka += 1 if correct[order[j]] else 0
            j += 1
        if j >= min_rows and k / j >= min_precision and wilson_lb(k, j) >= min_wilson:
            acting_ok = True
            if chosen is not None and acting_key is not None:
                acting_ok = (
                    ja >= min_acting_rows
                    and ka / ja >= min_precision
                    and wilson_lb(ka, ja) >= min_wilson
                )
            if acting_ok:
                best = (v, j, k)
        i = j
    return best


def assign_folds(
    correct: Sequence[bool], groups: Optional[Sequence[Optional[str]]] = None,
    folds: int = FOLDS, seed: int = 0,
) -> Tuple[List[int], Dict[str, Any]]:
    """Each row's fold, plus how the split was made.

    Without groups: stratified by label so a small minority is spread across
    folds (the original split, unchanged row for row).

    GROUPED (2026-11-09): rows of one group never sit on both sides of a fold.
    Measured on tool_approval/v6: 6482 rows came from 92 eval tasks run again
    and again, so near-identical rows of one task were trained on and scored in
    the same fit and the OOF numbers were optimistic (oracle.md 12.8). Whole
    groups are dealt, largest first, to the fold that stays most even in rows
    AND in the rarer label. A group larger than one fold cannot be held out and
    is split into single rows (counted in ``split_rows``: the synthetic
    ``de-shadow-battery`` session holds most tool_choice rows, all distinct
    inputs). Fewer whole units than folds falls back to the ungrouped split."""
    rng = random.Random(seed)
    n = len(correct)
    fold_of = [0] * n

    def _ungrouped(info: Dict[str, Any]) -> Tuple[List[int], Dict[str, Any]]:
        for label in (True, False):
            idx = [i for i in range(n) if bool(correct[i]) is label]
            rng.shuffle(idx)
            for pos, i in enumerate(idx):
                fold_of[i] = pos % folds
        return fold_of, info

    if not groups or not any(groups):
        return _ungrouped({"grouped": False})
    members: Dict[Any, List[int]] = {}
    for i, g in enumerate(groups):
        members.setdefault(g if g else ("row", i), []).append(i)
    units: List[List[int]] = []
    split = 0
    for idx in members.values():
        if len(idx) > n / folds:
            units.extend([i] for i in idx)
            split += len(idx)
        else:
            units.append(idx)
    if len(units) < folds:
        return _ungrouped({"grouped": False, "reason": f"{len(units)} groups < {folds} folds"})
    rare = sum(1 for v in correct if v) * 2 < n  # the rarer label
    tot_rare = max(1, sum(1 for v in correct if bool(v) is rare))
    rng.shuffle(units)
    units.sort(key=len, reverse=True)
    f_rows = [0] * folds
    f_rare = [0] * folds
    for u in units:
        u_rare = sum(1 for i in u if bool(correct[i]) is rare)
        f = min(range(folds), key=lambda k: (
            (f_rare[k] + u_rare) / tot_rare + (f_rows[k] + len(u)) / n, k))
        f_rows[f] += len(u)
        f_rare[f] += u_rare
        for i in u:
            fold_of[i] = f
    return fold_of, {"grouped": True, "groups": len(members), "split_rows": split}


def rule_baseline(
    keys: Sequence[str], chosen: Sequence[Any], correct: Sequence[bool],
    probability: Sequence[Optional[float]], reference: Sequence[Any],
    fold_of: Sequence[int], folds: int = FOLDS, prior: float = 2.0,
) -> Optional[Dict[str, Any]]:
    """The model against a TRIVIAL RULE that decides without it, on the same folds.

    The rule sees only the input's key (the proposed tool when the question
    has one; otherwise nothing, so it is the base rate / most common answer)
    and learns from the other folds. Measured 2026-11-09 (oracle.md 12.8): on
    tool_approval a per-tool failure rate passed the bar by itself and beat d1
    on every number - it measured which tools were broken on this machine.

      * yes/no consumer (rows carry P(yes)): the TRUTH is the chosen answer
        when it was right, the other one when wrong. Metric: how well P(yes)
        ranks the truth (AUROC), model vs the rule's P(yes | key).
      * choice consumer: the rule gives the most common reference answer for
        the key. Metric: accuracy, model vs rule.

    ``_rule_ok`` (popped by ``fit_consumer``) holds, per row, whether the
    rule's own answer would have been right - for the acting-region numbers.

    None when it cannot be measured (one truth class; a choice consumer whose
    reference is an outcome, not an answer)."""
    n = len(keys)
    binary = n > 0 and all(p is not None for p in probability)
    if binary:
        truth = [(_answer_key(chosen[i]) == "yes") == bool(correct[i]) for i in range(n)]
    elif n > 0 and all(ref is not None for ref in reference):
        truth = [_answer_key(ref) for ref in reference]
    else:
        return None
    rule: List[Any] = [None] * n
    for f in range(folds):
        train = [i for i in range(n) if fold_of[i] != f]
        if not train:
            continue
        stats: Dict[str, Dict[Any, int]] = {}
        overall: Dict[Any, int] = {}
        for i in train:
            st = stats.setdefault(keys[i], {})
            st[truth[i]] = st.get(truth[i], 0) + 1
            overall[truth[i]] = overall.get(truth[i], 0) + 1
        base_yes = overall.get(True, 0) / len(train)
        top = max(sorted(overall, key=str), key=lambda a: overall[a])
        for i in range(n):
            if fold_of[i] != f:
                continue
            st = stats.get(keys[i], {})
            if binary:
                cnt = sum(st.values())
                rule[i] = (st.get(True, 0) + prior * base_yes) / (cnt + prior)
            else:
                rule[i] = max(sorted(st, key=str), key=lambda a: st[a]) if st else top
    if binary:
        if len(set(truth)) < 2:
            return None
        model = _auroc([{"confidence": probability[i], "correct": truth[i]} for i in range(n)])
        base = _auroc([{"confidence": rule[i], "correct": truth[i]} for i in range(n)])
        metric = "truth_auroc"
    else:
        model = round(sum(1 for v in correct if v) / n, 4)
        base = round(sum(1 for i in range(n) if rule[i] == truth[i]) / n, 4)
        metric = "accuracy"
    if binary:
        rule_ok = [rule[i] is not None and (rule[i] >= 0.5) == truth[i] for i in range(n)]
    else:
        rule_ok = [rule[i] == truth[i] for i in range(n)]
    return {"metric": metric, "model": model, "rule": base, "keys": len(set(keys)),
            "_rule_ok": rule_ok}


# The "no map" map: raw confidence used as it is (apply_knots is piecewise
# linear, so these two knots are the identity on [0, 1]).
IDENTITY_KNOTS = [[0.0, 0.0], [1.0, 1.0]]


def choose_map(
    xs: Sequence[float], correct: Sequence[bool],
    groups: Optional[Sequence[Optional[str]]] = None,
    min_block: int = MIN_BLOCK, seed: int = 0,
) -> Tuple[List[List[float]], str]:
    """The isotonic map, or NO map, whichever is better calibrated on groups
    these rows' own inner folds hold out; ``(knots, method)``.

    Measured 2026-11-09 (route_v2/binary-v1, 1240 rows): under grouped folds
    the isotonic map was overconfident on unseen eval tasks (top bin 0.963
    against 0.931 observed; ECE 0.049-0.064 over 20 seeds) while the RAW
    confidence held ECE 0.042. A map fitted on some tasks learns their
    quirks; it must beat using no map at all, measured on held-out groups.
    Used inside each outer fold (nested), so the choice is scored on rows it
    never saw. Below two inner blocks per fold the isotonic map is kept."""
    ys = [1.0 if v else 0.0 for v in correct]
    knots = fit_isotonic(xs, ys, min_block)
    if len(xs) < FOLDS * MIN_FIT_ROWS or not knots:
        return knots, "isotonic"
    inner, _ = assign_folds(correct, groups, FOLDS, seed)
    cal = [0.0] * len(xs)
    for f in range(FOLDS):
        tr = [i for i in range(len(xs)) if inner[i] != f]
        k = fit_isotonic([xs[i] for i in tr], [ys[i] for i in tr], min_block)
        for i in range(len(xs)):
            if inner[i] == f:
                cal[i] = apply_knots(k, xs[i]) if k else 0.0
    ece_iso = _ece_brier([{"confidence": c, "correct": v} for c, v in zip(cal, correct)])[0]
    ece_raw = _ece_brier([{"confidence": x, "correct": v} for x, v in zip(xs, correct)])[0]
    if ece_iso is not None and ece_raw is not None and ece_raw < ece_iso:
        return [list(k) for k in IDENTITY_KNOTS], "identity"
    return knots, "isotonic"


def oof_calibrated(
    xs: Sequence[float], correct: Sequence[bool],
    folds: int = FOLDS, min_block: int = MIN_BLOCK, seed: int = 0,
    fold_of: Optional[Sequence[int]] = None,
    groups: Optional[Sequence[Optional[str]]] = None, choose: bool = False,
) -> List[float]:
    """Each row's calibrated confidence from a map that never saw that row.

    ``fold_of`` from ``assign_folds``; omitted, the ungrouped stratified split.
    ``choose``: each outer fold picks isotonic-or-identity with ``choose_map``
    on its training rows alone (nested), so the score includes the choice."""
    if fold_of is None:
        fold_of, _ = assign_folds(correct, None, folds, seed)
    out = [0.0] * len(xs)
    for f in range(folds):
        train = [i for i in range(len(xs)) if fold_of[i] != f]
        if choose:
            knots, _m = choose_map([xs[i] for i in train], [correct[i] for i in train],
                                   [groups[i] for i in train] if groups else None,
                                   min_block, seed)
        else:
            knots = fit_isotonic([xs[i] for i in train],
                                 [1.0 if correct[i] else 0.0 for i in train], min_block)
        for i in range(len(xs)):
            if fold_of[i] == f:
                out[i] = round(apply_knots(knots, xs[i]), 4) if knots else 0.0
    return out


def fit_consumer(
    rows: Sequence[Dict[str, Any]], *, acting: Optional[str] = None,
    consumer_id: Optional[str] = None,
) -> Dict[str, Any]:
    """The calibration entry for ONE consumer's distinct rows of one backend.

    ``rows`` carry ``confidence`` (in the chosen answer) and ``correct``; a row
    may carry ``repeats`` (how many ledger rows it stands for) and ``chosen``
    (the answer the engine gave).

    ``consumer_id`` applies the owner's POLICY_RAW_THRESHOLD (policy B) so the
    entry's threshold is the calibrated value at that raw confidence, not the
    bar's maximum-coverage minimum. Every other clause still applies.

    ``acting`` names the ONE answer that changes behaviour (consumer_bar.
    ACTING_ANSWER). When given, the entry also carries that answer's precision
    and Wilson LB at the calibrated threshold: the side that actually acts, so
    the bar cannot be carried by the side that changes nothing.

    REQ-7 AC7.2 NO MIXED CURVES (2026-10-22): a consumer can hold rows on two
    references - an OUTCOME (`outside_label`, what actually happened) and
    PARITY (`correct`, whether d1 agreed with the incumbent reviewer). They
    answer different questions and must never share a curve: measured live,
    review_verdict read 0.7114 on its 1471 outcome rows and 0.6242 when 576
    parity rows were blended in - parity alone demoted it. When ANY outcome
    rows exist the fit uses ONLY those; the dropped parity count is reported
    in `mixed_dropped` so the trade is visible. A consumer with no outcome
    rows keeps every row, byte-identical to before."""
    outcome_rows = [r for r in rows if r.get("outside_label") is not None]
    source = "parity"
    if outcome_rows:
        mixed_dropped = len(rows) - len(outcome_rows)
        rows = outcome_rows
        source = "outcome"
    else:
        mixed_dropped = 0  # nothing was dropped: there was no other curve
    data = sorted(
        ((float(r["confidence"]), bool(r["correct"]), r.get("chosen"),
          r.get("group"), str(r.get("rule_key") or ""), r.get("probability"),
          r.get("reference"))
         for r in rows),
        key=lambda p: p[0],
    )
    xs = [d[0] for d in data]
    ok = [d[1] for d in data]
    ch = [d[2] for d in data]
    grp = [d[3] for d in data]
    rkey = [d[4] for d in data]
    prob = [d[5] for d in data]
    ref = [d[6] if source == "parity" else None for d in data]
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
        "folds": None,
        "baseline": None,
        "classes": {"correct": a, "wrong": b},
        "fitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "label_source": (
            "step outcome (verified_label)" if source == "outcome" else LABEL_SOURCE
        ),
        "reference": source,
        "mixed_dropped": mixed_dropped,
    }
    if len(data) < MIN_FIT_ROWS or a == 0 or b == 0:
        return entry  # nothing honest to fit; the bar's own clauses name why
    entry["knots"], entry["method"] = choose_map(xs, ok, grp)
    fold_of, entry["folds"] = assign_folds(ok, grp)
    cal = oof_calibrated(xs, ok, fold_of=fold_of, groups=grp, choose=True)
    scored = [{"confidence": c, "correct": v} for c, v in zip(cal, ok)]
    ece, brier = _ece_brier(scored)
    entry["oof"].update(ece=ece, brier=brier, auroc=_auroc(scored))
    entry["baseline"] = rule_baseline(rkey, ch, ok, prob, ref, fold_of)
    rule_ok = entry["baseline"].pop("_rule_ok") if entry["baseline"] else None
    pick = pick_threshold(
        cal, ok,
        chosen=ch if acting else None,
        acting_key=_answer_key(acting) if acting else None,
    )
    if pick is not None:
        t, n_above, k = pick
        entry["threshold"] = t
        entry["rows_above"] = n_above
        entry["oof"].update(precision_at_t=round(k / n_above, 4),
                            wilson_lb=round(wilson_lb(k, n_above), 4))
        if rule_ok is not None:
            # where the Oracle would ACT: its precision there vs the rule's
            # accuracy on the same rows (reported; the clause reads model/rule)
            sel = [i for i in range(len(xs)) if cal[i] >= t]
            entry["baseline"]["acting_region"] = {
                "rows": len(sel),
                "model": round(k / n_above, 4),
                "rule": round(sum(1 for i in sel if rule_ok[i]) / len(sel), 4) if sel else None,
            }
        if acting:
            want = _answer_key(acting)
            sel = [i for i in range(len(xs))
                   if cal[i] >= t and _answer_key(ch[i]) == want]
            kk = sum(1 for i in sel if ok[i])
            entry["oof"].update(
                acting_answer=want,
                acting_rows_above=len(sel),
                acting_precision=(round(kk / len(sel), 4) if sel else None),
                acting_wilson_lb=(round(wilson_lb(kk, len(sel)), 4) if sel else None),
            )
    _raw = POLICY_RAW_THRESHOLD.get(str(consumer_id or ""))
    if _raw is not None and entry["knots"]:
        # Policy B: the calibrated value at the owner's RAW confidence, not the
        # bar's maximum-coverage minimum. Re-measure the selected set so the
        # record carries the numbers actually enforced.
        _t = round(apply_knots(entry["knots"], float(_raw)), 4)
        _sel = [i for i in range(len(xs)) if cal[i] >= _t]
        if _sel:
            _k = sum(1 for i in _sel if ok[i])
            _n = len(_sel)
            entry["threshold"] = _t
            entry["rows_above"] = _n
            entry["oof"].update(
                precision_at_t=round(_k / _n, 4),
                wilson_lb=round(wilson_lb(_k, _n), 4),
            )
    return entry


def _answer_key(ans: Any) -> str:
    """Normalize an answer to a comparable word: True -> 'yes', False -> 'no'."""
    if isinstance(ans, bool):
        return "yes" if ans else "no"
    return str(ans).strip().lower()


def fit_all(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """consumer id -> entry, for rows already scoped to ONE backend.

    A consumer in ACTING_ENFORCED is fitted with its acting answer, so the
    threshold WRITTEN for the runtime is the same acting-aware pick the bar
    was measured on (2026-10-21: the fit wrote 0.5 for needs_action while the
    report's bar held at 0.6244 - the runtime would have enforced a more
    permissive threshold than the evidence was measured at).
    """
    from backend.agent.consumer_bar import ACTING_ANSWER, ACTING_ENFORCED

    by: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["consumer_id"], []).append(r)
    return {
        cid: fit_consumer(
            grp,
            acting=ACTING_ANSWER.get(cid) if cid in ACTING_ENFORCED else None,
            consumer_id=cid,
        )
        for cid, grp in sorted(by.items())
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Fit the Oracle calibration map.")
    from _app_store import app_store_path  # the configured store, not a stale copy

    ap.add_argument("--db", default=app_store_path())
    ap.add_argument("--out", default=str(CALIBRATION_PATH))
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    ap.add_argument("--scope", action="append", default=[], metavar="CONSUMER=STAMP",
                    help="fit CONSUMER on its rows of ONE criteria_version only "
                         "(the same scope the bar record is written with)")
    args = ap.parse_args()

    # Lazy: the report imports this module for fit_consumer.
    from scripts.consumer_enforcement_report import (
        declared_only,
        load_rows,
        parse_scopes,
        scope_rows,
        thresholds_by_consumer,
    )

    db = Path(args.db)
    if not db.is_file():
        print(f"UNVERIFIED: db not found: {db}")
        return 4
    _, config = thresholds_by_consumer()
    backend_id = config.get("backend_id")
    # FIXED 2026-10-11: rows were filtered by `backend_id` ("model|readout")
    # while a row's `engine` holds the MODEL id ("d1-3b-ad-q4_k_m+letters"),
    # so EVERY d1 row read as other_backend and nothing was ever fitted; and
    # the map was written under `backend_id` while the runtime looks a
    # threshold up under the consumer's full decision identity
    # (decision_engine._current_backend_identity(consumer)). Rows now filter on
    # `engine_id` (the report's own filter) and each consumer's entry is ALSO
    # written under its decision identity - the key decides() reads.
    engine_id = config.get("engine_id")
    if not backend_id or not engine_id:
        print("UNVERIFIED: active backend id unresolved; a map belongs to one backend")
        return 4
    try:
        rows, skipped = load_rows(str(db), engine_id)
    except sqlite3.Error as e:
        print(f"UNVERIFIED: cannot read ledger ({e})")
        return 4
    scopes = parse_scopes(args.scope)
    rows = declared_only(scope_rows(rows, scopes), skipped)

    fitted = fit_all(rows)
    for cid, e in fitted.items():
        if cid in scopes:
            e["criteria_version"] = scopes[cid]
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
    # the runtime key: each consumer under ITS decision identity
    from backend.agent.decision_engine import CURRENT_READOUT_MODE, decision_identity

    _cap = int(config.get("candidate_cap") or 0)
    for cid, e in fitted.items():
        doc.setdefault(decision_identity(str(engine_id), CURRENT_READOUT_MODE, cid, _cap),
                       {})[cid] = e
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
