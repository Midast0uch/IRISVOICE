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
    """Register the consumer's criteria (REQ-19 AC19.1). Idempotent."""
    from backend.agent.decision_backend_onnx import (
        ConsumerSpec,
        get_consumer_spec,
        register_consumer_spec,
    )

    if get_consumer_spec(CONSUMER_ID) is None:
        register_consumer_spec(ConsumerSpec(
            consumer_id=CONSUMER_ID, task_name=CONSUMER_ID,
            instruction=INSTRUCTION, labels=LABELS,
        ))


def record_assessment(statement: str, gate_verdict: str) -> Optional[dict]:
    """Score ``statement`` in shadow and emit ONE row paired with the gate's verdict.

    Blocking (the model call); run it on the lane. Returns the row, or None when
    there is no engine / no answer. Never raises.
    """
    try:
        engine = ENGINE
        if engine is AUTO_ENGINE:
            from backend.agent.decision_engine import get_decision_engine

            engine = get_decision_engine()
        if engine is None:
            return None
        register_consumer()
        ds = engine.decide(CONSUMER_ID, list(LABELS), {"goal": statement[:400]})
        if ds is None:
            return None
        row: Dict[str, Any] = {
            "consumer_id": CONSUMER_ID,
            "chosen": ds.chosen,
            "confidence": round(float(ds.confidence), 4),
            "engine_latency_ms": ds.engine_latency_ms,
            "brain_choice": gate_verdict,
            "shadow": True,
        }
        emit_row(row)
        return row
    except Exception as e:  # noqa: BLE001 - a shadow never raises
        logger.debug("[click_safety] shadow failed: %r", e)
        return None


def submit_assessment(statement: str, gate_verdict: str) -> bool:
    """Queue ``record_assessment`` on its ordered lane; never blocks the click."""
    try:
        from backend.utils.durability_queue import lane

        return bool(lane("click_safety_shadow").submit(
            "click_safety_row", record_assessment, statement, gate_verdict,
        ))
    except Exception as e:  # noqa: BLE001
        logger.debug("[click_safety] lane submit failed: %r", e)
        return False
