"""
IRIS IdleTracker — single source of truth for "is anyone actively using IRIS?"

Active = a user turn is in flight (busy()) OR an HTTP request / WS message
arrived in the last N seconds.  Background workers (distillation, retention, etc.) check this before
doing expensive work so they never fire while the user is mid-conversation.

Usage:
    from backend.core.idle_tracker import get_idle_tracker

    tracker = get_idle_tracker()
    tracker.touch()          # called on every user-initiated event
    tracker.is_idle()        # True when quiet for >= idle_threshold_s
    tracker.idle_seconds()   # seconds since last activity
"""

import time
import threading
import logging
from contextlib import contextmanager

logger = logging.getLogger("backend.core.idle_tracker")

# Default idle threshold: 2 minutes of silence = "system idle"
_DEFAULT_IDLE_THRESHOLD_S = 120.0


class IdleTracker:
    """Thread-safe activity / idle tracker.

    Design:
    - touch() is O(1) and lock-free (atomic float write is safe on CPython)
    - is_idle() / idle_seconds() are read-only, also lock-free
    - Avoids asyncio — called from sync middleware, async handlers, and threads
    """

    def __init__(self, idle_threshold_s: float = _DEFAULT_IDLE_THRESHOLD_S) -> None:
        self._idle_threshold_s = idle_threshold_s
        self._last_active: float = time.monotonic()
        self._in_flight = 0
        self._lock = threading.Lock()
        logger.debug(
            f"[IdleTracker] Initialized (idle after {idle_threshold_s:.0f}s of silence)"
        )

    def touch(self) -> None:
        """Record user activity — resets the idle clock."""
        self._last_active = time.monotonic()

    @contextmanager
    def busy(self):
        """Mark a user turn in flight: never idle until it ends.

        touch() alone marks only the moment a message ARRIVES, so a turn that
        ran for minutes without new input read as idle mid-turn - measured
        2026-10-01: the whisper warm-up fired inside eval c01 and its HDD
        import held the turn's first pytest for 220 s (reply 351 s vs 145 s).
        """
        with self._lock:
            self._in_flight += 1
        self.touch()
        try:
            yield
        finally:
            with self._lock:
                self._in_flight -= 1
            self.touch()

    def idle_seconds(self) -> float:
        """Return seconds elapsed since last activity (0 while a turn runs)."""
        if self._in_flight > 0:
            return 0.0
        return time.monotonic() - self._last_active

    def is_idle(self, threshold_s: float | None = None) -> bool:
        """Return True if system has been idle for at least *threshold_s* seconds.

        Args:
            threshold_s: Override the instance threshold for this check only.
        """
        limit = threshold_s if threshold_s is not None else self._idle_threshold_s
        return self.idle_seconds() >= limit

    def idle_minutes(self) -> float:
        """Convenience alias for distillation compat."""
        return self.idle_seconds() / 60.0


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_singleton: IdleTracker | None = None
_singleton_lock = threading.Lock()


def get_idle_tracker() -> IdleTracker:
    """Return the process-wide IdleTracker singleton (created on first call)."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = IdleTracker()
    return _singleton
