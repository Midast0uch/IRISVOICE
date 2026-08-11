"""REQ-15 (T25/T26): mid-task steering channel — three distinct control
channels plus the resume lifecycle channel.

steer / pause / stop / resume are pushed here from the WebSocket layer
(``backend/main.py``) so they do NOT queue behind ``_session_message_locks``
/ ``handle_message``. The RUNNING DER loop consumes them at its next step
boundary via ``AgentKernel._der_check_steering`` (REQ-15 AC1: available at the
next step boundary, never mid-step), and suspends via
``AgentKernel._der_suspend_task`` (AC4) when a pause lands.

ACK protocol (AC5):
  - on push, the WS layer emits ``steering:ack`` status="queued" — the
    message LANDED (it is in the inbox, not silently queued behind the
    running turn);
  - while a record stays unacknowledged (unconsumed) past
    ``RESEND_AFTER_SECONDS``, ``resend_stale_acks`` re-emits the queued ack
    (the unacknowledged message is re-sent);
  - when the boundary consumer drains a record, it emits ``steering:ack``
    status="considered" — the message was applied/dropped.

AC6 (channel independence) is structural here: each record carries its own
``channel`` and the consumer latches stop/pause BEFORE applying any (potentially
slow) steering revision, so a stop is never delayed behind steering work.

Thread-safety: the inbox is a per-session deque guarded by a lock. The push
side runs in the WS reader task; the drain side runs in the DER loop thread.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

# REQ-15 AC6: three distinct, independently observable channels.
CHANNEL_STEER = "steer"
CHANNEL_PAUSE = "pause"
CHANNEL_STOP = "stop"
STEERING_CHANNELS = frozenset({CHANNEL_STEER, CHANNEL_PAUSE, CHANNEL_STOP})

# REQ-15 AC4: the fourth, lifecycle-only channel — resume is not a steering
# channel and is never conflated with steer/pause/stop.
CHANNEL_RESUME = "resume"

# AC5: a queued steering record whose ack has not been superseded by
# "considered" within this window is re-sent (queued ack re-emitted).
RESEND_AFTER_SECONDS = 15.0


@dataclass
class SteeringRecord:
    """One control message waiting to be consumed at the next step boundary."""

    channel: str
    session_id: str
    text: str = ""
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    queued_at: float = field(default_factory=time.time)
    acknowledged: bool = False


class SteeringInbox:
    """Per-session queue of steering/pause/stop/resume records (REQ-15)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: Dict[str, Deque[SteeringRecord]] = {}

    def push(
        self,
        channel: str,
        session_id: str,
        text: str = "",
        message_id: Optional[str] = None,
    ) -> SteeringRecord:
        """Queue a control record for the session. Never blocks the caller."""
        record = SteeringRecord(
            channel=channel,
            session_id=session_id,
            text=text,
            message_id=message_id or uuid.uuid4().hex,
        )
        with self._lock:
            self._records.setdefault(session_id, deque()).append(record)
        return record

    def drain(self, session_id: str) -> List[SteeringRecord]:
        """Atomically remove and return every record queued for the session.

        The ONLY consumer at a step boundary is
        ``AgentKernel._der_check_steering`` — this is what makes AC1
        ("never mid-step") hold. Draining marks the records acknowledged.
        """
        with self._lock:
            q = self._records.pop(session_id, None)
        if not q:
            return []
        records = list(q)
        for rec in records:
            rec.acknowledged = True
        return records

    def pending(self, session_id: str) -> int:
        """Number of records still waiting for the next boundary (AC1)."""
        with self._lock:
            return len(self._records.get(session_id, ()))

    def pending_channel(self, session_id: str, channel: str) -> bool:
        """True if a record of `channel` is queued (used by the suspend
        loop to wait for resume/stop without consuming steer records)."""
        with self._lock:
            q = self._records.get(session_id)
            if not q:
                return False
            return any(r.channel == channel for r in q)

    def drain_channel(self, session_id: str, channel: str) -> List[SteeringRecord]:
        """Remove and return ONLY records of `channel`, leaving every other
        channel queued. Used by the suspend loop so steer records arriving
        while paused are held for the post-resume boundary."""
        with self._lock:
            q = self._records.get(session_id)
            if not q:
                return []
            taken = [r for r in q if r.channel == channel]
            kept = deque(r for r in q if r.channel != channel)
            if kept:
                self._records[session_id] = kept
            else:
                self._records.pop(session_id, None)
        for rec in taken:
            rec.acknowledged = True
        return taken

    def pending_stale(
        self, session_id: str, max_age_seconds: float
    ) -> List[SteeringRecord]:
        """Records still queued (unacknowledged) past `max_age_seconds` —
        the AC5 re-send candidates. Does not consume them."""
        _cutoff = time.time() - max_age_seconds
        with self._lock:
            q = self._records.get(session_id)
            if not q:
                return []
            return [r for r in q if r.queued_at < _cutoff]

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


_inbox: Optional[SteeringInbox] = None
_inbox_lock = threading.Lock()


def get_steering_inbox() -> SteeringInbox:
    """Module singleton — the ONE inbox the WS layer pushes into and the DER
    loop drains from."""
    global _inbox
    if _inbox is None:
        with _inbox_lock:
            if _inbox is None:
                _inbox = SteeringInbox()
    return _inbox


def emit_queued_ack(rec: SteeringRecord) -> None:
    """REQ-15 AC5: visible acknowledgement that the message LANDED — it is
    in the steering inbox, not silently queued behind the running turn."""
    try:
        from backend.agent.event_bus import get_event_bus, IRISStreamEvent

        get_event_bus().emit(
            IRISStreamEvent.STEERING_ACK,
            data={
                "channel": rec.channel,
                "message_id": rec.message_id,
                "status": "queued",
            },
            session_id=rec.session_id,
        )
    except Exception:
        pass  # ack is best-effort — never break the message loop


def resend_stale_acks(
    session_id: str, max_age_seconds: float = RESEND_AFTER_SECONDS
) -> List[SteeringRecord]:
    """REQ-15 AC5: an unacknowledged steering message SHALL be re-sent.

    Re-emits the "queued" ack for every record still queued past the resend
    threshold (the user is reminded the message is pending). Returns the
    re-sent records so callers can log/observe them. Called by the WS layer
    whenever it touches the session (a frame arrives or a record is pushed).
    """
    records = get_steering_inbox().pending_stale(session_id, max_age_seconds)
    for rec in records:
        emit_queued_ack(rec)
    return records
