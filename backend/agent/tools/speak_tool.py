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
        conversation_id: Optional[str] = None,
        turn_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Emit a `speak` utterance for TTS. Fire-and-forget.

        Args:
            text: What to speak (truncated to MAX_TEXT_CHARS).
            priority: "normal" | "high" | "low" (default "normal").
            interrupt: If True and priority is "high", halts current TTS
                before speaking (best-effort).
            conversation_id: thread the utterance belongs to. If omitted,
                resolved from the active AgentKernel so the TTS log can be
                correlated to a conversation thread during live testing.
            turn_id: turn the utterance belongs to. If omitted, resolved
                from the active AgentKernel.

        Returns a status dict. Never raises — speech is best-effort.
        """
        if not text or not isinstance(text, str):
            return {"status": "error", "reason": "text (str) is required"}
        text = text[:MAX_TEXT_CHARS]

        # Resolve thread/turn for correlation when not explicitly passed.
        # NOTE: look up the EXISTING kernel instance only — never call
        # get_agent_kernel() with an empty/id string, as that would CREATE
        # a new heavy kernel (memory wiring) as a side effect of a log call.
        if conversation_id is None or turn_id is None:
            try:
                from backend.agent.agent_kernel import _agent_kernel_instances

                _active = None
                if conversation_id and conversation_id in _agent_kernel_instances:
                    _active = _agent_kernel_instances[conversation_id]
                elif _agent_kernel_instances:
                    # Fall back to the most recently created instance.
                    _active = next(
                        reversed(_agent_kernel_instances.values())
                    )
                if _active is not None:
                    conversation_id = conversation_id or getattr(
                        _active, "conversation_id", None
                    )
                    turn_id = turn_id or getattr(
                        _active, "_current_turn_id", None
                    )
            except Exception:
                pass

        self._prune_pending()
        if len(self._pending) >= MAX_PENDING:
            logger.warning("[SpeakTool] rate limited (max %d pending)", MAX_PENDING)
            return {"status": "rate_limited"}

        uid = f"spk_{uuid.uuid4().hex[:8]}"
        self._pending.append(time.time())
        # Structured correlation log: intent (what the agent decided to say,
        # for which thread/turn, at what wall-clock time). Pairs with the
        # TTSManager playback log so screenshots <-> thread <-> TTS <-> text
        # can be reconstructed during manual live testing.
        logger.info(
            "[SpeakTool] SPEAK intent ts=%.3f conv=%s turn=%s prio=%s uid=%s text=%r",
            time.time(),
            conversation_id,
            turn_id,
            priority,
            uid,
            text[:80],
        )
        try:
            self._bus.emit(
                self._IRISStreamEvent.UTTERANCE_START,
                data={
                    "text": text,
                    "priority": priority,
                    "interrupt": bool(interrupt),
                    "utterance_id": uid,
                    "conversation_id": conversation_id,
                    "turn_id": turn_id,
                },
            )
            self._bus.emit(
                self._IRISStreamEvent.UTTERANCE_DONE,
                data={
                    "text": text,
                    "priority": priority,
                    "interrupt": bool(interrupt),
                    "utterance_id": uid,
                    "conversation_id": conversation_id,
                    "turn_id": turn_id,
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
