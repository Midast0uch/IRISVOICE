"""click_safety consumer - shadow-first (specs/research-memory-chain-browser W2, AC7.4).

The click-safety gate (``agent/tools/click_safety.py``: rules -> Brain judge ->
ask the user) decides every browser action today. The Oracle scores the SAME
action in shadow so the parity data it needs to earn this decision accumulates:
one row per assessment, ``chosen`` = the engine's pick, ``brain_choice`` = the
gate's verdict. Nothing here decides anything (CLAUDE.md "THE ORACLE EARNS ITS
JOBS"): no enforced mode exists.

Wired like ``monitor_shadow``: a process-wide row sink the kernel installs
(``AgentKernel.__init__`` -> ``set_row_sink``), so the row lands in the same
single-writer ledger. Scoring runs on the ``click_safety_shadow`` lane, never on
the click's own path. Engine unavailable -> no row (a missing engine never
fabricates a row).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("click_safety_shadow")

CONSUMER_ID = "click_safety"
INSTRUCTION = "Is this browser action safe to perform without asking the user?"
LABELS = ("safe", "unsafe", "unsure")

# Sentinel: adopt the module-level engine singleton. `ENGINE = None` means NO
# ENGINE - never "resolve the singleton", or a shadow scorer would silently load
# the model on first use. Tests replace ENGINE with a fake.
AUTO_ENGINE = object()
ENGINE: Any = AUTO_ENGINE

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
        except Exception as e:  # noqa: BLE001 - an observer never blocks
            logger.debug("[click_safety] row sink failed: %r", e)
    logger.info(
        "[click_safety] shadow row chosen=%s brain=%s conf=%s",
        row.get("chosen"), row.get("brain_choice"), row.get("confidence"),
    )


def register_consumer() -> None:
    """Register the consumer's criteria (REQ-19 AC19.1, REQ-4). Idempotent.

    The DECLARED type and criteria come from the declaration table
    (`register_declared`); this site supplies only its own instruction and
    labels. `needs_upgrade` also replaces a spec that predates REQ-4 (AC13.4).
    """
    from backend.agent.decision_engine import (
        get_consumer_spec,
        needs_upgrade,
        register_declared,
    )

    if needs_upgrade(get_consumer_spec(CONSUMER_ID)):
        register_declared(CONSUMER_ID, INSTRUCTION, LABELS)


def _scope_now() -> Dict[str, str]:
    """REQ-6 AC6.3a: the row's scope (turn/step/node ids), bound AS VALUES at
    submit time - this module's lane runs the score later on a worker thread
    whose own context says nothing."""
    try:
        from backend.agent.decision_engine import scope_now

        return scope_now()
    except Exception:  # noqa: BLE001 - scope is best-effort, never fatal
        return {}


def record_assessment(statement: str, gate_verdict: str,
                      screenshot: Optional[bytes] = None,
                      scope: Optional[Dict[str, str]] = None,
                      defer_outcome: bool = False) -> Optional[dict]:
    """Score ``statement`` in shadow and emit ONE row paired with the gate's verdict.

    Blocking (the model call); run it on the lane. Returns the row, or None when
    there is no engine / no answer. Never raises.

    REQ-5 (AC5.1/AC5.3): ``screenshot`` is the SESSION-SCOPED browser capture
    (never the desktop) the call site took at assess time. ``guard`` is the one
    job that declares an image, so only this consumer's state carries it; the
    lane runs LATER and the session may have moved, so the bytes are pinned at
    submit time rather than re-captured here (a late frame would mislabel the
    row).
    """
    try:
        engine = ENGINE
        if engine is AUTO_ENGINE:
            from backend.agent.decision_engine import get_decision_engine

            engine = get_decision_engine()
        if engine is None:
            return None
        register_consumer()
        frame: Dict[str, Any] = {"goal": statement[:400]}
        if isinstance(screenshot, (bytes, bytearray)) and screenshot:
            frame["screenshot"] = bytes(screenshot)
        ds = engine.decide(CONSUMER_ID, list(LABELS), frame)
        if ds is None:
            return None
        row: Dict[str, Any] = {
            "consumer_id": CONSUMER_ID,
            "chosen": ds.chosen,
            "confidence": round(float(ds.confidence), 4),
            "engine_latency_ms": ds.engine_latency_ms,
            "brain_choice": gate_verdict,
            "shadow": True,
            # v2 (2026-10-11): action-first statement + guard budget 128 - the
            # old rows read a goal-first text cut before the action.
            "criteria_version": "click_safety/v2",
        }
        if scope:
            row.update(scope)
        # REQ-6 AC6.2/AC6.6: a SAMPLED consult's row is labelled by the turn's
        # outcome (registered by the caller), not paired with the incumbent -
        # skipping the parity emit here is what makes the row OUTCOME-labelled.
        if defer_outcome:
            return row
        emit_row(row)
        return row
    except Exception as e:  # noqa: BLE001 - a shadow never raises
        logger.debug("[click_safety] shadow failed: %r", e)
        return None


def statement(action: str, goal: str) -> str:
    """The consult's text: the ACTION first, then the task (click_safety/v2).

    It used to be ``goal | action``, and the guard budget (64 ids, ~256 chars)
    cut from the END - with a long step goal the action, the very thing the
    question is about, never reached the model."""
    return f"{action} | task: {(goal or '')[:300]}"


def submit_assessment(statement: str, gate_verdict: str,
                      screenshot: Optional[bytes] = None) -> bool:
    """Queue ``record_assessment`` on its ordered lane; never blocks the click."""
    try:
        from backend.utils.durability_queue import lane

        _scope = _scope_now()  # bound NOW; the lane's context is empty
        return bool(lane("click_safety_shadow").submit(
            "click_safety_row", record_assessment, statement, gate_verdict,
            screenshot, _scope,
        ))
    except Exception as e:  # noqa: BLE001
        logger.debug("[click_safety] lane submit failed: %r", e)
        return False
