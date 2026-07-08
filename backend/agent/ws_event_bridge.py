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
            self._bus.subscribe(evt, self._make_handler(evt))
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
                msg = {"type": evt.value, "payload": data}
                loop = self._main_loop
                if loop is None:
                    # Loop not captured yet (events before server startup). Skip.
                    logger.debug("[WSEventBridge] no main loop yet; skipping %s", evt.value)
                    return
                if session_id and session_id != "default":
                    asyncio.run_coroutine_threadsafe(
                        self._ws.broadcast_to_session(session_id, msg), loop
                    )
                else:
                    # No session routing info -- broadcast to all (IRIS is single-user).
                    asyncio.run_coroutine_threadsafe(self._ws.broadcast(msg), loop)
            except Exception as e:  # one bad payload never breaks others
                logger.warning("[WSEventBridge] %s forward failed: %s", evt.value, e)

        return handler
