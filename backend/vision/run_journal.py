"""Bounded, run-scoped JSONL event journal for the vision path (REQ-17 AC2).

The audit found the vision path had NO machine-readable record of what it
emitted: 25 `scripts/validate_*` harnesses exist and a frame recorder exists
(`validate_websearch_trajectory.py`), but those traces contain ZERO vision
events. This module is the missing journal — ONE run-scoped JSON Lines file an
agent can diff against the contract.

Contract (REQ-17 AC2):
  - ONE journal per run, JSON Lines, the run id recorded FIRST.
  - Every emitted vision / frame / grant event is appended.
  - BOUNDED (max lines AND max bytes) with an explicit truncation marker, so a
    long session cannot grow without limit (REQ-17 edge).
  - Off the critical path: a write failure NEVER fails a run (REQ-17 edge). A
    read-only disk degrades to "journal unavailable", not a broken run.

The journal deliberately does NOT duplicate the capture/proxy surface: it
records EVENT ENVELOPES (type + fields), never frame BYTES or page HTML.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# REQ-17 edge: bounded by BOTH a line cap and a byte cap.
_MAX_LINES = int(os.environ.get("IRIS_VISION_JOURNAL_MAX_LINES", "5000"))
_MAX_BYTES = int(os.environ.get("IRIS_VISION_JOURNAL_MAX_BYTES", str(2 * 1024 * 1024)))

#: Fields that must NEVER enter the journal (REQ-14 AC4: an ephemeral typed
#: value; REQ-16 AC2: frame bytes are not journaled here).
_FORBIDDEN_KEYS = frozenset({"text", "bytes", "html", "value"})


class RunJournal:
    """A bounded JSONL writer for one run (REQ-17 AC2). Never raises."""

    def __init__(
        self,
        path: str,
        run_id: str,
        *,
        max_lines: int = _MAX_LINES,
        max_bytes: int = _MAX_BYTES,
    ) -> None:
        self._path = path
        self._run_id = run_id
        self._max_lines = max(1, int(max_lines))
        self._max_bytes = max(256, int(max_bytes))
        self._lines = 0
        self._bytes = 0
        self._truncated = False
        self._lock = threading.Lock()
        self._available = False
        self._fh = None

    # ── lifecycle ──────────────────────────────────────────────────────────

    def open(self) -> bool:
        """Open the journal and write the run-id header (REQ-17 AC2).

        Returns True when writable, False when unavailable (read-only disk) —
        the caller proceeds either way (REQ-17 edge).
        """
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            self._fh = open(self._path, "w", encoding="utf-8")
            self._available = True
            # The run id is recorded FIRST so a reader knows the scope.
            self._write_raw({"kind": "run_start", "run_id": self._run_id})
            return True
        except Exception as exc:  # noqa: BLE001 — a verification aid never fails a run
            logger.info("[run_journal] unavailable (%s) — run proceeds", exc)
            self._available = False
            return False

    def close(self) -> None:
        try:
            if self._fh is not None:
                self._fh.flush()
                self._fh.close()
        except Exception:  # noqa: BLE001
            pass
        self._fh = None

    @property
    def available(self) -> bool:
        return self._available

    @property
    def truncated(self) -> bool:
        return self._truncated

    # ── writing ────────────────────────────────────────────────────────────

    def record(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        """Append one event. Bounded + best-effort; never raises.

        The payload is NESTED under ``payload`` so a producer field named
        ``kind`` (the vision action kind) cannot collide with the journal's own
        ``kind`` envelope key.
        """
        if not self._available or self._fh is None:
            return
        safe = _scrub(payload or {})
        self._write_raw({"kind": "event", "event": event_type, "payload": safe})

    def _write_raw(self, obj: Dict[str, Any]) -> None:
        with self._lock:
            if self._fh is None:
                return
            if self._truncated:
                return
            if self._lines >= self._max_lines:
                self._mark_truncated("max_lines")
                return
            try:
                line = json.dumps(obj, default=str)
            except Exception:  # noqa: BLE001
                return
            size = len(line.encode("utf-8")) + 1
            if self._bytes + size > self._max_bytes:
                self._mark_truncated("max_bytes")
                return
            try:
                self._fh.write(line + "\n")
                self._lines += 1
                self._bytes += size
            except Exception as exc:  # noqa: BLE001 — a write failure never fails a run
                logger.debug("[run_journal] write failed: %s", exc)

    def _mark_truncated(self, reason: str) -> None:
        """Write the explicit truncation marker, then stop (REQ-17 edge)."""
        self._truncated = True
        try:
            marker = json.dumps({"kind": "truncated", "reason": reason,
                                 "run_id": self._run_id})
            self._fh.write(marker + "\n")
            self._fh.flush()
        except Exception:  # noqa: BLE001
            pass


def _scrub(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop forbidden keys (ephemeral values, frame bytes, page HTML).

    REQ-14 AC4 / REQ-16 AC2: the journal records event ENVELOPES, never a typed
    value, frame bytes, or page HTML. A nested dict is scrubbed recursively.
    """
    out: Dict[str, Any] = {}
    for k, v in payload.items():
        if k in _FORBIDDEN_KEYS:
            continue
        if isinstance(v, dict):
            out[k] = _scrub(v)
        else:
            out[k] = v
    return out


__all__ = ["RunJournal"]
