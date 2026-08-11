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
# T15 (REQ-14 AC3): a voice answer resolves the question only at/above this
# fuzzy-match confidence. Below it -> AC4 (ask to repeat, never guess).
_VOICE_RESOLVE_THRESHOLD = 0.7


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

    # ── T13 (REQ-13): non-blocking mode + first-wins funnel ────────────────

    def ask_non_blocking(
        self,
        text: str,
        options: Optional[List[str]] = None,
        allow_other: bool = False,
        timeout_seconds: int = ASK_USER_QUESTION_TIMEOUT,
        turn_id: Optional[str] = None,
        run_id: Optional[str] = None,
        parked_url: Optional[str] = None,
        wall_kind: str = "unknown",
    ) -> Question:
        """Ask and return immediately with a handle (REQ-13 AC1).

        Unlike `ask()` + `wait_for_answer()`, the caller is NOT expected to
        block. If `parked_url` is given, the source is parked in the
        ParkedSourceRegistry (REQ-13 AC2) so it can be resumed when the answer
        arrives (AC3) — one question per domain per run (AC6).
        """
        question = self.ask(
            text=text, options=options, allow_other=allow_other,
            timeout_seconds=timeout_seconds, turn_id=turn_id,
        )
        if parked_url:
            from urllib.parse import urlparse

            domain = urlparse(parked_url).netloc or parked_url
            registry = get_parked_source_registry()
            registry.park(
                run_id=run_id or "",
                url=parked_url,
                wall_kind=wall_kind,
                question_id=question.question_id,
            )
            logger.info(
                "[AskUser] Parked source url=%s domain=%s qid=%s run=%s (REQ-13)",
                parked_url, domain, question.question_id, run_id,
            )
        return question

    def resolve_answer(self, question_id: str, answer: str) -> Optional[Question]:
        """SINGLE resolution funnel (REQ-14 AC5, CT-4 first-wins).

        Card click and voice BOTH route through here. First caller wins:
        `receive_answer` pops the question from `_pending`, so a second answer
        (e.g. voice after click) is a no-op. A parked source linked to the
        question is resumed (REQ-13 AC3) so the research run can pick it up.
        """
        question = self.receive_answer(question_id, answer)
        if question is not None:
            registry = get_parked_source_registry()
            source = registry.resume(question_id, answer=answer)
            if source is not None:
                logger.info(
                    "[AskUser] Resumed parked source url=%s (REQ-13 AC3)",
                    source.url,
                )
        return question

    # ── T15 (REQ-14): answer a question card by voice ─────────────────────

    def pending_for_session(self, session_id: str) -> Optional[Question]:
        """Most-recent pending question for a session (REQ-14 edge:
        two questions pending -> most recent wins; the other stays pending).

        Questions are linked to a session via ``turn_id == session_id`` (set by
        tool_bridge when it asks). Returns the newest, or None.
        """
        candidates = [
            q for q in self._pending.values()
            if q.turn_id == session_id and q.status == "pending"
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda q: q.created_at)

    def resolve_via_voice(self, transcript: str, session_id: str) -> dict:
        """Route a completed voice transcript as a candidate answer to a
        pending question (REQ-14 AC1-AC6).

        Returns:
          {"handled": False}                 -> no pending question; the caller
                                                routes the transcript to the
                                                normal command path (AC6)
          {"handled": True, "resolved": opt} -> matched at/above threshold and
                                                resolved via the single funnel
                                                (AC3, first-wins)
          {"handled": False, "repeat": True} -> below threshold; question stays
                                                pending, user asked to repeat
                                                (AC4); transcript still falls
                                                through to the normal path
        """
        question = self.pending_for_session(session_id)
        if question is None:
            return {"handled": False}
        # AC2: match against the question's options with fuzzy_match_answer.
        option, confidence, _exact = fuzzy_match_answer(transcript, question.options)
        if option is not None and confidence >= _VOICE_RESOLVE_THRESHOLD:
            resolved = self.resolve_answer(question.question_id, option)
            if resolved is not None:
                logger.info(
                    "[AskUser] Voice answered qid=%s -> %r (conf=%.2f, REQ-14 AC3)",
                    question.question_id, option, confidence,
                )
                return {"handled": True, "resolved": option}
        # AC4: below threshold -> leave pending, ask to repeat, don't guess.
        self.send_filler(question.question_id)
        logger.info(
            "[AskUser] Voice below threshold qid=%s conf=%.2f -> repeat (REQ-14 AC4)",
            question.question_id, confidence,
        )
        return {"handled": False, "repeat": True}

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


# ── T13 (REQ-13): parked sources + non-blocking ask ────────────────────────


@dataclass
class ParkedSource:
    """A source the research run could not pass, parked for a human answer.

    One question per domain per run (REQ-13 AC6): the registry dedupes on
    (run_id, domain) so a repeated blocked source does not re-ask.
    """

    url: str
    domain: str
    run_id: str
    question_id: str
    wall_kind: str = "unknown"  # captcha | login | paywall | unknown
    status: str = "parked"      # parked | resumed | timed_out
    answer: Optional[str] = None
    parked_at: float = field(default_factory=time.time)
    resumed_at: Optional[float] = None


class ParkedSourceRegistry:
    """Per-run registry of sources parked behind walls (REQ-13 AC2/AC6).

    The registry is the record that lets AC3 resume a parked source WITHOUT
    restarting the research run: `resume()` returns the source the run can
    re-dispatch, and `timed_out()` is logged (REQ-16) when no answer arrived.
    """

    def __init__(self) -> None:
        self._parked: Dict[str, ParkedSource] = {}  # question_id -> source
        self._run_domain: Dict[str, str] = {}       # "run_id|domain" -> question_id

    @staticmethod
    def _key(run_id: str, domain: str) -> str:
        return f"{run_id}|{domain}"

    def park(self, run_id: str, url: str, wall_kind: str = "unknown", question_id: str = "") -> Optional[ParkedSource]:
        """Register a parked source. Returns None if (run_id, domain) already
        has a pending question (REQ-13 AC6 — no duplicate questions)."""
        from urllib.parse import urlparse

        domain = urlparse(url).netloc or url
        key = self._key(run_id, domain)
        existing_qid = self._run_domain.get(key)
        if existing_qid and existing_qid in self._parked:
            return None  # already asked about this domain this run
        source = ParkedSource(
            url=url, domain=domain, run_id=run_id,
            question_id=question_id or f"parked_{uuid.uuid4().hex[:8]}",
            wall_kind=wall_kind,
        )
        self._parked[source.question_id] = source
        self._run_domain[key] = source.question_id
        return source

    def get(self, question_id: str) -> Optional[ParkedSource]:
        return self._parked.get(question_id)

    def resume(self, question_id: str, answer: Optional[str] = None) -> Optional[ParkedSource]:
        """Mark the parked source resumed (REQ-13 AC3). Returns it for
        re-dispatch, or None if it was never parked / already resolved."""
        source = self._parked.pop(question_id, None)
        if source is None:
            return None
        source.status = "resumed"
        source.answer = answer
        source.resumed_at = time.time()
        self._run_domain.pop(self._key(source.run_id, source.domain), None)
        return source

    def mark_timed_out(self, question_id: str) -> Optional[ParkedSource]:
        source = self._parked.pop(question_id, None)
        if source is None:
            return None
        source.status = "timed_out"
        self._run_domain.pop(self._key(source.run_id, source.domain), None)
        return source

    def pending(self, run_id: Optional[str] = None) -> List[ParkedSource]:
        if run_id is None:
            return list(self._parked.values())
        return [s for s in self._parked.values() if s.run_id == run_id]

    def clear(self) -> None:
        self._parked.clear()
        self._run_domain.clear()


_parked_registry: Optional[ParkedSourceRegistry] = None


def get_parked_source_registry() -> ParkedSourceRegistry:
    global _parked_registry
    if _parked_registry is None:
        _parked_registry = ParkedSourceRegistry()
    return _parked_registry


def reset_parked_source_registry_for_testing() -> None:
    global _parked_registry
    _parked_registry = None
