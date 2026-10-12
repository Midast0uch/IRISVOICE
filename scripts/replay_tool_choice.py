#!/usr/bin/env python3
"""Offline replay of the Oracle's tool decision on RECORDED states (2026-10-11).

Every tool_choice row since the replay keys carries `state` (exactly what d1
read), the offered menu (`candidates`), the incumbent's tool (`brain_choice`)
and whether that call worked (`brain_ok`). This re-asks d1 the SAME question on
the SAME states under a question/option VARIANT and measures agreement and the
confidence bands - so a question-design change is tested in minutes, not with a
full eval group, and never blends into the live cohorts (nothing is written).

Needs the d1 llama-server on :8082 (the backend boots it). Read-only on the store.

Usage:
    python scripts/replay_tool_choice.py [--variants descriptions,hints] [--stamps tc-frame-v8] [--limit N]
"""

from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for p in (str(_REPO), str(_REPO / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from _app_store import app_store_path  # noqa: E402

from backend.agent.decision_backend_d1 import D1Backend  # noqa: E402
from backend.agent.decision_engine import OracleState  # noqa: E402
from backend.agent.tool_registry import oracle_hint, resolve_tool  # noqa: E402

ENGINE = "d1-3b-ad-q4_k_m+letters"
CONTROL = {"DELEGATE", "NONE"}


def load_rows(limit: int, stamps=None):
    c = sqlite3.connect(f"file:{app_store_path()}?mode=ro", uri=True)
    rows, seen = [], set()
    for (p,) in c.execute(
            "SELECT interaction_payload FROM system_events WHERE event_type='tool_execution' "
            "ORDER BY rowid DESC"):
        try:
            d = json.loads(p or "{}").get("decision")
        except Exception:
            continue
        if not isinstance(d, dict) or d.get("consumer_id") != "tool_choice":
            continue
        if d.get("engine") != ENGINE or not d.get("state") or not d.get("brain_choice"):
            continue
        if stamps and d.get("criteria_version") not in stamps:
            continue
        # only calls that WORKED are a target worth matching (brain_ok False
        # = the model's own call failed; None = an older row, kept)
        if d.get("brain_ok") is False:
            continue
        menu = [x["name"] for x in d.get("candidates") or []]
        if d["brain_choice"] not in menu:
            continue
        key = (d["state"], d["brain_choice"])
        if key in seen:
            continue
        seen.add(key)
        rows.append({"state": d["state"], "menu": menu, "ref": d["brain_choice"],
                     "ok": d.get("brain_ok"), "live_chosen": d.get("chosen")})
        if len(rows) >= limit:
            break
    return rows


def option_text(variant: str, name: str) -> str:
    """`hints` = the live decision lines (tool_registry.ORACLE_HINTS);
    `descriptions` = the tools' LLM-facing descriptions (the pre-hints text).
    To test a new line, edit ORACLE_HINTS and replay `hints` - one source."""
    spec = resolve_tool(name)
    desc = getattr(spec, "description", "") if spec else ""
    if variant == "hints":
        return oracle_hint(name, desc)
    return desc or name


def run(variant: str, rows, backend: D1Backend):
    out = []
    for r in rows:
        state = OracleState(job="route", fields=(), text=r["state"], budget_ids=384,
                            option_criteria=tuple((n, option_text(variant, n)) for n in r["menu"]))
        ds = backend.decide("tool_choice", r["menu"], state)
        if ds is None:
            continue
        out.append((float(ds.confidence), ds.chosen == r["ref"] and ds.chosen not in CONTROL,
                    r["ok"], ds.chosen, r["ref"]))
    return out


def report(variant: str, res):
    n = len(res)
    if not n:
        print(f"{variant}: no rows scored")
        return
    agree = sum(x[1] for x in res) / n
    ok_rows = [x for x in res if x[2] is True]
    agree_ok = sum(x[1] for x in ok_rows) / len(ok_rows) if ok_rows else float("nan")
    print(f"\n== {variant}: n={n} agree={agree:.3f} agree_on_successful_calls={agree_ok:.3f} (n={len(ok_rows)})")
    for lo, hi in ((0, .6), (.6, .8), (.8, .9), (.9, .95), (.95, 1.01)):
        b = [x for x in res if lo <= x[0] < hi]
        if b:
            print(f"   conf[{lo:.2f},{hi:.2f}) n={len(b):4d} agree={sum(x[1] for x in b) / len(b):.3f}")
    wrong = collections.Counter((x[3], x[4]) for x in res if not x[1])
    print("   top disagreements (chosen, reference):", wrong.most_common(6))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default="descriptions,hints")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--stamps", default="", help="comma list of criteria_version to replay")
    args = ap.parse_args()
    rows = load_rows(args.limit, {s for s in args.stamps.split(",") if s} or None)
    print(f"replayable distinct rows: {len(rows)}")
    backend = D1Backend()
    if not backend.load():
        print("d1 is not served on :8082 - start the backend first")
        return 2
    for v in args.variants.split(","):
        report(v, run(v.strip(), rows, backend))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
