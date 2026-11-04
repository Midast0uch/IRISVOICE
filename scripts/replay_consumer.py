#!/usr/bin/env python3
"""Offline replay of ANY Oracle consumer on its RECORDED question (2026-11-04).

The methodology instrument for the consumers that do not meet the bar
(docs/architecture/oracle.md 6.1 rule 3: "fix the question or the label on
the rows already recorded"). A question change is measured here in minutes,
against the recorded states, and never blends into the live cohorts (nothing
is written).

Only the consumers whose rows carry the rendered question can be replayed:
the payload must hold `state` (what d1 read), `candidates` (the menu) and
`brain_choice` (the reference label). MEASURED 2026-11-04: review_verdict
and tool_choice carry them; the noul consumers (done, sufficient, depth_met)
and the binary ones (tool_approval, escalate_incomplete) do not - their
question is not recorded, so their fix must be in the LABEL or the question
must start being recorded.

The variants change the OPTION TEXT (the consumer declaration's wording):
  current  the declaration's text (the live question)
  bare     the option names only
  custom   a JSON map given with --options '{"pass": "...", ...}'

Usage:
    python scripts/replay_consumer.py --consumer review_verdict \
        --engine d1-2b-q4_k_m+systemone --stamps review_verdict/v8 \
        --variants current,bare --limit 300
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for p in (str(_REPO), str(_REPO / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from _app_store import app_store_path  # noqa: E402

from backend.agent.decision_backend_d1 import D1Backend  # noqa: E402
from backend.agent.decision_engine import OracleState  # noqa: E402
from backend.memory.db import open_store_read_only  # noqa: E402

SOURCE_ENGINE = "d1-2b-q4_k_m+systemone"


def declaration_text(consumer: str) -> dict:
    """The live option text of a consumer (the declaration's wording).

    MEASURED 2026-11-04: this read `decl.options`, which does not exist, so
    the lookup raised and the "current" variant silently fell back to the
    BARE NAMES - the variant that measures 0.8488 while the live question
    (the descriptions) measures 0.4642. The declaration's field is
    `criteria`.
    """
    try:
        from backend.agent.decision_engine import CONSUMER_DECLARATIONS

        decl = CONSUMER_DECLARATIONS.get(consumer)
        if decl is None:
            return {}
        return dict(decl.criteria)
    except Exception:
        return {}


def load_rows(consumer: str, limit: int, stamps=None, engine: str = SOURCE_ENGINE):
    """The recorded questions of one consumer (the newest first)."""
    c = open_store_read_only(app_store_path())
    rows, seen = [], set()
    for ts, p in c.execute(
            "SELECT created_at, interaction_payload FROM system_events "
            "WHERE event_type='tool_execution' ORDER BY rowid DESC"):
        try:
            d = json.loads(p or "{}").get("decision")
        except Exception:
            continue
        if not isinstance(d, dict) or d.get("consumer_id") != consumer:
            continue
        if engine and d.get("engine") and str(d["engine"]) != engine:
            continue
        if stamps and d.get("criteria_version") not in stamps:
            continue
        state = d.get("state")
        menu = [x["name"] for x in (d.get("candidates") or []) if isinstance(x, dict)]
        ref = d.get("brain_choice")
        if not state or not menu or ref not in menu:
            continue
        key = (state, tuple(menu), ref)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"state": state, "menu": menu, "ref": ref,
                     "stamp": d.get("criteria_version"), "ts": ts,
                     "confidence": d.get("confidence"), "chosen": d.get("chosen"),
                     "outside_label": d.get("outside_label")})
    # SPREAD the sample over the whole cohort, newest first. MEASURED
    # 2026-11-04: taking the newest N rows sampled only the test-running
    # steps (AUROC 0.8448) and hid the read/add steps, where the Oracle
    # over-refines and the ranking is INVERTED (AUROC 0.0142..0.3466).
    if limit and len(rows) > limit:
        step = len(rows) / float(limit)
        rows = [rows[int(i * step)] for i in range(limit)]
    return rows


def option_text(variant: str, name: str, live: dict, custom: dict) -> str:
    if variant == "current":
        return live.get(name, name)
    if variant == "bare":
        return name
    if variant == "custom":
        return custom.get(name, live.get(name, name))
    return live.get(name, name)


def live_instruction(consumer: str) -> str:
    """The consumer's LIVE criteria text (the instruction the live path
    registers). MEASURED 2026-11-04: the replay without it asks a DIFFERENT
    question - the D1Backend registers the default spec when the instruction
    is missing."""
    if consumer == "review_verdict":
        from backend.agent.der_loop import Reviewer

        return Reviewer.REVIEW_INSTRUCTION
    return ""


def run(variant: str, consumer: str, rows, backend: D1Backend, live: dict, custom: dict,
        instruction: str = "", raw_frame: bool = False):
    # The consumer's OWN job (name, fields, budget) - the live question. The
    # job changes the prompt and the text budget, so a replay with another
    # job measures another question (MEASURED 2026-11-04: review_verdict with
    # the "route" job scored 0.7015 while its live rows score 0.3452).
    from backend.agent.decision_engine import oracle_job

    job = oracle_job(consumer)
    out = []
    same_pick = same_conf = compared = 0
    for r in rows:
        if raw_frame:
            # The live call site passes a RAW frame ({"goal": text}), so the
            # backend reads the text and NEVER the job's budget or fields.
            # MEASURED 2026-11-04: the review_verdict live path does this, and
            # the replay with an OracleState (the job set) reproduces only
            # half of the live picks.
            frame = {"goal": r["state"]}
        else:
            frame = OracleState(job=job.name, fields=tuple(job.fields), text=r["state"],
                                budget_ids=job.budget_ids,
                                option_criteria=tuple(
                                    (n, option_text(variant, n, live, custom)) for n in r["menu"]))
        ds = backend.decide(consumer, r["menu"], frame, instruction=instruction or None)
        if ds is None:
            continue
        if r.get("confidence") is not None:
            same_pick += 1 if ds.chosen == r.get("chosen") else 0
            same_conf += 1 if abs(float(ds.confidence) - float(r["confidence"])) < 1e-6 else 0
            compared += 1
        # The BAR's label for review_verdict is the OUTCOME (the ground
        # truth), not the Brain's verdict: VERIFIED -> pass was right,
        # FAILED -> refine or veto was right (oracle.md 7.4, the v8 reading
        # B). The row carries the ground truth's verdict on the RECORDED
        # pick (outside_label), and the map is binary, so a different pick
        # flips it.
        if r.get("outside_label") is not None:
            ok = (bool(r["outside_label"]) if ds.chosen == r.get("chosen")
                  else not bool(r["outside_label"]))
        else:
            ok = ds.chosen == r["ref"]
        out.append((float(ds.confidence), ok, ds.chosen, r["ref"]))
    if compared:
        print(f"   fresh ask vs the recorded row: same pick {same_pick}/{compared}, "
              f"same confidence {same_conf}/{compared}")
    return out


def report(variant: str, res):
    n = len(res)
    if not n:
        print(f"{variant}: no rows scored")
        return
    agree = sum(x[1] for x in res) / n
    print(f"\n== {variant}: n={n} agree={agree:.3f}")
    for lo, hi in ((0, .6), (.6, .8), (.8, .9), (.9, .95), (.95, 1.01)):
        b = [x for x in res if lo <= x[0] < hi]
        if b:
            print(f"   conf[{lo:.2f},{hi:.2f}) n={len(b):4d} agree={sum(x[1] for x in b) / len(b):.3f}")
    wrong = collections.Counter((x[2], x[3]) for x in res if not x[1])
    print("   top disagreements (chosen, reference):", wrong.most_common(6))
    pos = [x[0] for x in res if x[1]]
    neg = [x[0] for x in res if not x[1]]
    if pos and neg:
        wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
        print(f"   oof_auroc={wins / (len(pos) * len(neg)):.4f} "
              f"(correct={len(pos)} wrong={len(neg)})")
    else:
        print(f"   oof_auroc=untestable (correct={len(pos)} wrong={len(neg)})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consumer", required=True)
    ap.add_argument("--variants", default="current,bare")
    ap.add_argument("--options", default="", help="JSON map for the custom variant")
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--stamps", default="")
    ap.add_argument("--engine", default=SOURCE_ENGINE)
    ap.add_argument("--instruction", default="", help="the live criteria text, or 'live' for the consumer's own")
    ap.add_argument("--since", default="", help="only rows created at/after this ISO stamp")
    ap.add_argument("--raw-frame", action="store_true",
                    help="ask with the raw frame, like the live call site")
    args = ap.parse_args()

    stamps = {s.strip() for s in args.stamps.split(",") if s.strip()} or None
    rows = load_rows(args.consumer, args.limit, stamps, args.engine)
    if args.since:
        rows = [r for r in rows if str(r.get("ts") or "") >= args.since]
    print(f"replayable distinct rows: {len(rows)}")
    if not rows:
        print("  (the rows must carry state + candidates + brain_choice)")
        return 1
    live = declaration_text(args.consumer)
    custom = {}
    if args.options:
        raw = args.options
        if Path(raw).exists():
            raw = Path(raw).read_text(encoding="utf-8")
        custom = json.loads(raw)
    backend = D1Backend()
    instr = live_instruction(args.consumer) if args.instruction == "live" else args.instruction
    if instr and Path(instr).exists():
        instr = Path(instr).read_text(encoding="utf-8")
    for variant in [v.strip() for v in args.variants.split(",") if v.strip()]:
        report(variant, run(variant, args.consumer, rows, backend, live, custom, instr,
                            args.raw_frame))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
