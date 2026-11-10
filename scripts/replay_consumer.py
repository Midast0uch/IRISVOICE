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
import contextlib
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
# The control labels: the engine's "do not act" answers. The bar's rule
# (calibrate_decision_threshold.py) counts a control-label row as skipped,
# never as wrong.
CONTROL_LABELS = ("NONE", "DELEGATE")


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


def bool_reference(d: dict):
    """The label of a yes/no row by THE BAR's rule (decision_label): the
    outside label first, else the incumbent's answer (brain_bool).

    Before 2026-11-09 the replay read brain_bool only. For needs_action that
    is the incumbent's constant True (1233 of 1233 replayable v7 rows), so an
    acting "no" could never score right, and rows labelled ONLY by an outside
    label were dropped."""
    if d.get("outside_label") is not None:
        return bool(d["outside_label"])
    if d.get("brain_bool") is not None:
        return bool(d["brain_bool"])
    return None


def load_rows(consumer: str, limit: int, stamps=None, engine: str = SOURCE_ENGINE):
    """The recorded questions of one consumer (the newest first)."""
    c = open_store_read_only(app_store_path())
    rows, seen = [], set()
    from scripts.consumer_enforcement_report import fold_group

    for ts, p, sid in c.execute(
            "SELECT created_at, interaction_payload, session_id FROM system_events "
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
        mode = "choice"
        if not state:
            continue
        if not menu or ref not in menu:
            # BOOL consumers (2026-11-04): depth_met, done, needs_action,
            # escalate_incomplete and tool_approval answer a yes/no question, so
            # there is no candidate menu. The question is `state` (now recorded
            # by every writer). Without this branch the replay skipped all five,
            # which are exactly the ones the bar fails on AUROC.
            ref = bool_reference(d)
            if ref is None:
                continue
            ref = bool(ref)
            menu = None
            mode = "bool"
        key = (json.dumps(state, sort_keys=True, default=str)
               if isinstance(state, dict) else state, tuple(menu or ()), ref)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"state": state, "menu": menu, "ref": ref, "mode": mode,
                     "stamp": d.get("criteria_version"), "ts": ts,
                     "confidence": d.get("confidence"), "chosen": d.get("chosen"),
                     "outside_label": d.get("outside_label"),
                     # the bar's fold group and trivial-rule key (2026-11-10):
                     # without them the replay verdict skipped grouped folds
                     # and clause 3b, so it read more optimistic than the bar
                     "group": fold_group(sid),
                     "rule_key": (str(state.get("proposed_tool") or "")
                                  if isinstance(state, dict) else "")})
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
    # 2026-11-09: the yes/no consumers ask a question too. Without it every
    # replay of them asked the backend's DEFAULT question, not the live one.
    if consumer == "tool_approval":
        from backend.agent.tool_approval_shadow import TOOL_APPROVAL_INSTRUCTION

        return TOOL_APPROVAL_INSTRUCTION
    from backend.agent.surface_shadow import SURFACE_CONSUMERS

    return SURFACE_CONSUMERS.get(consumer, "")


@contextlib.contextmanager
def bool_criteria(consumer: str, variant: str, live: dict, custom: dict):
    """The yes/no criteria block for one variant, for the length of a run.

    The d1 backend reads a yes/no consumer's criteria from its declaration
    (decision_backend_d1.declared_criteria), never from the frame, so before
    2026-11-09 `--variants` and `--options` changed NOTHING for these
    consumers: every variant asked the live criteria. current = the
    declaration; bare = no criteria block; custom = the declaration overlaid
    with --options (keys "true"/"false"). Restored on exit."""
    import backend.agent.decision_backend_d1 as d1mod

    orig = d1mod.declared_criteria
    if variant == "bare":
        crit = None
    elif variant == "custom":
        crit = {**(live or {}), **(custom or {})}
    else:
        crit = live
    d1mod.declared_criteria = lambda cid: crit if cid == consumer else orig(cid)
    try:
        yield
    finally:
        d1mod.declared_criteria = orig


def trim_state(text: str, mode: str) -> str:
    """Shorten the recorded frame text, so a frame variant can be measured.

    MEASURED 2026-11-04: the tool_choice's recorded state carries the
    step_facts and the last_result, and on the calibration tasks those two
    lines are long file lists. The question the model reads is then mostly
    file names. "trim" drops both lines, "trim2" keeps a short head of each.
    """
    if not mode or mode == "live":
        return text
    out = []
    for line in text.split("\n"):
        if line.startswith("step_facts:"):
            if mode == "trim":
                continue
            line = "step_facts: " + line[len("step_facts:"):].split(";")[0]
        elif line.startswith("last_result:"):
            if mode == "trim":
                continue
            line = "last_result: " + line[len("last_result:"):][:120]
        out.append(line)
    return "\n".join(out)


def run(variant: str, consumer: str, rows, backend: D1Backend, live: dict, custom: dict,
        instruction: str = "", raw_frame: bool = False, frame_mode: str = "live"):
    if rows and rows[0].get("mode") == "bool":
        with bool_criteria(consumer, variant, live, custom):
            return _run(variant, consumer, rows, backend, live, custom,
                        instruction, raw_frame, frame_mode)
    return _run(variant, consumer, rows, backend, live, custom,
                instruction, raw_frame, frame_mode)


def _run(variant: str, consumer: str, rows, backend: D1Backend, live: dict, custom: dict,
         instruction: str = "", raw_frame: bool = False, frame_mode: str = "live"):
    # The consumer's OWN job (name, fields, budget) - the live question. The
    # job changes the prompt and the text budget, so a replay with another
    # job measures another question (MEASURED 2026-11-04: review_verdict with
    # the "route" job scored 0.7015 while its live rows score 0.3452).
    from backend.agent.decision_engine import oracle_job

    job = oracle_job(consumer)
    out = []
    same_pick = same_conf = compared = 0
    for r in rows:
        if r.get("mode") == "bool":
            # BOOL consumers (2026-11-04): the live call is
            # `engine.noul(consumer, statement, frame)`, which is
            # `decide(consumer, ["yes","no"], frame or {"goal": statement})`.
            # `state` is the frame when the site passed one, else the
            # statement. Score the SAME frame here so the replay reproduces
            # the live prompt.
            from backend.agent.decision_engine import job_input
            from backend.agent.surface_shadow import register_surface_consumers

            register_surface_consumers()
            st = r["state"]
            # THE ENGINE'S INPUT, not the raw frame (2026-11-09): the live
            # DecisionEngine.decide renders the job's declared fields
            # (job_input) before the backend reads them; the raw dict made the
            # backend read `goal` ONLY - tool_approval lost tool/args/last
            # result (fresh picks matched 817 of 1500 recorded ones; with
            # job_input 1500 of 1500), needs_action lost `expected`.
            frame = job_input(consumer, st if isinstance(st, dict) else {"goal": str(st)})
            ds = backend.decide(consumer, ["yes", "no"], frame,
                                instruction=instruction or None)
            if ds is None:
                continue
            p = 0.0
            for c in (ds.distribution or ()):
                if c.name == "yes":
                    p = float(c.prob)
                    break
            chosen = p >= 0.5
            # FIDELITY: the fresh pick against the recorded one. A replay that
            # does not reproduce the recorded picks measures another question,
            # and none of its variant numbers count (oracle.md 12.3).
            _rec = r.get("chosen")
            if _rec is not None:
                _rec_yes = (_rec is True) or str(_rec).strip().lower() in ("yes", "true")
                same_pick += 1 if chosen == _rec_yes else 0
                compared += 1
            out.append((max(p, 1.0 - p), chosen == bool(r["ref"]),
                        chosen, bool(r["ref"]), _meta(r, probability=p)))
            continue
        st = r["state"]
        if isinstance(st, dict):
            # 2026-11-04: the state is now the EXACT frame the live call
            # passed, so replay hands the dict back unchanged. The backend
            # reads `goal` from a raw mapping, which is what the live call
            # did; re-wrapping it in an OracleState would change the prompt.
            state_text = trim_state(str(st.get("goal") or ""), frame_mode)
            raw = dict(st)
            raw["goal"] = state_text
        else:
            state_text = trim_state(st, frame_mode)
            raw = {"goal": state_text}
        if raw_frame:
            # The live call site passes a RAW frame ({"goal": text}), so the
            # backend reads the text and NEVER the job's budget or fields.
            # MEASURED 2026-11-04: the review_verdict live path does this, and
            # the replay with an OracleState (the job set) reproduces only
            # half of the live picks.
            frame = raw
        else:
            frame = OracleState(job=job.name, fields=tuple(job.fields), text=state_text,
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
        # THE BAR's rule (calibrate_decision_threshold.py, decision_label): a
        # CONTROL-label answer (NONE / DELEGATE) can never match the
        # reference, so such a row is NOT SCOREABLE - it is counted as
        # skipped, never as wrong. MEASURED 2026-11-04: the tool_choice's
        # Oracle picks NONE on 63 of 400 rows, and counting them as wrong
        # depresses every number. The rows are dropped here so the replay
        # measures the same population the report measures.
        if ds.chosen in CONTROL_LABELS:
            continue
        out.append((float(ds.confidence), ok, ds.chosen, r["ref"],
                    _meta(r, reference=(r["ref"] if r.get("outside_label") is None
                                        else None))))
    if compared:
        print(f"   fresh ask vs the recorded row: same pick {same_pick}/{compared}, "
              f"same confidence {same_conf}/{compared}")
    return out


def _meta(r, probability=None, reference=None) -> dict:
    """What the bar's fit needs beside (confidence, correct, chosen): the fold
    group, the trivial-rule key, P(yes) for a yes/no consumer, the reference
    for a parity-labelled choice row, and whether the row is outcome-labelled
    (the fit never blends an outcome curve with a parity curve)."""
    return {"group": r.get("group"), "rule_key": r.get("rule_key"),
            "probability": probability, "reference": reference,
            "outside": r.get("outside_label") is not None}


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
    # PER ANSWER (2026-11-09): the answer that ACTS is what the bar's acting
    # clause judges, and with no threshold the BAR line below prints nothing
    # for it. Count and precision of each answer, and at confidence >= 0.9.
    by = collections.defaultdict(list)
    for x in res:
        by[x[2]].append(x)
    parts = []
    for ans, xs in sorted(by.items(), key=lambda kv: str(kv[0])):
        hi = [x for x in xs if x[0] >= 0.9]
        parts.append(f"{ans}: n={len(xs)} prec={sum(x[1] for x in xs) / len(xs):.3f}"
                     + (f" (conf>=0.9: n={len(hi)} prec={sum(x[1] for x in hi) / len(hi):.3f})"
                        if hi else ""))
    print("   per answer:", " | ".join(parts))
    pos = [x[0] for x in res if x[1]]
    neg = [x[0] for x in res if not x[1]]
    # IN-SAMPLE, not out-of-fold (it was printed as "oof_auroc"): a quick read
    # only. The BAR line below is the verdict that counts.
    if pos and neg:
        wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
        print(f"   in_sample_auroc={wins / (len(pos) * len(neg)):.4f} "
              f"(correct={len(pos)} wrong={len(neg)})")
    else:
        print(f"   in_sample_auroc=untestable (correct={len(pos)} wrong={len(neg)})")


def bar_verdict(consumer: str, res) -> None:
    """The BAR's own verdict on a replayed variant (2026-11-09).

    The replay used to print only an in-sample AUROC and agreement, so a
    variant could look good here and still fail the bar (threshold, precision,
    Wilson bound, rows above, ECE, the acting side). This runs the SAME fit
    (fit_oracle_calibration.fit_consumer, 5-fold out-of-fold) and the SAME
    clause order (consumer_bar.derive_status) as consumer_enforcement_report.py,
    so "passes in replay" means "would pass the bar on this cohort". The
    acting-side numbers are printed for every asymmetric consumer; they gate
    only the consumers in ACTING_ENFORCED, as in the report."""
    if not res:
        return
    try:
        from backend.agent.consumer_bar import ACTING_ANSWER, ACTING_ENFORCED, derive_status
        from scripts.fit_oracle_calibration import fit_consumer
    except Exception as exc:  # noqa: BLE001 - the quick numbers above still stand
        print(f"   BAR: unavailable ({exc!r})")
        return
    rows = []
    for x in res:
        m = x[4] if len(x) > 4 else {}
        rows.append({"confidence": x[0], "correct": bool(x[1]), "chosen": x[2],
                     "group": m.get("group"), "rule_key": m.get("rule_key"),
                     "probability": m.get("probability"),
                     "reference": m.get("reference"),
                     "outside_label": bool(x[1]) if m.get("outside") else None})
    honest = fit_consumer(rows, acting=ACTING_ANSWER.get(consumer), consumer_id=consumer)
    if consumer in ACTING_ENFORCED:
        honest["acting_required"] = True
    oof = honest.get("oof") or {}
    status, gap = derive_status(len(rows), float(oof.get("precision_at_t") or 0.0),
                                oof.get("ece"), honest=honest)

    def _f(v):
        return f"{v:.4f}" if isinstance(v, (int, float)) else str(v)

    print(f"   BAR: status={status} gap={gap or '-'}")
    print(f"        folds={honest.get('folds')} map={honest.get('method')} "
          f"baseline={honest.get('baseline')}")
    print(f"        rows={honest.get('rows_distinct')} classes={honest.get('classes')} "
          f"oof_auroc={_f(oof.get('auroc'))} oof_ece={_f(oof.get('ece'))} "
          f"threshold={_f(honest.get('threshold'))} precision={_f(oof.get('precision_at_t'))} "
          f"wilson={_f(oof.get('wilson_lb'))} rows_above={honest.get('rows_above')}")
    acting = {k: v for k, v in oof.items() if "acting" in k and k != "acting_answer"}
    if acting:
        print(f"        acting({ACTING_ANSWER.get(consumer)}): "
              + " ".join(f"{k}={_f(v)}" for k, v in sorted(acting.items())))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consumer", required=True)
    ap.add_argument("--variants", default="current,bare")
    ap.add_argument("--options", default="", help="JSON map for the custom variant")
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--stamps", default="")
    ap.add_argument("--engine", default=SOURCE_ENGINE)
    ap.add_argument("--instruction", default="live",
                    help="the question: 'live' (default: the consumer's own, as the live "
                         "call asks it), 'none' (no question), a text, or a file path")
    ap.add_argument("--since", default="", help="only rows created at/after this ISO stamp")
    ap.add_argument("--raw-frame", action="store_true",
                    help="ask with the raw frame, like the live call site")
    ap.add_argument("--frame", default="live", choices=["live", "trim", "trim2"],
                    help="the frame variant: live, trim (drop the step_facts and "
                         "the last_result) or trim2 (keep a short head of each)")
    args = ap.parse_args()

    stamps = {s.strip() for s in args.stamps.split(",") if s.strip()} or None
    rows = load_rows(args.consumer, args.limit, stamps, args.engine)
    if args.since:
        rows = [r for r in rows if str(r.get("ts") or "") >= args.since]
    print(f"replayable distinct rows: {len(rows)}")
    if not rows:
        print("  (the rows must carry state + a reference: brain_choice with "
              "candidates, or brain_bool)")
        return 1
    live = declaration_text(args.consumer)
    custom = {}
    if args.options:
        raw = args.options
        if Path(raw).exists():
            raw = Path(raw).read_text(encoding="utf-8")
        custom = json.loads(raw)
    backend = D1Backend()
    instr = (live_instruction(args.consumer) if args.instruction == "live"
             else "" if args.instruction == "none" else args.instruction)
    if instr and Path(instr).exists():
        instr = Path(instr).read_text(encoding="utf-8")
    for variant in [v.strip() for v in args.variants.split(",") if v.strip()]:
        res = run(variant, args.consumer, rows, backend, live, custom, instr,
                  args.raw_frame, args.frame)
        report(variant, res)
        bar_verdict(args.consumer, res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
