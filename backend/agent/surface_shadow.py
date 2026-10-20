"""Remaining decision-surface consumers — shadow-first (REQ-29, T46–T49).

Choice-shaped Brain decisions that the §8.4 wiring survey missed. Each is a
BOOLEAN question the common case answers negatively, and each currently costs a
Brain call or a keyword list:

  ``escalate_incomplete`` the incomplete-result keyword list that escalates
  ``needs_action``        the heuristics that gate the engine's OWN NONE commit

FOUNDATION SCOPE (AC29.1–AC29.4): every site is UNCHANGED. The engine is scored
in shadow and its row recorded, so the parity data a Wave 7/TG-13 flip needs
can accumulate. Nothing here is enforced by default.

Stage B (2026-10-05): a site passes the chokepoint's answer -
``enforced=decides(cid) is not None`` and ``acts=`` (``oracle_acts`` on the
confidence in the chosen answer) - and, when it does not decide, ``defer=True``
so the score runs on the ``oracle_shadow`` lane, never on the reply path.
(``has_gaps`` was removed the same day: its only producer, trailing_director.py,
was deleted 2026-08-06, so it had no live site.)

Three invariants this module exists to hold:
  * THE ENGINE NEVER WRITES PROSE. The Brain still writes any text a positive
    verdict calls for (AC29.1).
  * SAFETY IS NOT NEGOTIABLE. `escalate_incomplete` still passes through the
    existing budget and veto-cap checks, which the engine may never permit
    (AC29.3). `needs_action` keeps its documented SAFE direction — when in
    doubt, ACT (AC29.4).
  * ENGINE UNAVAILABLE → today's behaviour, byte-identical, at all four sites
    (AC29.7).

NON-FIT (AC29.5): `semantic_gate.tier0_classify` is deliberately NOT scored.
Its deterministic branch is pure, no-I/O, resolves most traffic at <1ms, and
replacing it with a ~150ms model would be a REGRESSION. See REQ-29's
Non-Requirements so it is not re-proposed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger("surface_shadow")


def input_key(consumer_id: str, statement: str,
              frame: Optional[dict] = None) -> str:
    """A stable identity for the INPUT a row was scored on (2026-10-20).

    The ledger's dedupe key is (consumer, engine, confidence, chosen,
    reference, correct) and confidence jitters on every rescore, so the same
    goal rescored counted as NEW evidence (measured: needs_action 226
    "distinct" rows, 17 collapsed, after two passes over one 101-task set).
    This key pins the row to what was ASKED, not to how confidently it was
    answered. The report prefers it when present; rows without it keep the
    legacy key.
    """
    payload = json.dumps(
        {"c": consumer_id, "s": statement, "f": frame or None},
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]

SURFACE_CONSUMERS: Dict[str, str] = {
    "escalate_incomplete": (
        "Is this step result too incomplete to proceed without more work?"
    ),
    "needs_action": (
        # v4 (2026-10-19, measured on 294 REAL goal+outcome pairs). Two
        # defects in v3, both reproduced before the change:
        #
        # 1. THE WORD "writing" SAT ON BOTH SIDES. v3's NO side ended "by
        #    writing an answer from what is already available", so d1 read
        #    "Write the slugify function to textutils.py" as an ANSWER
        #    (p=0.11 for a tool) - and it misread Update/Edit/Add goals the
        #    same way at 0.17-0.45. Those are 8 of the 9 wrong "no" answers
        #    on tool-needing steps, i.e. the whole precision ceiling.
        # 2. THE FRAME CARRIED ONLY THE GOAL. A goal that names an action
        #    ("Write the slugify function to textutils.py") is still
        #    ambiguous alone; the step's EXPECTED OUTPUT makes the artifact
        #    explicit. With it, the same 4 hard write/edit goals moved from
        #    "no" (0.97-0.99) to "yes" (0.77-0.86).
        #
        # v5 (2026-10-19) - measured on 11 REAL production (goal, expected)
        # pairs where the planner now fills expected_output, plus the 11-case
        # hard probe. v4 said "no" to a READ goal (0.82) and an EDIT goal
        # (0.65): the model judged the WORDING of the goal, not the action it
        # must perform. The added clause ("Decide about the action the step
        # must perform, not about the wording of the goal") fixes both:
        # live 11/11, hard 10/11 (one miss: "Add the balance_on(date) method"
        # at 0.64, an API addition with no file named - genuinely ambiguous).
        # A variant that also names a file/a command scores 10/11 and 10/11:
        # the nouns pull analysis steps ("Analyze the test output...") to yes
        # at 0.53. Hence the verbs.
        "Does this step take an ACTION in the project - read, write, edit, "
        "run, search or browse - or does it only give an ANSWER from what "
        "is already known? Decide about the action the step must perform, "
        "not about the wording of the goal."
    ),
    # Session 364 (owner request). The DEPTH question, anchored to the task's
    # success criteria: `sufficient`/`done` ask whether the objective is
    # COVERED, this asks whether it is done to the DEPTH the criteria require.
    # Site: the run-grade chokepoint (AgentKernel._der_finalize_step's grade
    # block), where the required facts, what is still open, the coverage and the
    # loop's own verdict are all in hand. brain_bool is that verdict, so the
    # parity metric answers "how often does the loop call a task complete when
    # the depth bar was not actually met?".
    "depth_met": (
        "Is this actually done to the depth its success criteria require, "
        "rather than only superficially complete?"
    ),
}

_TRUE_LABEL = "yes"
_FALSE_LABEL = "no"

# Sentinel: adopt the module-level engine singleton. `engine=None` means NO
# ENGINE (fail-safe) — never "resolve the singleton", or a shadow scorer would
# silently load the model the first time it is called.
AUTO_ENGINE = object()

# Process-wide row sink. The four surface sites have no bridge of their own, so
# this is how their rows reach a ledger (the kernel installs it) — and how a
# test observes them. None = log only, never silently dropped.
_ROW_SINK: Optional[Callable[[dict], None]] = None


def set_row_sink(sink: Optional[Callable[[dict], None]]) -> None:
    """Install (or clear) the process-wide row sink. Test seam / ledger wiring."""
    global _ROW_SINK
    _ROW_SINK = sink


def emit_row(row: Optional[dict]) -> None:
    """Hand a shadow row to the installed sink, else log it. Never raises."""
    if not row:
        return
    sink = _ROW_SINK
    if callable(sink):
        try:
            sink(row)
            return
        except Exception as e:  # noqa: BLE001 — an observer never blocks
            logger.debug("[surface] row sink failed: %r", e)
    logger.info(
        "[surface] shadow row consumer=%s chosen=%s conf=%s brain=%s",
        row.get("consumer_id"), row.get("chosen"), row.get("confidence"),
        row.get("brain_bool"),
    )


def register_surface_consumers() -> int:
    """Register the surface consumers' criteria (REQ-19 AC19.1). Idempotent.

    A consumer with no criteria is REFUSED by the engine rather than scored
    under another consumer's head, so this must run before any shadow scoring.

    REQ-4: the DECLARED type and criteria come from the declaration table
    (`register_declared`), never from this site. `needs_upgrade` replaces a
    spec that predates REQ-4 (AC13.4) - the old ``is None`` check would have let
    a warm registry keep its pre-REQ-4 shape forever.
    """
    try:
        from backend.agent.decision_engine import (
            get_consumer_spec,
            needs_upgrade,
            register_declared,
        )
    except Exception as e:  # noqa: BLE001 — criteria are best-effort
        logger.warning("[surface] consumer specs unavailable: %s", e)
        return 0
    added = 0
    for cid, instruction in SURFACE_CONSUMERS.items():
        if not needs_upgrade(get_consumer_spec(cid)):
            continue
        register_declared(cid, instruction, (_TRUE_LABEL, _FALSE_LABEL))
        added += 1
    return added


def _default_engine():
    try:
        from backend.agent.decision_engine import get_decision_engine
        return get_decision_engine()
    except Exception:  # noqa: BLE001
        return None


def score_surface_bool(
    consumer_id: str,
    statement: str,
    *,
    engine: Any = None,
    frame: Optional[dict] = None,
) -> Optional[Any]:
    """The consumer's Noul for *statement*, or None. Never raises."""
    try:
        register_surface_consumers()
        eng = _default_engine() if engine is AUTO_ENGINE else engine
        if eng is None:
            return None
        scorer = getattr(eng, "noul", None)
        if not callable(scorer):
            return None
        return scorer(
            consumer_id, statement, frame or {"goal": statement},
            true_label=_TRUE_LABEL, false_label=_FALSE_LABEL,
        )
    except Exception as e:  # noqa: BLE001 — a shadow never raises
        logger.debug("[surface] %s shadow failed: %r", consumer_id, e)
        return None


def _scope_now() -> Dict[str, str]:
    """REQ-6 AC6.3a: the row's scope (turn/step/node ids), bound AS VALUES at
    submit time - the shadow lane's own thread context would say nothing."""
    try:
        from backend.agent.decision_engine import scope_now

        return scope_now()
    except Exception:  # noqa: BLE001 - scope is best-effort, never fatal
        return {}


def shadow_row(
    consumer_id: str,
    noul: Optional[Any],
    brain_bool: Optional[bool],
    scope: Optional[Dict[str, str]] = None,
    input_key: Optional[str] = None,
) -> Optional[dict]:
    """The CT-DEI-6-shaped row for a surface judgment, or None.

    No Noul → no row: a missing engine must never fabricate a shadow row.
    ``brain_bool`` is what the legacy decider ACTUALLY returned, so the row is
    a shadow PAIR and the parity metric exists.
    """
    if noul is None:
        return None
    p = float(noul.probability)
    row = {
        "consumer_id": consumer_id,
        "chosen": bool(noul.true(0.5)),
        # Confidence in the CHOSEN answer, raw P(true) beside it (see
        # monitor_shadow.shadow_row: P(true) read as confidence inverts a "no").
        "confidence": round(max(p, 1.0 - p), 4),
        "probability": round(p, 4),
        "engine_latency_ms": noul.engine_latency_ms,
        "brain_bool": brain_bool,
        "shadow": True,
    }
    if input_key:
        row["input_key"] = input_key
    if scope:
        row.update(scope)
    return row


def surface_bool(
    consumer_id: str,
    statement: str,
    *,
    brain_bool_fn: Callable[[], bool],
    engine: Any = None,
    enforced: bool = False,
    threshold: float = 0.8,
    frame: Optional[dict] = None,
    defer: bool = False,
    criteria_version: Optional[str] = None,
    acts: Optional[Callable[[float], bool]] = None,
) -> Tuple[bool, Optional[dict]]:
    """One surface judgment: ``(value, shadow_row)``.

    SHADOW (``enforced=False``, the default and the only shipped mode until a
    TG-13 measured bar): the LEGACY decider owns the bool, byte-identical to
    today (AC29.1–AC29.4, AC29.7). The engine's verdict is recorded only.

    ENFORCED (only when the chokepoint says so): a confident Noul supplies the
    bool. The engine still never writes prose.

    ``acts`` (Stage B): the chokepoint's per-decision test on the confidence in
    the CHOSEN answer (``max(p, 1-p)``). When given it REPLACES the raw
    ``threshold`` margin: the verdict is ``p >= 0.5`` and it stands only when
    ``acts(conf)`` is true; below the calibrated threshold the legacy decider
    decides.

    ``defer=True`` (SHADOW only): the reply does not wait for the score. The
    legacy decider answers first; the Noul is scored on the ``oracle_shadow``
    lane and its row goes to :func:`emit_row` from there, so the returned row is
    None. Measured 2026-10-05: depth_met, escalate_incomplete and the other
    inline shadow scores cost the reply 326-561 ms per turn each, for rows
    nothing on the answer path reads.

    Fail-safe: an unavailable/below-threshold Noul leaves the legacy decider in
    charge; a raising decider returns False (the conservative answer for all
    the questions).
    """
    if defer and not enforced:
        _scope = _scope_now()
        try:
            value = bool(brain_bool_fn())
        except Exception as e:  # noqa: BLE001 — fail safe, never raise
            logger.warning("[surface] %s legacy decider failed: %r", consumer_id, e)
            _submit_shadow(consumer_id, statement, engine, None, frame, criteria_version,
                           _scope)
            return False, None
        _submit_shadow(consumer_id, statement, engine, value, frame, criteria_version,
                       _scope)
        return value, None

    noul = score_surface_bool(consumer_id, statement, engine=engine, frame=frame)
    _scope = _scope_now()
    _ik = input_key(consumer_id, statement, frame)

    if acts is not None:
        _engine_decides = bool(enforced and noul is not None and acts(
            max(float(noul.probability), 1.0 - float(noul.probability))))
        _cut = 0.5
    else:
        _engine_decides = bool(
            enforced and noul is not None and noul.confident(threshold))
        _cut = threshold
    if _engine_decides:
        value = bool(noul.true(_cut))
        return value, shadow_row(consumer_id, noul, brain_bool=value,
                                 scope=_scope, input_key=_ik)

    try:
        value = bool(brain_bool_fn())
    except Exception as e:  # noqa: BLE001 — fail safe, never raise
        logger.warning("[surface] %s legacy decider failed: %r", consumer_id, e)
        return False, shadow_row(consumer_id, noul, brain_bool=None,
                                 scope=_scope, input_key=_ik)
    return value, shadow_row(consumer_id, noul, brain_bool=value, scope=_scope,
                             input_key=_ik)


_NA_ACTION_LEAD = re.compile(
    r"^\s*(run|read|write|edit|update|create|modify|execute|search|list|"
    r"navigate|open|install|copy|move|delete|add|apply|build|compile|test|"
    r"check|verify|inspect|rename|remove|append|save|fetch|download|upload|"
    r"implement)\b",
    re.IGNORECASE,
)
# A planner marker is not a step goal: "Duplicate of step 1 (already
# completed) - skip or rephrase" and the RESOLVE markers describe the PLAN's
# bookkeeping. They carry no honest answer to the consumer's question.
_NA_ARTIFACT = re.compile(r"^\s*(duplicate of step|resolve:)", re.IGNORECASE)

# v6 (2026-10-20): does the goal name an action ANYWHERE? The slip test above
# looks at the LEADING verb only; this one is the mirror guard for the case
# where a call RAN. "Parse the test output" names no action; "Find the failing
# function and fix it" does. Deliberately excludes bare "test", "output",
# "count" and "result": those are nouns in goals that need no tool.
_NA_ACTION_ANYWHERE = re.compile(
    r"\b(read|reads|reading|write|writes|writing|edit|edits|editing|patch|"
    r"list|lists|listing|run|runs|running|grep|search|searches|glob|open|"
    r"opens|create|creates|creating|delete|removes?|rename|renames|install|"
    r"start|stop|fetch|download|browse|navigate|execute|apply|applies|add|"
    r"adds|modify|modifies|update|updates|fix|fixes|copy|move|build|compile|"
    r"inspect|append|save|upload|implement)\b",
    re.IGNORECASE,
    )


def needs_action_label(goal: str, calls: Any, success: bool) -> Optional[bool]:
    """The honest outcome label for a DER node, or None when the row must not exist.

    ``needs_action`` asks whether the GOAL needs a tool call. The outcome
    labels that question only when it is unambiguous:

      * a call that RAN  -> True (a tool was needed; the v2 rule, kept)
      * no call + success -> False, but ONLY when the goal does not name a
        tool action. Measured on 294 real goal+outcome pairs (2026-10-19): 15
        rows whose goal was "Run main.py to verify ..." / "Edit the geometry
        files ..." completed with no call. Those are SLIPS - the agent
        skipped the work - not evidence that the goal needed no tool; the
        consumer's own answer for them ("yes") is correct, so labelling them
        "no" made correct answers count as errors and inverted the ranking.
        A shape test cannot know the step slipped, so it refuses the row.
      * anything else -> None (an ambiguous outcome is not evidence).
    """
    try:
        text = str(goal or "")
        for c in calls or []:
            if c.get("ok_call", c.get("ok")):
                # v6 (2026-10-20): the MIRROR of the slip case. A goal that names
                # no action ANYWHERE, yet ran a call, did not force that call -
                # the REACT loop used a tool on an analysis step ("Parse the test
                # output to count the number of failures"). Measured on 495 real
                # pairs: this shape is 30 rows, the consumer says "no" on 24 of
                # them, and the label scores all 24 as errors - 45% of the
                # cohort's error mass from 6% of its rows. It is also the group
                # whose label is unstable (30/79 True for an identical shape),
                # which is what flattened the confidence bands and made clause 8
                # unreachable. The outcome cannot tell "needed" from "used", so
                # the row is refused, exactly as the slip case refuses its half.
                if not _NA_ACTION_ANYWHERE.search(text):
                    return None
                return True
        if not calls and success:
            if _NA_ACTION_LEAD.match(text) or _NA_ARTIFACT.match(text):
                return None
            return False
        return None
    except Exception:  # noqa: BLE001 - a measurement never fails a step
        return None


def _submit_shadow(consumer_id: str, statement: str, engine: Any,
                   brain_bool: Optional[bool], frame: Optional[dict],
                   criteria_version: Optional[str] = None,
                   scope: Optional[Dict[str, str]] = None,
                   outside_label: Optional[bool] = None) -> None:
    """Score + emit one shadow row on the ``oracle_shadow`` lane. Values are
    bound now (the statement, the frame, the legacy answer, the scope ids), so
    the row pairs what THIS call saw. Never raises; a full lane is counted by
    the lane."""
    _frame = dict(frame) if frame else None
    _scope = dict(scope) if scope else _scope_now()
    _ik = input_key(consumer_id, statement, _frame)

    def _job() -> None:
        noul = score_surface_bool(consumer_id, statement, engine=engine, frame=_frame)
        row = shadow_row(consumer_id, noul, brain_bool=brain_bool, scope=_scope,
                         input_key=_ik)
        if row is not None and criteria_version:
            row["criteria_version"] = criteria_version
        if row is not None and outside_label is not None:
            row["outside_label"] = bool(outside_label)
            row["label_source"] = "outcome"
        if row is not None and consumer_id == "depth_met":
            # depth_met/v3 (oracle.md 7.5, 2026-10-17): the row is HELD for the
            # turn's EXTERNAL verdict (the eval harness's hidden tests; a user
            # correction for live turns) instead of written on the loop grade -
            # the grade is a deterministic rule over inputs the model never
            # sees, and grading against it held the consumer at oof AUROC 0.40
            # (confidence ranked errors BACKWARDS). Held rows are written once,
            # with the verdict as their outside label, by report_verdict; the
            # map is bounded and the drop counted. try/except: a label never
            # blocks a consult - on any failure the row writes exactly as
            # before.
            try:
                from backend.agent import turn_verdict_label as _tvl

                if _tvl.defer(row, emit_row):
                    return
            except Exception:  # noqa: BLE001 — fall through to the plain emit
                pass
        emit_row(row)

    try:
        from backend.utils.durability_queue import lane

        if not lane("oracle_shadow").submit(f"surface:{consumer_id}", _job):
            logger.warning("[surface] %s shadow row dropped (lane full)", consumer_id)
    except Exception as e:  # noqa: BLE001 — a shadow never raises
        logger.warning("[surface] %s shadow submit failed: %r", consumer_id, e)
