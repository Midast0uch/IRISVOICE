"""Speak tool — agent-initiated TTS speech (Issue C.2).

Lets the agent proactively speak via TTS during task execution, even when the
audio pipeline isn't open.  Fire-and-forget: the tool emits an UTTERANCE event
on the EventBus and returns immediately — it never blocks the DER loop.
ConversationKernel picks up the utterance and drives TTS (or buffers it when
the audio pipeline is closed).

Design notes (per plan §3.2.2):
  * Text is bounded to MAX_TEXT_CHARS (500) so a runaway agent can't flood TTS.
  * Pending utterances are rate-limited (MAX_PENDING within a time window) so
    the 4th rapid speak is dropped instead of queuing unbounded.
  * `interrupt=True` + `priority="high"` signals ConversationKernel to halt the
    current TTS before speaking (best-effort, depends on TTS manager support).
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from typing import Any, Dict, Optional

from backend.agent.event_bus import EventBus, IRISStreamEvent, get_event_bus

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 500
MAX_PENDING = 3
_PENDING_WINDOW = 10.0  # seconds — bounds the rate of concurrent speaks


class SpeakTool:
    """Tool for agent-initiated speech via TTS."""

    def __init__(self, event_bus: Optional[EventBus] = None):
        self._bus = event_bus or get_event_bus()
        self._IRISStreamEvent = IRISStreamEvent
        self._pending: deque = deque()

    def _prune_pending(self) -> None:
        _now = time.time()
        while self._pending and _now - self._pending[0] > _PENDING_WINDOW:
            self._pending.popleft()

    def speak(
        self,
        text: str,
        priority: str = "normal",
        interrupt: bool = False,
    ) -> Dict[str, Any]:
        """Emit a `speak` utterance for TTS. Fire-and-forget.

        Args:
            text: What to speak (truncated to MAX_TEXT_CHARS).
            priority: "normal" | "high" | "low" (default "normal").
            interrupt: If True and priority is "high", halts current TTS
                before speaking (best-effort).

        Returns a status dict.  Never raises — speech is best-effort.
        """
        if not text or not isinstance(text, str):
            return {"status": "error", "reason": "text (str) is required"}
        text = text[:MAX_TEXT_CHARS]

        self._prune_pending()
        if len(self._pending) >= MAX_PENDING:
            logger.warning("[SpeakTool] rate limited (max %d pending)", MAX_PENDING)
            return {"status": "rate_limited"}

        uid = f"spk_{uuid.uuid4().hex[:8]}"
        self._pending.append(time.time())
        try:
            self._bus.emit(
                self._IRISStreamEvent.UTTERANCE_START,
                data={
                    "text": text,
                    "priority": priority,
                    "interrupt": bool(interrupt),
                    "utterance_id": uid,
                },
            )
            self._bus.emit(
                self._IRISStreamEvent.UTTERANCE_DONE,
                data={
                    "text": text,
                    "priority": priority,
                    "interrupt": bool(interrupt),
                    "utterance_id": uid,
                },
            )
        except Exception as exc:
            logger.warning("[SpeakTool] emit failed: %s", exc)
            return {"status": "error", "reason": str(exc)}
        return {"status": "ok", "utterance_id": uid, "spoken": text}


# ── Singleton ──────────────────────────────────────────────────────────────

_tool_instance: Optional[SpeakTool] = None


def get_speak_tool() -> SpeakTool:
    global _tool_instance
    if _tool_instance is None:
        _tool_instance = SpeakTool()
    return _tool_instance


def reset_speak_tool_for_testing() -> None:
    """Reset the singleton — used by tests to get a fresh instance."""
    global _tool_instance
    _tool_instance = None
