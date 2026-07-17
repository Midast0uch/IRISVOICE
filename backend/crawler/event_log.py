"""Resilient server-side event log for crawl research (REQ-31).

The raw WebSocket is NOT guaranteed for the desktop widget: no auto-reconnect,
frequent suspend/resume drops. To make the crawl research flow resilient we
keep a server-side, per-session, sequence-numbered event log with TTL eviction.

- Every progress event from CrawlOrchestrator is appended here (keyed by
  session_id) in addition to being pushed over the live WS/SSE channel.
- A reconnecting client replays from the last seq it saw (Last-Event-ID) and
  receives any events it missed — partial replay, not full re-crawl.
- Events older than TTL are evicted so memory stays bounded (no unbounded
  queues — quality-check requirement).

This module is transport-agnostic: both the WS handler and the SSE endpoint
read from the same log, so they never diverge.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default TTL for buffered crawl events (seconds). A reconnecting client has
# this long to replay missed events before they are evicted.
DEFAULT_TTL_S = float(300)  # 5 minutes

# Hard cap on buffered events per session (bounded memory — quality check).
MAX_EVENTS_PER_SESSION = int(2000)


@dataclass
class LoggedEvent:
    seq: int
    event: str
    payload: dict
    ts: float = field(default_factory=time.time)


class SessionEventLog:
    """Per-session, sequence-numbered, TTL-bounded event log.

    One instance is shared process-wide (singleton via get_event_log()).
    All mutating operations are guarded by a single asyncio.Lock so concurrent
    crawls in different sessions cannot interleave corruptly.
    """

    def __init__(self, ttl_s: float = DEFAULT_TTL_S) -> None:
        self._ttl_s = ttl_s
        self._lock = asyncio.Lock()
        # session_id -> {seq: LoggedEvent}
        self._store: Dict[str, Dict[int, LoggedEvent]] = {}
        self._counters: Dict[str, int] = {}
        # session_id -> True once TTL eviction has dropped events a client may
        # not have replayed. The SSE endpoint emits crawler_sync_required and the
        # client does a full snapshot fetch instead of trusting partial replay.
        self._sync_required: Dict[str, bool] = {}

    async def append(
        self, session_id: str, event: str, payload: dict
    ) -> int:
        """Append an event; return its monotonic seq number."""
        async with self._lock:
            seq = self._counters.get(session_id, 0) + 1
            self._counters[session_id] = seq
            bucket = self._store.setdefault(session_id, {})
            bucket[seq] = LoggedEvent(seq=seq, event=event, payload=payload)
            # Bounded size: drop oldest if over cap.
            if len(bucket) > MAX_EVENTS_PER_SESSION:
                oldest = min(bucket.keys())
                bucket.pop(oldest, None)
            self._evict(session_id)
            return seq

    async def replay(self, session_id: str, after_seq: int = 0) -> List[LoggedEvent]:
        """Return events with seq > after_seq, oldest first."""
        async with self._lock:
            self._evict(session_id)
            bucket = self._store.get(session_id, {})
            return [bucket[s] for s in sorted(bucket) if s > after_seq]

    async def snapshot(self, session_id: str) -> Tuple[int, List[LoggedEvent], bool]:
        """Return (last_seq, all current events, sync_required) for a full sync."""
        async with self._lock:
            self._evict(session_id)
            bucket = self._store.get(session_id, {})
            events = [bucket[s] for s in sorted(bucket)]
            last = self._counters.get(session_id, 0)
            sync = self._sync_required.get(session_id, False)
            return last, events, sync

    async def consume_sync_required(self, session_id: str) -> bool:
        """Return (and clear) the sync_required flag for a session."""
        async with self._lock:
            flag = self._sync_required.pop(session_id, False)
            return flag

    async def clear(self, session_id: str) -> None:
        async with self._lock:
            self._store.pop(session_id, None)
            self._counters.pop(session_id, None)
            self._sync_required.pop(session_id, None)

    def _evict(self, session_id: str) -> None:
        """Drop events older than TTL. Caller must hold self._lock."""
        bucket = self._store.get(session_id)
        if not bucket:
            return
        cutoff = time.time() - self._ttl_s
        expired = [s for s, ev in bucket.items() if ev.ts < cutoff]
        if expired:
            # Events were dropped before the client replayed them -> partial
            # replay is now insufficient; the client must do a full snapshot
            # sync instead (REQ-31 edge / T23).
            self._sync_required[session_id] = True
        for s in expired:
            bucket.pop(s, None)
        if not bucket:
            self._store.pop(session_id, None)


_log_instance: Optional[SessionEventLog] = None


def get_event_log() -> SessionEventLog:
    """Process-wide singleton (lazy)."""
    global _log_instance
    if _log_instance is None:
        _log_instance = SessionEventLog()
    return _log_instance
