#!/usr/bin/env python3
"""Calibration for the decision engine (specs/tool-decision-engine REQ-6/REQ-10,
REQ-18/T24, REQ-22/T31).

Reads `system_events` from data/memory.db (READ-ONLY URI — D13), extracts rows
whose payload carries a `decision` block, and reports:

  * reliability table: confidence bucket -> observed accuracy (per consumer,
    per engine model id)
  * ECE + Brier score (AC18.1/T24) alongside precision-at-threshold
  * the coverage/accuracy-above-threshold curve (AC22.2/T31 — the operating
    point is re-derivable from it, D13)
  * recommended threshold maximizing auto-executed fraction s.t. accuracy>=0.90
    (refuses under N=50 engine-routed decisions, AC6.2)
  * per-route decision latency p50/p95 and escalation rate (AC10.2)
  * big-model calls avoided = 1 - escalation rate (engine-routed rows)

SOFTMAX_TAU RESOLVED (T24/REQ-21): the fixed sharpening is DELETED with the
LFM path — the ONNX backend's softmax is natively calibrated (D13), so the
reported confidence IS the model's probability, not a sharpened value
reported as one.

Never writes. Never hits the network. Exit 0 = report produced; exit 3 =
insufficient data; exit 4 = DB encrypted/unreadable (reports UNVERIFIED).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from pathlib import Path

REFUSE_BELOW = 50
ACCURACY_TARGET = 0.90


def _connect(db: str) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _load_decisions(db: str, since: str | None = None) -> list[dict]:
    rows: list[dict] = []
    with _connect(db) as c:
        q = (
            "SELECT event_id, session_id, outcome, interaction_payload, "
            "created_at FROM system_events WHERE event_type='tool_execution'"
        )
        args: tuple = ()
        if since:
            q += " AND created_at >= ?"
            args = (since,)
        for r in c.execute(q, args):
            try:
                payload = json.loads(r["interaction_payload"] or "{}")
            except Exception:
                continue
            d = payload.get("decision")
            if not isinstance(d, dict):
                continue
            outcome = None if payload.get("tool") == "no_tool" else r["outcome"]
            rows.append(
                {
                    "engine": d.get("engine"),
                    "consumer_id": d.get("consumer_id"),
                    "route": d.get("route"),
                    "confidence": d.get("confidence"),
                    "chosen": d.get("chosen"),
                    "escalated": bool(d.get("escalated")),
                    "retried": bool(d.get("retried")),
                    "latency_ms": d.get("decision_latency_ms")
                    or d.get("engine_latency_ms"),
                    "correct": outcome in ("success", "reason", None),
                    "created_at": r["created_at"],
                }
            )
    return rows


def _buckets(rows: list[dict], edges=(0.0, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.01)):
    """confidence bucket -> (n, accuracy)."""
    agg: dict[tuple, list] = defaultdict(list)
    for r in rows:
        c = r.get("confidence")
        if c is None:
            continue
        for lo, hi in zip(edges, edges[1:]):
            if lo <= c < hi:
                agg[(lo, hi)].append(bool(r["correct"]))
                break
    return {
        f"{lo:.2f}-{hi:.2f}": (
            len(v), round(sum(v) / len(v), 3) if v else None
        )
        for lo, hi in sorted(agg)
        for v in [agg[(lo, hi)]]
    }


def _pct(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    xs = sorted(vals)
    i = min(len(xs) - 1, max(0, int(p * len(xs))))
    return xs[i]


# ── REQ-9 AC9.2 (T12): per-class accuracy for the two WEB intent classes ────
# REQ-9's whole point is that the engine must separate an INSTANT factual
# lookup (`search`) from research-class intent (`crawler_query`). A pooled
# accuracy number hides a classifier that is good at one class and blind to
# the other — which is exactly the failure REQ-9 exists to catch. (The offline
# battery had ZERO cases in either class before T12; both classes are now in
# scripts/fixtures/decision_engine_cases.json.)
WEB_INTENT_CLASSES: dict[str, str] = {
    "search": "instant_lookup",
    "crawler_query": "research",
}


def intent_class(row: dict) -> str:
    """Map a decision row to its intent class (AC9.2).

    Classification is by the tool the engine CHOSE. The ledger row carries no
    goal text, and the classes the requirement names ARE the two web tiers, so
    the chosen tool is the authoritative signal available at calibration time.
    Anything else lands in ``other`` and is reported but not judged.
    """
    return WEB_INTENT_CLASSES.get(str(row.get("chosen") or ""), "other")


def per_class_accuracy(rows: list[dict], classifier=intent_class) -> dict:
    """intent class -> {n, accuracy} (AC9.2)."""
    agg: dict[str, list] = defaultdict(list)
    for r in rows:
        agg[classifier(r)].append(bool(r["correct"]))
    return {
        k: {
            "n": len(v),
            "accuracy": round(sum(v) / len(v), 3) if v else None,
        }
        for k, v in sorted(agg.items())
    }


def recommend_threshold(rows: list[dict], target: float = ACCURACY_TARGET):
    """Highest coverage threshold meeting the accuracy target.

    Sample size n = every row with a confidence (escalated rows count toward
    the N>=50 harvest rule). Accuracy at t = P(correct | conf >= t) over ALL
    rows — escalated rows at conf < t simply never enter its numerator, while
    at t <= their conf they represent decisions the engine would've made.
    """
    eng = [r for r in rows if r.get("confidence") is not None]
    if len(eng) < REFUSE_BELOW:
        return None, len(eng)
    best = None
    for t in [x / 100 for x in range(50, 100)]:
        kept = [r for r in eng if r["confidence"] >= t]
        if not kept:
            continue
        acc = sum(1 for r in kept if r["correct"]) / len(kept)
        if acc >= target and (best is None or t < best):
            best = t
    return best, len(eng)


def _ece_brier(rows: list[dict], n_bins: int = 10):
    """AC18.1 (T24): expected calibration error + Brier score.

    ECE: sum over confidence bins of |observed accuracy - mean confidence|
    weighted by bin share. Brier: mean (confidence - correct)^2. Both are
    the calibration-quality numbers the enforcement gate reads (AC18.4) —
    a consumer flips only when ECE is within bound, never on precision
    alone. Returns (None, None) when no row carries a confidence.
    """
    eng = [r for r in rows if r.get("confidence") is not None]
    if not eng:
        return None, None
    bins: dict[int, list] = defaultdict(list)
    for r in eng:
        c = float(r["confidence"])
        b = min(n_bins - 1, max(0, int(c * n_bins)))
        bins[b].append((c, 1.0 if r["correct"] else 0.0))
    ece = 0.0
    for _b, vals in bins.items():
        conf_b = sum(v[0] for v in vals) / len(vals)
        acc_b = sum(v[1] for v in vals) / len(vals)
        ece += (len(vals) / len(eng)) * abs(acc_b - conf_b)
    brier = sum(
        (float(r["confidence"]) - (1.0 if r["correct"] else 0.0)) ** 2
        for r in eng
    ) / len(eng)
    return round(ece, 4), round(brier, 4)


def _auroc(rows: list[dict]):
    """Error-detection AUROC: does CONFIDENCE RANK correct above incorrect?

    WHY THIS BELONGS ON THE REPORT LINE (oracle-addendum 25.4). Precision@threshold
    and ECE both describe the OPERATING POINT; neither says whether confidence
    carries any error signal at all. That distinction is load-bearing here,
    because the JEV cascade (arXiv 2609.26550) is built on exactly that
    assumption: it ACCEPTS when the engine is confident and ESCALATES when it is
    not, so the whole saving depends on confidence ranking errors. The paper
    measured a case where it does not - on style-adversarial pairs about a third
    of items scoring in [0.9, 0.95) were still wrong, with error-detection AUROC
    falling to 0.77. A consumer can therefore show healthy precision at its
    threshold and still have a confidence signal that ranks nothing.

    Rank-based (Mann-Whitney U) with mid-ranks for ties, so no dependency is
    added. Returns None when either class is empty - an undefined AUC must not be
    fabricated as 0.5.
    """
    eng = [r for r in rows if r.get("confidence") is not None]
    pos = [float(r["confidence"]) for r in eng if r.get("correct")]
    neg = [float(r["confidence"]) for r in eng if not r.get("correct")]
    if not pos or not neg:
        return None
    neg.sort()
    total = 0.0
    for c in pos:
        lo = bisect_left(neg, c)
        eq = bisect_right(neg, c) - lo
        total += lo + 0.5 * eq
    return round(total / (len(pos) * len(neg)), 4)


def coverage_accuracy_curve(rows: list[dict], thresholds=None) -> list[dict]:
    """AC22.2 (BT-DEI-14): the coverage/accuracy-above-threshold curve.

    For each candidate threshold t: coverage = P(conf >= t) and
    accuracy_above = P(correct | conf >= t). The operating point is
    re-derivable from this curve rather than hard-coded (D13) — this is the
    instrument that derived 0.40 for the GLiNER backend.
    """
    if thresholds is None:
        thresholds = [x / 100 for x in range(5, 100, 5)]
    eng = [r for r in rows if r.get("confidence") is not None]
    curve = []
    for t in thresholds:
        kept = [r for r in eng if r["confidence"] >= t]
        cov = len(kept) / len(eng) if eng else None
        acc = (
            sum(1 for r in kept if r["correct"]) / len(kept) if kept else None
        )
        curve.append({
            "threshold": round(t, 2),
            "coverage": round(cov, 4) if cov is not None else None,
            "accuracy_above": round(acc, 4) if acc is not None else None,
            "n_above": len(kept),
        })
    return curve


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/memory.db")
    ap.add_argument("--since", default=None,
                    help="ISO date lower bound, e.g. 2026-09-20")
    ap.add_argument("--json", action="store_true", help="machine output")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.is_file():
        print(f"UNVERIFIED: db not found: {db}")
        return 4
    try:
        rows = _load_decisions(str(db), args.since)
    except sqlite3.Error as e:  # encrypted DBs surface here (SQLCipher)
        print(f"UNVERIFIED: cannot read ledger ({e})")
        return 4

    out: dict = {"n_rows": len(rows), "refuse_below": REFUSE_BELOW}
    # group by consumer x engine model (AC6.1 edge)
    by_model = defaultdict(list)
    for r in rows:
        by_model[(r.get("consumer_id"), r.get("engine"))].append(r)

    out["groups"] = {}
    for (consumer, engine), grp in sorted(
        by_model.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))
    ):
        lats = [r["latency_ms"] for r in grp if r["latency_ms"] is not None]
        escal = [r for r in grp if r["escalated"]]
        t, n = recommend_threshold(grp)
        ece, brier = _ece_brier(grp)
        out["groups"][f"{consumer}::{engine}"] = {
            "n": len(grp),
            "buckets": _buckets(grp),
            "recommended_threshold": t,
            "recommendation_n": n,
            "ece": ece,
            "brier": brier,
            "coverage_accuracy_curve": coverage_accuracy_curve(grp),
            # AC9.2: pooled accuracy hides a class-blind classifier.
            "per_class_accuracy": per_class_accuracy(grp),
            "latency_p50_ms": _pct(lats, 0.50),
            "latency_p95_ms": _pct(lats, 0.95),
            "escalation_rate": round(len(escal) / len(grp), 3) if grp else None,
            "big_model_calls_avoided": round(1 - len(escal) / len(grp), 3)
            if grp
            else None,
        }

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"decision rows: {out['n_rows']}")
        for name, g in out["groups"].items():
            print(f"\n[{name}] n={g['n']}")
            print(f"  latency p50/p95 ms: {g['latency_p50_ms']} / "
                  f"{g['latency_p95_ms']}")
            print(f"  escalation rate: {g['escalation_rate']}  "
                  f"big-model calls avoided: {g['big_model_calls_avoided']}")
            print(f"  recommended threshold: {g['recommended_threshold']} "
                  f"(n={g['recommendation_n']})")
            print(f"  ECE: {g['ece']}  Brier: {g['brier']}  (AC18.1)")
            pca = g.get("per_class_accuracy") or {}
            if pca:
                print("  per-class accuracy (AC9.2 — web intent classes):")
                for cls, v in pca.items():
                    print(f"    {cls}: n={v['n']} acc={v['accuracy']}")
            for b, (n, acc) in g["buckets"].items():
                print(f"    conf {b}: n={n} acc={acc}")
            curve = g.get("coverage_accuracy_curve") or []
            if curve:
                print("  coverage/accuracy-above-threshold curve (AC22.2):")
                for pt in curve:
                    acc_s = (f"{pt['accuracy_above']:.3f}"
                             if pt["accuracy_above"] is not None else "n/a")
                    print(f"    t={pt['threshold']:.2f}: cov={pt['coverage']} "
                          f"acc>={acc_s} n={pt['n_above']}")
    if not rows or all(
        g["recommendation_n"] < REFUSE_BELOW for g in out["groups"].values()
    ):
        if rows:
            print(f"\nINSUFFICIENT DATA (< {REFUSE_BELOW}); thresholds stay "
                  "provisional (UNVERIFIED).")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())


# ── REQ-31 AC31.1/AC31.2 (T50): the deployed-configuration CONFIRMATION ────


def _default_cfg():
    try:
        from backend.agent.decision_engine import get_decision_engine

        return getattr(get_decision_engine(), "_cfg", None)
    except Exception:  # noqa: BLE001 — an unavailable engine is not fatal here
        return None


def deployed_config_report(cfg=None) -> dict:
    """AC31.1: CONFIRM the recorded operating point against the DEPLOYED
    backend, cap and variant.

    A match is a CONFIRMATION and is reported as one — never silently assumed.
    A difference marks the thresholds STALE, which refuses enforcement
    entirely (AC31.4).
    """
    from backend.agent.decision_engine import EngineConfig

    cfg = cfg if cfg is not None else (_default_cfg() or EngineConfig())
    # `threshold_stale` is a METHOD on EngineConfig (not a property) — reading
    # it with plain getattr returns a bound method, which is always truthy and
    # would report every configuration as stale. Handle both shapes.
    _stale_attr = getattr(cfg, "threshold_stale", None)
    stale = bool(_stale_attr() if callable(_stale_attr) else _stale_attr)
    return {
        "candidate_cap": getattr(cfg, "candidate_cap", None),
        "calibrated_cap": getattr(cfg, "calibrated_cap", None),
        "backend_id": getattr(cfg, "backend_id", None),
        "threshold": (
            cfg.threshold_for("tool_choice")
            if hasattr(cfg, "threshold_for") else None
        ),
        "stale": stale,
        "confirms": not stale,
    }


def calibration_report(rows: list, cfg=None) -> dict:
    """AC31.1/AC31.2: precision, ECE and Brier AT the deployed configuration,
    with the confirmation of that configuration alongside them.

    Reports INSUFFICIENT_DATA below the row floor rather than a verdict
    (AC18.5) — never a calibration claim from too few rows.
    """
    cfg = cfg if cfg is not None else _default_cfg()
    thr = None
    if cfg is not None and hasattr(cfg, "threshold_for"):
        thr = cfg.threshold_for("tool_choice")
    above = [
        r for r in rows
        if r.get("confidence") is not None and thr is not None
        and float(r["confidence"]) >= thr
    ]
    precision = (
        round(sum(1 for r in above if r["correct"]) / len(above), 4)
        if above else None
    )
    ece, brier = _ece_brier(rows)
    return {
        "rows": len(rows),
        "threshold": thr,
        "above_threshold": len(above),
        "precision": precision,
        "ece": ece,
        "brier": brier,
        "verdict": (
            "INSUFFICIENT_DATA" if len(rows) < REFUSE_BELOW else "MEASURED"
        ),
        "deployed": deployed_config_report(cfg),
    }
