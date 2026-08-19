#!/usr/bin/env python3
"""
EventBus — typed pub/sub event system for kernel separation.

Sits between the agent kernel and the frontend.  Two kernel types
subscribe to events:
  - ConversationKernel: speech events (utterances → TTS)
  - TaskKernel: tool events (task list, progress, milestones)

Events are typed (IRISStreamEvent enum), delivered in-order per turn_id,
and handler isolation means one handler crash never blocks others.

A small bounded ring buffer (100 events) allows late subscribers to
replay missed events — critical for TaskListCard mounting after
tool_calls have already fired.
"""

from __future__ import annotations

import asyncio
import enum
import inspect
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

RING_BUFFER_SIZE = 100
MAX_EVENT_QUEUE_SIZE = 1000


# ── Event types ────────────────────────────────────────────────────────────


class IRISStreamEvent(enum.Enum):
    """All event types that flow through EventBus.

    Naming convention: <domain>_<action>.
    """

    # ── Agent lifecycle ────────────────────────────────────────────────
    AGENT_START = "agent:start"
    AGENT_STOP = "agent:stop"
    AGENT_ERROR = "agent:error"

    # ── Text / chat ────────────────────────────────────────────────────
    TEXT_RESPONSE_CHUNK = "text:response_chunk"
    TEXT_RESPONSE_DONE = "text:response_done"

    # ── Utterance (agent-initiated speech) ──────────────────────────────
    UTTERANCE_START = "utterance:start"
    UTTERANCE_CHUNK = "utterance:chunk"
    UTTERANCE_DONE = "utterance:done"

    # ── Document render (speak/show separation, Issue C.1) ──────────────
    # Carries the `show` payload (format/content/alternatives) to the
    # frontend so a generated document renders visually while only the
    # `speak` summary is read aloud by TTS.
    DOCUMENT_RENDER = "document:render"

    # ── Tool execution ──────────────────────────────────────────────────
    TOOL_CALL = "tool:call"
    TOOL_RESULT = "tool:result"
    TOOL_ERROR = "tool:error"

    # ── Task lifecycle ──────────────────────────────────────────────────
    TASK_START = "task:start"
    TASK_PROGRESS = "task:progress"
    TASK_MILESTONE = "task:milestone"
    TASK_DONE = "task:done"
    TASK_FAIL = "task:fail"
    # REQ-8: honest learning signal. Emitted when a DER step is avoided
    # (FAILED -> AVOID), retried (verify_failed -> split into Sub-Loops), or
    # crystallized (VERIFIED -> skill captured). Drives the Pacman OrbCanvas
    # particles on the TaskListCard border. Carries real state, never narration.
    TASK_LEARNING = "task:learning"
    # REQ-10: a critical step failed past the recovery budget (grafts
    # exhausted / cycle limit hit with incomplete critical work). The agent
    # MUST NOT silently report partial completion — it escalates to the user
    # with concrete alternative options (see agent_kernel._der_handle_step_failure).
    TASK_BLOCKED = "task:blocked"
    # REQ-15 (T26): pause/resume lifecycle state (AC4). Mirrors the ledger
    # lifecycle values persisted under REQ-9 (paused / running) so the
    # frontend can render the suspended state.
    TASK_PAUSED = "task:paused"
    TASK_RESUMED = "task:resumed"
    # REQ-15 (T26): steering acknowledgement (AC5). data carries
    # {channel, message_id, status} with status "queued" (landed in the
    # steering inbox — not silently queued behind the running turn) or
    # "considered" (consumed at a step boundary).
    STEERING_ACK = "steering:ack"

    # ── Permissions ─────────────────────────────────────────────────────
    PERMISSION_REQUEST = "permission:request"
    PERMISSION_GRANTED = "permission:granted"
    PERMISSION_DENIED = "permission:denied"

    # ── Question ────────────────────────────────────────────────────────
    QUESTION_ASK = "question:ask"
    QUESTION_ANSWERED = "question:answered"
    QUESTION_TIMEOUT = "question:timeout"

    # ── Mode change ─────────────────────────────────────────────────────
    MODE_CHANGED = "mode:changed"

    # ── Context window usage ────────────────────────────────────────────
    CONTEXT_USAGE = "context:usage"

    # ── Voice listening state ──────────────────────────────────────────
    # Carried by iris_gateway / crawler to drive the orb + ContextPill phase
    # (idle / listening / processing_conversation / processing_tool /
    # speaking / error). Bridged to the frontend so the crawler can flip the
    # phase to "processing_tool" (SEARCHING) while it crawls — otherwise the
    # UI shows "processing my STT" the whole time the agent is researching.
    LISTENING_STATE = "listening_state"

    # ── DER loop ────────────────────────────────────────────────────────
    DER_STEP = "der:step"
    DER_DONE = "der:done"
    BUDGET_EXHAUSTED = "plan:budget_exhausted"
    VALIDATION_FAILED = "plan:validation_failed"
    RECOVERY_START = "plan:recovery_start"
    TOPOLOGY_RECOVERY = "plan:topology_recovery"

    # ── Vision routing (unified-vision-routing REQ-3 AC6) ───────────────
    # Emitted when the VL fallback ladder has no candidate that fits current
    # free VRAM (or no VL model exists on disk at all). User-resolved
    # 2026-08-18: "fail loudly and alert the user through a system message"
    # — this is a DISTINCT event from BUDGET_EXHAUSTED (token budget) and
    # VALIDATION_FAILED (RC1 validation); reusing either would corrupt their
    # telemetry. Payload carries free VRAM, the smallest candidate's
    # requirement, and the full rejected ladder with a per-candidate reason.
    VISION_UNAVAILABLE = "vision:unavailable"


# ── Event payload ──────────────────────────────────────────────────────────


@dataclass
class EventPayload:
    """Every event carries these fields."""

    event: IRISStreamEvent
    data: Any = None
    turn_id: Optional[str] = None
    conversation_id: str = "default"
    session_id: str = "default"
    timestamp: float = field(default_factory=time.time)


# ── Handler type ───────────────────────────────────────────────────────────

EventHandler = Callable[[EventPayload], None]


# ── Ring buffer ────────────────────────────────────────────────────────────


class RingBuffer:
    """Bounded ring buffer for replay on late subscription."""

    def __init__(self, capacity: int = RING_BUFFER_SIZE) -> None:
        self._capacity = capacity
        self._buffer: List[EventPayload] = []
        self._lock = threading.Lock()

    def push(self, event: EventPayload) -> None:
        with self._lock:
            self._buffer.append(event)
            if len(self._buffer) > self._capacity:
                self._buffer = self._buffer[-self._capacity:]

    def replay(self, since_timestamp: float = 0.0) -> List[EventPayload]:
        with self._lock:
            if since_timestamp > 0:
                return [e for e in self._buffer if e.timestamp >= since_timestamp]
            return list(self._buffer)

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()


# ── EventBus ───────────────────────────────────────────────────────────────


class EventBus:
    """Typed pub/sub event system.

    Usage:
        bus = EventBus()

        def on_tool_call(payload):
            task_kernel.handle_tool_call(payload)

        bus.subscribe(IRISStreamEvent.TOOL_CALL, on_tool_call)
        bus.emit(IRISStreamEvent.TOOL_CALL, data={...})
        bus.unsubscribe(IRISStreamEvent.TOOL_CALL, on_tool_call)
    """

    def __init__(self) -> None:
        self._subscribers: Dict[IRISStreamEvent, Set[EventHandler]] = {}
        self._lock = threading.Lock()
        self._ring = RingBuffer()

    # ── Public API ──────────────────────────────────────────────────────

    def subscribe(self, event: IRISStreamEvent, handler: EventHandler) -> None:
        """Register a handler for an event type.

        Thread-safe.  Idempotent — same handler can only be registered
        once per event type.
        """
        with self._lock:
            if event not in self._subscribers:
                self._subscribers[event] = set()
            self._subscribers[event].add(handler)

    def unsubscribe(self, event: IRISStreamEvent, handler: EventHandler) -> None:
        """Remove a handler.  No-op if not registered."""
        with self._lock:
            if event in self._subscribers:
                self._subscribers[event].discard(handler)
                if not self._subscribers[event]:
                    del self._subscribers[event]

    def emit(
        self,
        event: IRISStreamEvent,
        data: Any = None,
        *,
        turn_id: Optional[str] = None,
        conversation_id: str = "default",
        session_id: str = "default",
    ) -> None:
        """Emit an event to all subscribers.

        Handler isolation: if one handler crashes, others still receive
        the event.  The error is logged and suppressed.

        Supports both sync and async handlers.  Async handlers are
        scheduled on the event loop (not awaited here, so the caller
        is not blocked by slow handlers).
        """
        payload = EventPayload(
            event=event,
            data=data,
            turn_id=turn_id,
            conversation_id=conversation_id,
            session_id=session_id,
        )

        # Push to ring buffer for replay
        self._ring.push(payload)

        # Deliver to subscribers
        with self._lock:
            handlers = list(self._subscribers.get(event, []))

        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    # Schedule async handler on event loop (fire-and-forget)
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(handler(payload))
                    except RuntimeError:
                        # No running loop — create a new one
                        asyncio.run_coroutine_threadsafe(
                            handler(payload), asyncio.new_event_loop()
                        )
                else:
                    handler(payload)
            except Exception as exc:
                logger.warning(
                    "[EventBus] Handler %r failed for event %s: %s",
                    handler,
                    event.value,
                    exc,
                )

    def replay(self, since_timestamp: float = 0.0) -> List[EventPayload]:
        """Replay events from the ring buffer for late subscribers."""
        return self._ring.replay(since_timestamp)

    def clear(self) -> None:
        """Clear all subscribers and ring buffer."""
        with self._lock:
            self._subscribers.clear()
            self._ring.clear()

    def subscriber_count(self, event: Optional[IRISStreamEvent] = None) -> int:
        """Count subscribers for an event (or total across all events)."""
        with self._lock:
            if event is not None:
                return len(self._subscribers.get(event, set()))
            return sum(len(h) for h in self._subscribers.values())


# ── Singleton ──────────────────────────────────────────────────────────────

_event_bus_instance: Optional[EventBus] = None
_event_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Get or create the singleton EventBus."""
    global _event_bus_instance
    if _event_bus_instance is None:
        with _event_bus_lock:
            if _event_bus_instance is None:
                _event_bus_instance = EventBus()
    return _event_bus_instance


def reset_event_bus_for_testing() -> None:
    """Reset singleton — for test isolation only."""
    global _event_bus_instance
    _event_bus_instance = None
