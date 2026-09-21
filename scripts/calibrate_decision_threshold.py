#!/usr/bin/env python3
"""Calibration for the decision engine (specs/tool-decision-engine REQ-6/REQ-10).

Reads `system_events` from data/memory.db (READ-ONLY URI — D13), extracts rows
whose payload carries a `decision` block, and reports:

  * reliability table: confidence bucket -> observed accuracy (per consumer,
    per engine model id)
  * recommended threshold maximizing auto-executed fraction s.t. accuracy>=0.90
    (refuses under N=50 engine-routed decisions, AC6.2)
  * per-route decision latency p50/p95 and escalation rate (AC10.2)
  * big-model calls avoided = 1 - escalation rate (engine-routed rows)

Never writes. Never hits the network. Exit 0 = report produced; exit 3 =
insufficient data; exit 4 = DB encrypted/unreadable (reports UNVERIFIED).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
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
        out["groups"][f"{consumer}::{engine}"] = {
            "n": len(grp),
            "buckets": _buckets(grp),
            "recommended_threshold": t,
            "recommendation_n": n,
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
            for b, (n, acc) in g["buckets"].items():
                print(f"    conf {b}: n={n} acc={acc}")
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
