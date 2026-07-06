"""AskUserQuestion tool — multiple-choice questions mid-task.

The agent can ask the user questions during task execution.
Two flows:
  1. Voice mode: question spoken via TTS, user speaks answer, fuzzy match
  2. Chat mode: QuestionCard rendered in chat, user clicks answer

Fuzzy matching confidence tiers:
  >= 0.7: Accept directly
  0.4 - 0.7: Confirm with user
  < 0.4: Re-state options

Error handling: try/except pattern — never blocks the DER loop.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.agent.event_bus import (
    EventBus,
    EventPayload,
    IRISStreamEvent,
    get_event_bus,
)

logger = logging.getLogger(__name__)

ASK_USER_QUESTION_TIMEOUT = 120  # seconds
FILLER_INTERVAL = 30  # seconds between filler re-prompts
MAX_FILLERS = 2


@dataclass
class Question:
    """A pending AskUserQuestion."""
    question_id: str = field(default_factory=lambda: f"q_{uuid.uuid4().hex[:8]}")
    text: str = ""
    options: List[str] = field(default_factory=list)
    allow_other: bool = False
    created_at: float = field(default_factory=time.time)
    timeout_seconds: int = ASK_USER_QUESTION_TIMEOUT
    status: str = "pending"  # pending | answered | timed_out
    answer: Optional[str] = None
    filler_count: int = 0
    turn_id: Optional[str] = None


class AskUserTool:
    """Tool for asking the user questions mid-task.

    The agent calls this tool when it needs user input.
    The tool emits QUESTION_ASK events via EventBus,
    waits for a response (with timeout + fillers),
    and returns the answer.
    """

    def __init__(self, event_bus: Optional[EventBus] = None):
        self._bus = event_bus or get_event_bus()
        self._pending: Dict[str, Question] = {}
        self._IRISStreamEvent = IRISStreamEvent

    def ask(
        self,
        text: str,
        options: Optional[List[str]] = None,
        allow_other: bool = False,
        timeout_seconds: int = ASK_USER_QUESTION_TIMEOUT,
        turn_id: Optional[str] = None,
    ) -> Question:
        """Ask a question and return immediately (non-blocking).

        The caller must use wait_for_answer() to block.
        """
        question = Question(
            text=text,
            options=options or [],
            allow_other=allow_other,
            timeout_seconds=timeout_seconds,
            turn_id=turn_id,
        )
        self._pending[question.question_id] = question

        self._bus.emit(
            self._IRISStreamEvent.QUESTION_ASK,
            data={
                "question_id": question.question_id,
                "text": text,
                "options": options or [],
                "allow_other": allow_other,
                "timeout_seconds": timeout_seconds,
            },
            turn_id=turn_id,
        )
        logger.info(
            "[AskUser] Asked: %s (options=%d, timeout=%ds)",
            text[:60], len(options or []), timeout_seconds,
        )
        return question

    def receive_answer(self, question_id: str, answer: str) -> Optional[Question]:
        """Receive an answer from the frontend or voice pipeline.

        Returns the Question (with status updated) or None if not found.
        """
        question = self._pending.pop(question_id, None)
        if not question:
            logger.warning("[AskUser] Answer for unknown question: %s", question_id)
            return None
        question.status = "answered"
        question.answer = answer
        self._bus.emit(
            self._IRISStreamEvent.QUESTION_ANSWERED,
            data={
                "question_id": question_id,
                "answer": answer,
                "text": question.text,
            },
            turn_id=question.turn_id,
        )
        return question

    def send_filler(self, question_id: str) -> Optional[str]:
        """Send a filler prompt for an unanswered question.

        Returns the filler text or None if max fillers reached.
        """
        question = self._pending.get(question_id)
        if not question or question.filler_count >= MAX_FILLERS:
            return None
        question.filler_count += 1
        fillers = [
            "I'm still waiting for your response...",
            "Just checking in — still need your input.",
        ]
        filler = fillers[(question.filler_count - 1) % len(fillers)]
        self._bus.emit(
            self._IRISStreamEvent.UTTERANCE_START,
            data={"text": filler, "is_filler": True},
            turn_id=question.turn_id,
        )
        return filler

    def wait_for_answer(
        self,
        question: Question,
        poll_interval: float = 0.1,
        filler_interval: float = FILLER_INTERVAL,
    ) -> Question:
        """Block until the question is answered or times out.

        Sends filler prompts at intervals.
        """
        start = time.time()
        last_filler = start
        while time.time() - start < question.timeout_seconds:
            if question.question_id not in self._pending:
                return question  # answered
            # Filler logic
            if time.time() - last_filler >= filler_interval:
                self.send_filler(question.question_id)
                last_filler = time.time()
            time.sleep(poll_interval)

        # Timed out
        self._pending.pop(question.question_id, None)
        question.status = "timed_out"
        self._bus.emit(
            self._IRISStreamEvent.QUESTION_TIMEOUT,
            data={"question_id": question.question_id},
            turn_id=question.turn_id,
        )
        return question


# ── Fuzzy matching ─────────────────────────────────────────────────────────


def fuzzy_match_answer(answer: str, options: List[str]) -> tuple:
    """Fuzzy match a user answer against options.

    Uses simple substring + Levenshtein-like heuristics.
    Returns (best_option: str | None, confidence: float, is_exact: bool).
    """
    answer_lower = answer.lower().strip()

    # 1. Exact match
    for opt in options:
        if opt.lower().strip() == answer_lower:
            return (opt, 1.0, True)

    # 2. Numbered choice: "1", "option 1", etc.
    import re
    num_match = re.search(r"(\d+)", answer_lower)
    if num_match:
        idx = int(num_match.group(1)) - 1
        if 0 <= idx < len(options):
            return (options[idx], 0.9, False)

    # 3. Substring match
    for opt in options:
        opt_lower = opt.lower().strip()
        if opt_lower in answer_lower or answer_lower in opt_lower:
            return (opt, 0.8, False)

    # 4. Word overlap
    answer_words = set(answer_lower.split())
    best_word_overlap = 0
    best_option = None
    for opt in options:
        opt_words = set(opt.lower().split())
        if len(answer_words) > 0 and len(opt_words) > 0:
            overlap = len(answer_words & opt_words) / max(len(answer_words), len(opt_words))
            if overlap > best_word_overlap:
                best_word_overlap = overlap
                best_option = opt

    if best_word_overlap >= 0.7:
        return (best_option, best_word_overlap, False)

    return (None, 0.0, False)


# ── Singleton ──────────────────────────────────────────────────────────────

_tool_instance: Optional[AskUserTool] = None


def get_ask_user_tool() -> AskUserTool:
    global _tool_instance
    if _tool_instance is None:
        _tool_instance = AskUserTool()
    return _tool_instance


def reset_ask_user_tool_for_testing() -> None:
    global _tool_instance
    _tool_instance = None
