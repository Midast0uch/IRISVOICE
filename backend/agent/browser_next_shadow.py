"""browser_next — which page element should the agent act on? (2026-10-11).

WHY THIS EXISTS. The Oracle's tool-calling consumers ask d1 to copy the tool
model's PROCEDURE (read before edit), which is not in the state: tool_choice
parity stayed 50.8% -> 54.3% even after the frame carried the step's own calls
(pin_c66d84ce99f6). A browser element choice is the opposite kind of question:
the answer IS in the state - the step's goal and the page's numbered element
list, the same list the tool model reads - so it is a System One decision in
d1's own shape (a choice over named options).

SHADOW ONLY. Nothing here changes what runs. At every ``browser_act`` on an
element, d1 is asked which element the step should act on, given the goal and
the page the model saw; the row is paired with the element the model chose
(``brain_choice``). When the consult agrees at a calibrated confidence that
clears the bar, a later change may let the Oracle make the click itself and
skip a model call - not before.

THE STATE is the `route` job's fields: goal, done_when, calls_this_step and the
page (title, url, text digest) as ``last_result``. The element labels are the
OPTIONS (rendered into the option lines as dynamic criteria), never state text.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("browser_next_shadow")

BROWSER_NEXT_CONSUMER = "browser_next"
BROWSER_NEXT_INSTRUCTION = (
    "Which page element should be acted on next to make progress on the goal?"
)
CRITERIA_VERSION = "browser_next/v1"

# The marker browser_tools._do_observe writes before the numbered list.
_ELEMENTS_MARK = "Elements (pass the number as element_id to browser_act):"
_LINE = re.compile(r"^\[(\d+)\]\s+(.*)$")
# The option set is bounded: the reference's code pool is A..Z then 00..99.
_MAX_OPTIONS = 120
_ROW_TOP = 8  # candidates kept on the row (bounded row size)

AUTO_ENGINE = object()
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
            logger.debug("[browser_next] row sink failed: %r", e)
    logger.info("[browser_next] shadow row chosen=%s brain=%s conf=%s",
                row.get("chosen"), row.get("brain_choice"), row.get("confidence"))


def parse_page(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """``(page head, [(element id, label), ...])`` from an observation's content.

    The head is everything before the element list (title, url, text digest);
    the elements are the numbered lines after it. ``("", [])`` when the text
    carries no element list (the previous call was not an observation)."""
    if not text or _ELEMENTS_MARK not in text:
        return "", []
    head, _, body = text.partition(_ELEMENTS_MARK)
    elements: List[Tuple[str, str]] = []
    for line in body.splitlines():
        m = _LINE.match(line.strip())
        if m:
            elements.append((m.group(1), m.group(2).strip()[:80] or f"element {m.group(1)}"))
            if len(elements) >= _MAX_OPTIONS:
                break
    return head.strip(), elements


def register_browser_next_consumer() -> bool:
    """Register the consumer's criteria (declared choice). Idempotent."""
    try:
        from backend.agent.decision_engine import (
            get_consumer_spec,
            needs_upgrade,
            register_declared,
        )
        if not needs_upgrade(get_consumer_spec(BROWSER_NEXT_CONSUMER)):
            return False
        register_declared(BROWSER_NEXT_CONSUMER, BROWSER_NEXT_INSTRUCTION)
        return True
    except Exception as e:  # noqa: BLE001 — criteria are best-effort
        logger.debug("[browser_next] consumer spec unavailable: %s", e)
        return False


def _scope_now() -> Dict[str, str]:
    try:
        from backend.agent.decision_engine import scope_now

        return scope_now()
    except Exception:  # noqa: BLE001 - scope is best-effort
        return {}


def score(frame: Dict[str, Any], options: List[str], engine: Any) -> Optional[Any]:
    """d1's choice over the element ids, or None. Never raises."""
    try:
        register_browser_next_consumer()
        if engine is AUTO_ENGINE:
            from backend.agent.decision_engine import get_decision_engine

            engine = get_decision_engine()
        if engine is None:
            return None
        return engine.decide(BROWSER_NEXT_CONSUMER, options, frame)
    except Exception as e:  # noqa: BLE001 — a shadow never raises
        logger.debug("[browser_next] score failed: %r", e)
        return None


def shadow_row(ds: Any, brain_choice: str, action: str,
               scope: Optional[Dict[str, str]] = None,
               state: str = "", brain_ok: Optional[bool] = None) -> Optional[dict]:
    """The row for one element judgment, or None (no score, no row)."""
    if ds is None:
        return None
    ranked = sorted(ds.distribution or (), key=lambda c: -c.prob)
    top = ranked[:_ROW_TOP]
    # The model's element ALWAYS rides the row: the report reads a reference
    # missing from the candidates as "truncated off the menu" (unscoreable) -
    # measured: 7 of the first 14 rows were lost that way.
    top += [c for c in ranked[_ROW_TOP:] if c.name == str(brain_choice)]
    row = {
        "consumer_id": BROWSER_NEXT_CONSUMER,
        "job": "route",
        "chosen": str(ds.chosen),
        "confidence": round(float(ds.confidence), 4),
        "candidates": [{"name": c.name, "prob": round(c.prob, 4)} for c in top],
        "n_options": len(ds.distribution or ()),
        "engine_latency_ms": ds.engine_latency_ms,
        "brain_choice": str(brain_choice),
        "action": str(action or ""),
        "shadow": True,
        "criteria_version": CRITERIA_VERSION,
        # replay keys: what d1 read (the page head; the element labels are the
        # options) and whether the model's act worked
        "state": (state or "")[:2000],
        "brain_ok": brain_ok,
    }
    if scope:
        row.update(scope)
    return row


def record_browser_next(
    *,
    goal: str,
    page_text: str,
    element_id: Any,
    action: str,
    done_when: Optional[str] = None,
    calls_this_step: Optional[str] = None,
    engine: Any = AUTO_ENGINE,
    brain_ok: Optional[bool] = None,
) -> bool:
    """Submit the consult on the ``oracle_shadow`` lane. Returns True when a
    consult was queued. The values are bound NOW (the page and the step change
    after this call). No element list, or the model's element not on it, means
    no row: an element the menu never offered is unscoreable, never wrong."""
    head, elements = parse_page(page_text)
    ids = [e[0] for e in elements]
    target = str(element_id).strip() if element_id is not None else ""
    if not ids or target not in ids:
        return False
    frame = {
        "goal": (goal or "")[:200],
        "done_when": (done_when or "")[:200] or None,
        "calls_this_step": (calls_this_step or "")[-300:] or None,
        "last_result": head[:800] or None,
        # the element labels go into the OPTION LINES ("A Sign in"), never the state
        "option_criteria": {eid: label for eid, label in elements},
    }
    scope = _scope_now()
    try:
        from backend.agent.decision_engine import job_input

        state = job_input(BROWSER_NEXT_CONSUMER, frame).text
    except Exception:  # noqa: BLE001 - a replay key never blocks a row
        state = ""

    def _job() -> None:
        emit_row(shadow_row(score(frame, ids, engine), target, action, scope,
                            state=state, brain_ok=brain_ok))

    try:
        from backend.utils.durability_queue import lane

        if not lane("oracle_shadow").submit("browser_next", _job):
            logger.warning("[browser_next] shadow row dropped (lane full)")
            return False
        return True
    except Exception as e:  # noqa: BLE001 — a shadow never raises
        logger.warning("[browser_next] shadow submit failed: %r", e)
        return False
