"""REQ-18 (T31): the correlated per-task trace.

One bounded, in-memory trace per task (keyed by task_id == conversation_id
or session_id) that collects the six REQ-18 signals at their EXISTING
instrumentation points — no new parallel reporting channel:

  AC1 verify     — scorer tag ("semantic"|"fallback") + score for every
                   verified label produced (T19).
  AC2 synthesis  — whether synthesis ran and on which path: success /
                   failure / deterministic_success / deterministic_failure
                   (T20).
  AC3 revision   — every plan revision with its origin: initial /
                   sub_loop_split (REQ-4/REQ-13) / user_steering (REQ-15)
                   (T23).
  AC4 steering   — every steering message received, whether it was
                   acknowledged, and the step boundary at which it was
                   applied (T25/T26).
  AC5 navigation — every browser navigation with target surface
                   (in-app | external) + crawl job_id + HAR path (T27).

Bounded + redacted + off the critical path (REQ-8 discipline):
  - per-task entry cap (older entries evicted) -> no unbounded growth
  - every string field truncated -> redacted
  - ``record()`` never raises and never blocks the response path
  - thread-safe (DER runs under a concurrent loop + gather)
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

_MAX_ENTRIES_PER_TASK = 500
_MAX_STRING = 300
_MAX_TASKS = 200


class DerTaskTrace:
    """Bounded per-task trace. Append-only; never raises."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self._lock = threading.Lock()
        self._entries: List[Dict[str, Any]] = []
        self._created_at = time.time()

    def record(self, signal: str, **fields: Any) -> None:
        """Append one correlated trace entry (bounded + redacted)."""
        try:
            entry: Dict[str, Any] = {"signal": signal, "ts": time.time()}
            for k, v in fields.items():
                entry[k] = self._redact(v)
            with self._lock:
                self._entries.append(entry)
                if len(self._entries) > _MAX_ENTRIES_PER_TASK:
                    # Bounded: evict oldest, keep the most recent slice.
                    del self._entries[: len(self._entries) - _MAX_ENTRIES_PER_TASK]
        except Exception:
            pass  # never block the critical path

    @staticmethod
    def _redact(value: Any) -> Any:
        if isinstance(value, str) and len(value) > _MAX_STRING:
            return value[:_MAX_STRING] + "…[truncated]"
        return value

    def entries(self, signal: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            if signal is None:
                return list(self._entries)
            return [e for e in self._entries if e.get("signal") == signal]

    def has_signal(self, signal: str) -> bool:
        return any(e.get("signal") == signal for e in self.entries())

    def snapshot(self) -> Dict[str, Any]:
        return {"task_id": self.task_id, "entries": self.entries()}

    def count(self) -> int:
        return len(self.entries())


# ── process-wide registry (bounded) ────────────────────────────────────────
_registry: Dict[str, DerTaskTrace] = {}
_registry_lock = threading.Lock()


def get_der_trace(task_id: str) -> DerTaskTrace:
    """Get (creating if needed) the per-task trace. Bounded registry."""
    with _registry_lock:
        trace = _registry.get(task_id)
        if trace is None:
            trace = DerTaskTrace(task_id)
            _registry[task_id] = trace
            if len(_registry) > _MAX_TASKS:
                # Bounded: evict oldest-created traces beyond the cap.
                oldest = sorted(
                    _registry.values(), key=lambda t: t._created_at
                )
                for stale in oldest[: len(_registry) - _MAX_TASKS]:
                    _registry.pop(stale.task_id, None)
        return trace


def all_traces() -> List[DerTaskTrace]:
    with _registry_lock:
        return list(_registry.values())


def clear_traces() -> None:
    """Test hook: drop all traces (isolates contract tests)."""
    with _registry_lock:
        _registry.clear()
