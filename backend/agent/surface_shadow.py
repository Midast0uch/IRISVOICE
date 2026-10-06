"""Remaining decision-surface consumers — shadow-first (REQ-29, T46–T49).

Choice-shaped Brain decisions that the §8.4 wiring survey missed. Each is a
BOOLEAN question the common case answers negatively, and each currently costs a
Brain call or a keyword list:

  ``use_thinking``        the ~40-phrase thinking trigger list
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

import logging
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger("surface_shadow")

SURFACE_CONSUMERS: Dict[str, str] = {
    "use_thinking": (
        "Does this request need extended step-by-step reasoning?"
    ),
    "escalate_incomplete": (
        "Is this step result too incomplete to proceed without more work?"
    ),
    "needs_action": "Does this goal require calling a tool?",
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
    """
    try:
        from backend.agent.decision_backend_onnx import (
            ConsumerSpec,
            get_consumer_spec,
            register_consumer_spec,
        )
    except Exception as e:  # noqa: BLE001 — criteria are best-effort
        logger.warning("[surface] consumer specs unavailable: %s", e)
        return 0
    added = 0
    for cid, instruction in SURFACE_CONSUMERS.items():
        if get_consumer_spec(cid) is not None:
            continue
        register_consumer_spec(ConsumerSpec(
            consumer_id=cid,
            task_name=cid,
            instruction=instruction,
            labels=(_TRUE_LABEL, _FALSE_LABEL),
        ))
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


def shadow_row(
    consumer_id: str,
    noul: Optional[Any],
    brain_bool: Optional[bool],
) -> Optional[dict]:
    """The CT-DEI-6-shaped row for a surface judgment, or None.

    No Noul → no row: a missing engine must never fabricate a shadow row.
    ``brain_bool`` is what the legacy decider ACTUALLY returned, so the row is
    a shadow PAIR and the parity metric exists.
    """
    if noul is None:
        return None
    p = float(noul.probability)
    return {
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
        try:
            value = bool(brain_bool_fn())
        except Exception as e:  # noqa: BLE001 — fail safe, never raise
            logger.warning("[surface] %s legacy decider failed: %r", consumer_id, e)
            _submit_shadow(consumer_id, statement, engine, None, frame, criteria_version)
            return False, None
        _submit_shadow(consumer_id, statement, engine, value, frame, criteria_version)
        return value, None

    noul = score_surface_bool(consumer_id, statement, engine=engine, frame=frame)

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
        return value, shadow_row(consumer_id, noul, brain_bool=value)

    try:
        value = bool(brain_bool_fn())
    except Exception as e:  # noqa: BLE001 — fail safe, never raise
        logger.warning("[surface] %s legacy decider failed: %r", consumer_id, e)
        return False, shadow_row(consumer_id, noul, brain_bool=None)
    return value, shadow_row(consumer_id, noul, brain_bool=value)


def _submit_shadow(consumer_id: str, statement: str, engine: Any,
                   brain_bool: Optional[bool], frame: Optional[dict],
                   criteria_version: Optional[str] = None) -> None:
    """Score + emit one shadow row on the ``oracle_shadow`` lane. Values are
    bound now (the statement, the frame and the legacy answer), so the row pairs
    what THIS call saw. Never raises; a full lane is counted by the lane."""
    _frame = dict(frame) if frame else None

    def _job() -> None:
        noul = score_surface_bool(consumer_id, statement, engine=engine, frame=_frame)
        row = shadow_row(consumer_id, noul, brain_bool=brain_bool)
        if row is not None and criteria_version:
            row["criteria_version"] = criteria_version
        emit_row(row)

    try:
        from backend.utils.durability_queue import lane

        if not lane("oracle_shadow").submit(f"surface:{consumer_id}", _job):
            logger.warning("[surface] %s shadow row dropped (lane full)", consumer_id)
    except Exception as e:  # noqa: BLE001 — a shadow never raises
        logger.warning("[surface] %s shadow submit failed: %r", consumer_id, e)
