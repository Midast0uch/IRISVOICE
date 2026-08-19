"""Bridge: EventBus frontend-relevant events -> WebSocket delivery.

The EventBus is internal-only (kernel-to-kernel routing). This component
subscribes to the events the frontend needs and broadcasts them to the WS.
It is the single delivery path for task/question/permission/context events.

Threading note: the DER loop runs inside a thread pool (run_in_executor), so
EventBus.emit() fires OFF the main event loop. Handlers are therefore SYNC and
schedule the broadcast on the captured main loop via
asyncio.run_coroutine_threadsafe (same pattern as tool_bridge.py:880 and
iris_gateway.py:2016). Do NOT make handlers async — the bus's async fallback
would spin up a throwaway event loop and the broadcast would never reach the
live WS connections.

Exclusions (already delivered directly -- DO NOT re-forward to avoid duplicate
frontend CustomEvents):
  - TOOL_RESULT  (tool_bridge.py:881 broadcasts directly; the WS hook ignores
                 the raw "tool_result" message, so we re-forward it here for
                 iris:task_update without duplication)
  - MODE_CHANGED  (main.py:998 broadcasts directly)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, List, Tuple

from .event_bus import get_event_bus, IRISStreamEvent

logger = logging.getLogger(__name__)

# Events the bridge forwards to the frontend.
_BRIDGED_EVENTS: Tuple[IRISStreamEvent, ...] = (
    IRISStreamEvent.TASK_START,
    IRISStreamEvent.TASK_PROGRESS,
    IRISStreamEvent.TASK_MILESTONE,
    IRISStreamEvent.TASK_DONE,
    IRISStreamEvent.TASK_FAIL,
    IRISStreamEvent.TOOL_CALL,
    IRISStreamEvent.TOOL_RESULT,
    IRISStreamEvent.TOOL_ERROR,
    IRISStreamEvent.QUESTION_ASK,
    IRISStreamEvent.QUESTION_ANSWERED,
    IRISStreamEvent.QUESTION_TIMEOUT,
    IRISStreamEvent.PERMISSION_REQUEST,
    IRISStreamEvent.PERMISSION_GRANTED,
    IRISStreamEvent.PERMISSION_DENIED,
    IRISStreamEvent.CONTEXT_USAGE,
    IRISStreamEvent.DOCUMENT_RENDER,
    IRISStreamEvent.LISTENING_STATE,
    # ── Execution-hardening plan events (Phase 4.1) ──────────────────────────
    # Forwarded so the frontend can surface recovery / validation / budget
    # signals in the chat as system messages.  All four are emitted by the
    # agent kernel (RC1 validation -> VALIDATION_FAILED, graft recovery ->
    # RECOVERY_START, Caducean recovery -> TOPOLOGY_RECOVERY, budget exhaustion
    # -> BUDGET_EXHAUSTED) and must reach the WS to be displayed.
    IRISStreamEvent.BUDGET_EXHAUSTED,
    IRISStreamEvent.VALIDATION_FAILED,
    IRISStreamEvent.RECOVERY_START,
    IRISStreamEvent.TOPOLOGY_RECOVERY,
    # ── REQ-15 (T26): pause/resume lifecycle + steering acknowledgement ─────
    # AC4: TASK_PAUSED/TASK_RESUMED make the suspended state visible; AC5:
    # STEERING_ACK carries the queued/considered acknowledgement so the user
    # sees the steering message landed and was applied.
    IRISStreamEvent.TASK_PAUSED,
    IRISStreamEvent.TASK_RESUMED,
    IRISStreamEvent.STEERING_ACK,
    # ── Vision routing (REQ-3 AC6) ───────────────────────────────────────
    # No VL fallback candidate fit free VRAM — surfaced as a chat system
    # message the same way BUDGET_EXHAUSTED/VALIDATION_FAILED are.
    IRISStreamEvent.VISION_UNAVAILABLE,
)

# Events added at runtime (e.g. future additions) so the tuple above stays
# static for import-time safety.
_BRIDGED_EVENTS_EXT: List[IRISStreamEvent] = []


class WSEventBridge:
    """Subscribes to EventBus events and broadcasts them to the WebSocket.

    Fire-and-forget: sync handlers schedule the async broadcast on the main
    loop and return immediately. Never blocks the DER loop.
    """

    def __init__(self, ws_manager: Any) -> None:
        self._ws = ws_manager
        self._bus = get_event_bus()
        self._main_loop: Any = None
        self._subs: List[Tuple[IRISStreamEvent, Any]] = []
        self._started = False

    def set_main_loop(self, loop: Any) -> None:
        """Capture the running event loop (called from IRISGateway.set_main_loop)."""
        self._main_loop = loop

    def add_event(self, event: IRISStreamEvent) -> None:
        """Register an additional event type to bridge (e.g. CONTEXT_USAGE)."""
        if event not in _BRIDGED_EVENTS and event not in _BRIDGED_EVENTS_EXT:
            _BRIDGED_EVENTS_EXT.append(event)
            if self._started:
                self._bus.subscribe(event, self._make_handler(event))

    def start(self) -> None:
        if self._started:
            return
        for evt in list(_BRIDGED_EVENTS) + list(_BRIDGED_EVENTS_EXT):
            handler = self._make_handler(evt)
            self._bus.subscribe(evt, handler)
            self._subs.append((evt, handler))
        self._started = True
        logger.info("[WSEventBridge] subscribed to %d event types", len(self._subs))

    def stop(self) -> None:
        for evt, handler in self._subs:
            try:
                self._bus.unsubscribe(evt, handler)
            except Exception:
                pass
        self._subs.clear()
        self._started = False

    def _make_handler(self, evt: IRISStreamEvent):
        def handler(payload) -> None:
            try:
                session_id = getattr(payload, "session_id", None)
                data = getattr(payload, "data", None) or {}
                # REQ-6 AC3: carry conversation_id on every bridged event so the
                # frontend can drop stale events from a cancelled/old thread. The
                # EventPayload already carries conversation_id (event_bus.py:131);
                # surface it on the wire even when the emit site omitted it from data.
                conv_id = getattr(payload, "conversation_id", None) or data.get(
                    "conversation_id"
                )
                if conv_id and "conversation_id" not in data:
                    data = dict(data)
                    data["conversation_id"] = conv_id
                msg = {"type": evt.value, "payload": data}
                loop = self._main_loop
                if loop is None:
                    # Loop not captured yet (events before server startup). Skip.
                    logger.debug("[WSEventBridge] no main loop yet; skipping %s", evt.value)
                    return
                if (
                    session_id
                    and session_id != "default"
                    and self._ws.session_exists(session_id)
                ):
                    asyncio.run_coroutine_threadsafe(
                        self._ws.broadcast_to_session(session_id, msg), loop
                    )
                else:
                    # pin_42ddd255162d: no session routing info, OR the session
                    # has no connected client — DER sub-loop/crawl events
                    # arrive under the placeholder session "unknown", and
                    # broadcast_to_session() silently DROPS messages for
                    # unknown sessions (get_session -> None). IRIS is
                    # single-user, so falling back to broadcast still reaches
                    # the one connected client; the conversation_id carried on
                    # the wire lets the frontend drop stale events.
                    asyncio.run_coroutine_threadsafe(self._ws.broadcast(msg), loop)
            except Exception as e:  # one bad payload never breaks others
                logger.warning("[WSEventBridge] %s forward failed: %s", evt.value, e)

        return handler
