"""Loop-monitor bool consumers — shadow-first (REQ-14, T18).

Three per-turn Brain calls ask a BOOLEAN question about the step state:

  ``sufficient``  the sufficiency gate   (agent_kernel, advisory-fail-closed)
  ``done``        the Explorer done-bit  (goal-contract override preserved)
  ``on_track``    the FULL-mode drift check

Because the question is "is this statement true", each is answered with a
:class:`~backend.agent.decision_engine.Noul` — a single calibrated probability
of truth — rather than a two-option Choice (AC14.6). A 2-way softmax is a
different object, and AC14.4's fail-closed gate semantics depend on the
probability meaning what it claims.

FOUNDATION SCOPE (AC14.1/AC14.2/AC14.4): the Brain calls are UNCHANGED. The
engine is scored in shadow and its row recorded, so the parity data AC14.3's
flip needs can accumulate. AC14.3 (skip the Brain on a confident positive) is
Wave 7's measured flip and is gated behind ``enforced``, which defaults off.

Two invariants this module exists to hold:
  * THE ENGINE NEVER WRITES THE TEXT. On a negative branch the Brain writes
    ``missing`` / the next-goal description / ``note``+``suggestion``; the
    engine only ever supplies the bool (AC14.2).
  * FAIL CLOSED. Any failure — no engine, no criteria, a scoring error, or a
    raising Brain — returns ``(False, "")`` for the sufficiency gate, exactly
    the shape the advisory gate already had (AC14.4).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger("monitor_shadow")

MONITOR_CONSUMERS: Dict[str, str] = {
    "sufficient": (
        "Is the evidence gathered so far sufficient to answer the objective?"
    ),
    "done": "Is the objective complete?",
    "on_track": (
        "Is the current approach still on track to complete the objective?"
    ),
}

_TRUE_LABEL = "yes"
_FALSE_LABEL = "no"

# Sentinel: adopt the module-level engine singleton. `engine=None` means NO
# ENGINE (fail-closed) — never "resolve the singleton", or a shadow scorer
# would silently load the 651MB model the first time it is called.
AUTO_ENGINE = object()

# Process-wide row sink (REQ-14 AC14.1). The three monitor sites have no bridge
# of their own, so this is how their rows reach a ledger (the kernel installs
# it) — and how a test observes them. None = log only, never silently dropped.
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
            logger.debug("[monitor] row sink failed: %r", e)
    logger.info(
        "[monitor] shadow row consumer=%s chosen=%s conf=%s brain=%s",
        row.get("consumer_id"), row.get("chosen"), row.get("confidence"),
        row.get("brain_bool"),
    )


def register_monitor_consumers() -> int:
    """Register the three bool consumers' criteria (REQ-19 AC19.1). Idempotent.

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
        logger.warning("[monitor] consumer specs unavailable: %s", e)
        return 0
    added = 0
    for cid, instruction in MONITOR_CONSUMERS.items():
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


def score_monitor_bool(
    consumer_id: str,
    statement: str,
    *,
    engine: Any = None,
    frame: Optional[dict] = None,
) -> Optional[Any]:
    """The consumer's Noul for *statement*, or None (AC14.1/AC14.6).

    Never raises: a shadow must not be able to break the loop it observes.
    """
    try:
        register_monitor_consumers()
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
        logger.debug("[monitor] %s shadow failed: %r", consumer_id, e)
        return None


def _default_engine():
    try:
        from backend.agent.decision_engine import get_decision_engine
        return get_decision_engine()
    except Exception:  # noqa: BLE001
        return None


def shadow_row(
    consumer_id: str,
    noul: Optional[Any],
    brain_bool: Optional[bool],
) -> Optional[dict]:
    """The CT-DEI-6-shaped row for a monitor judgment, or None.

    No Noul → no row: a missing engine must never fabricate a shadow row.
    ``brain_bool`` is the Brain's ACTUAL answer, so the row is a shadow PAIR
    (engine said X, reality ran Y) and the parity metric exists.
    """
    if noul is None:
        return None
    return {
        "consumer_id": consumer_id,
        "chosen": bool(noul.true(0.5)),
        "confidence": round(float(noul.probability), 4),
        # AC14.6: the Noul shape — one probability of truth, no winner, no
        # separate confidence field.
        "probability": round(float(noul.probability), 4),
        "engine_latency_ms": noul.engine_latency_ms,
        "brain_bool": brain_bool,
        "shadow": True,
    }


def monitor_bool(
    consumer_id: str,
    statement: str,
    *,
    brain_bool_fn: Callable[[], bool],
    brain_text_fn: Callable[[], str],
    engine: Any = None,
    enforced: bool = False,
    threshold: float = 0.8,
    defer: bool = False,
) -> Tuple[bool, str, Optional[dict]]:
    """One monitor judgment: (value, text, shadow_row).

    SHADOW (``enforced=False``, the default and the only shipped mode until
    Wave 7 measures the bar): the Brain decides the bool AND writes the text
    on the negative branch — behaviour byte-identical to today (AC14.1).

    ENFORCED (Wave 7 only, and only above the measured bar): a confident Noul
    supplies the bool. ``threshold`` is the TWO-SIDED margin (p >= t or
    p <= 1-t), so a confident "not true" enforces just like a confident "true". A NEGATIVE branch still calls ``brain_text_fn`` for the
    text — the engine never writes assessments (AC14.2) — while a POSITIVE
    branch skips the Brain entirely (AC14.3).

    Fail-closed (AC14.4): an unavailable/below-threshold Noul leaves the Brain
    in charge; a raising Brain yields ``(False, "")``.

    ``defer=True`` (SHADOW only): the reply does not wait for the score. The
    Brain answers first; the Noul is scored on the ``oracle_shadow`` lane (one
    ordered writer) and its row goes to :func:`emit_row` from there, so the
    returned row is None. Measured 2026-10-01 (eval c04): the turn-end `done`
    and `on_track` scores held the reply 4.3 s + 1.3 s for rows nothing reads
    on the answer path.
    """
    if defer and not enforced:
        try:
            value = bool(brain_bool_fn())
        except Exception as e:  # noqa: BLE001 — fail closed, never raise
            logger.warning("[monitor] %s brain bool failed: %r", consumer_id, e)
            _submit_shadow(consumer_id, statement, engine, None)
            return False, "", None
        text = "" if value else _safe_text(brain_text_fn)
        _submit_shadow(consumer_id, statement, engine, value)
        return value, text, None

    noul = score_monitor_bool(consumer_id, statement, engine=engine)

    _engine_decides = bool(
        enforced and noul is not None and noul.confident(threshold)
    )
    if _engine_decides:
        value = bool(noul.true(threshold))
        text = "" if value else _safe_text(brain_text_fn)
        row = shadow_row(consumer_id, noul, brain_bool=value)
        return value, text, row

    try:
        value = bool(brain_bool_fn())
    except Exception as e:  # noqa: BLE001 — fail closed, never raise
        logger.warning("[monitor] %s brain bool failed: %r", consumer_id, e)
        return False, "", shadow_row(consumer_id, noul, brain_bool=None)
    text = "" if value else _safe_text(brain_text_fn)
    return value, text, shadow_row(consumer_id, noul, brain_bool=value)


def _submit_shadow(consumer_id: str, statement: str, engine: Any,
                   brain_bool: Optional[bool]) -> None:
    """Score + emit one shadow row on the ``oracle_shadow`` lane. Values are
    bound now (the statement and the Brain's answer), so the row pairs what
    THIS turn saw. Never raises; a full lane is counted by the lane."""
    def _job() -> None:
        noul = score_monitor_bool(consumer_id, statement, engine=engine)
        emit_row(shadow_row(consumer_id, noul, brain_bool=brain_bool))

    try:
        from backend.utils.durability_queue import lane

        if not lane("oracle_shadow").submit(f"monitor:{consumer_id}", _job):
            logger.warning("[monitor] %s shadow row dropped (lane full)", consumer_id)
    except Exception as e:  # noqa: BLE001 — a shadow never raises
        logger.warning("[monitor] %s shadow submit failed: %r", consumer_id, e)


def sufficiency_gate(
    statement: str,
    *,
    brain_bool_fn: Callable[[], bool],
    brain_text_fn: Callable[[], str],
    engine: Any = None,
    enforced: bool = False,
    threshold: float = 0.8,
) -> Tuple[bool, str]:
    """AC14.4: the sufficiency gate's advisory-FAIL-CLOSED shape.

    Inference/parse failure returns ``(False, "")`` — "not sufficient, no
    missing-text" — exactly as the gate already did, now with the engine's
    failure feeding the same path instead of a second one.
    """
    try:
        value, text, _row = monitor_bool(
            "sufficient", statement,
            brain_bool_fn=brain_bool_fn, brain_text_fn=brain_text_fn,
            engine=engine, enforced=enforced, threshold=threshold,
        )
        # AC14.1: the row reaches the sink from HERE, so a caller that only
        # wants (value, text) cannot accidentally drop the calibration data.
        emit_row(_row)
        return bool(value), text or ""
    except Exception as e:  # noqa: BLE001 — advisory fail-closed
        logger.warning("[monitor] sufficiency gate failed: %r", e)
        return False, ""


def _safe_text(fn: Callable[[], str]) -> str:
    try:
        return fn() or ""
    except Exception as e:  # noqa: BLE001 — the text is best-effort
        logger.debug("[monitor] brain text failed: %r", e)
        return ""
