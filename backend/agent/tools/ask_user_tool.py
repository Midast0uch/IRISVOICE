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
from typing import Any, Dict, List, Optional, Union

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
    """A pending AskUserQuestion.

    T3 (REQ-5): `set_id`, `header` and `multi_select` are additive fields
    that only ever get non-default values via `ask_set()`. A question
    created through the original `ask()` keeps `set_id=None`,
    `header=""`, `multi_select=False` — no behaviour change for existing
    callers.
    """
    question_id: str = field(default_factory=lambda: f"q_{uuid.uuid4().hex[:8]}")
    text: str = ""
    options: List[str] = field(default_factory=list)
    allow_other: bool = False
    created_at: float = field(default_factory=time.time)
    timeout_seconds: int = ASK_USER_QUESTION_TIMEOUT
    status: str = "pending"  # pending | answered | timed_out
    answer: Optional[Any] = None  # str, or list[str] for multi_select (REQ-5 AC3)
    filler_count: int = 0
    turn_id: Optional[str] = None
    set_id: Optional[str] = None  # REQ-5: the QuestionSet this belongs to, if any
    header: str = ""              # REQ-5 AC4: per-question label
    multi_select: bool = False    # REQ-5 AC3


@dataclass
class QuestionSpec:
    """One question's spec passed into `ask_set()` (REQ-5 AC1/AC2/AC3/AC4).

    Mirrors `ask()`'s parameters, minus `timeout_seconds`/`turn_id` which
    are shared across the whole set.
    """
    text: str = ""
    options: List[str] = field(default_factory=list)
    allow_other: bool = False
    multi_select: bool = False
    header: str = ""


@dataclass
class QuestionSet:
    """A set of N questions asked together (REQ-5 AC1).

    Each `Question` in `questions` has its OWN `question_id` and resolves
    independently through `resolve_answer()` — the same single funnel
    `ask()`'s question uses (REQ-6 edge case: "each question resolves
    independently through the same funnel"). There is no set-level
    resolution call.
    """
    set_id: str = field(default_factory=lambda: f"qs_{uuid.uuid4().hex[:8]}")
    questions: List[Question] = field(default_factory=list)
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
        conversation_id: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> Question:
        """Ask a question and return immediately (non-blocking).

        The caller must use wait_for_answer() to block.

        Session 247: ``conversation_id`` and ``context`` are additive —
        callers (e.g. the web format escalation) pass them so the question
        card can associate with its conversation and carry structured
        provenance. They ride the QUESTION_ASK payload; unknown-kwarg
        TypeErrors here silently killed whole escalations (live: "web format
        escalation failed").
        """
        question = Question(
            text=text,
            options=options or [],
            allow_other=allow_other,
            timeout_seconds=timeout_seconds,
            turn_id=turn_id,
        )
        if conversation_id:
            question.conversation_id = conversation_id
        if context:
            question.context = context
        self._pending[question.question_id] = question

        self._bus.emit(
            self._IRISStreamEvent.QUESTION_ASK,
            data={
                "question_id": question.question_id,
                "text": text,
                "options": options or [],
                "allow_other": allow_other,
                "timeout_seconds": timeout_seconds,
                **({"conversation_id": conversation_id} if conversation_id else {}),
                **({"context": context} if context else {}),
            },
            turn_id=turn_id,
            conversation_id=conversation_id,
        )
        logger.info(
            "[AskUser] Asked: %s (options=%d, timeout=%ds)",
            text[:60], len(options or []), timeout_seconds,
        )
        return question

    # ── T3 (REQ-5): question sets ───────────────────────────────────────────

    def ask_set(
        self,
        specs: List[QuestionSpec],
        *,
        timeout_seconds: int = ASK_USER_QUESTION_TIMEOUT,
        turn_id: Optional[str] = None,
    ) -> QuestionSet:
        """Ask N questions as one set and return immediately (REQ-5 AC1).

        Every question gets its OWN `question_id` and is stored in
        `_pending` exactly like a question created by `ask()` — there is
        no separate storage or resolution path. Each resolves
        independently through `resolve_answer(question_id, answer)`
        (REQ-6 edge case), so one answered question never blocks or
        invalidates the others (REQ-5 AC5 edge case).

        WIRE PAYLOAD (REQ-5 AC6, CT-2): the emitted `question:ask` event
        ALWAYS carries `set_id` and a `questions` array. When the set has
        EXACTLY ONE question, the event ALSO carries the legacy top-level
        `question_id`/`text`/`options`/`allow_other` keys mirroring that
        question, so an unmodified (pre-T10) QuestionCard keeps working —
        this is additive, never a breaking change to the single-question
        shape.
        """
        qset = QuestionSet(turn_id=turn_id)
        for spec in specs:
            question = Question(
                text=spec.text,
                options=list(spec.options),
                allow_other=spec.allow_other,
                multi_select=spec.multi_select,
                header=spec.header,
                timeout_seconds=timeout_seconds,
                turn_id=turn_id,
                set_id=qset.set_id,
            )
            qset.questions.append(question)
            self._pending[question.question_id] = question

        data: Dict[str, Any] = {
            "set_id": qset.set_id,
            "questions": [
                {
                    "question_id": q.question_id,
                    "text": q.text,
                    "options": q.options,
                    "allow_other": q.allow_other,
                    "multi_select": q.multi_select,
                    "header": q.header,
                    "status": q.status,
                }
                for q in qset.questions
            ],
            "timeout_seconds": timeout_seconds,
        }
        if len(qset.questions) == 1:
            only = qset.questions[0]
            data.update({
                "question_id": only.question_id,
                "text": only.text,
                "options": only.options,
                "allow_other": only.allow_other,
            })

        self._bus.emit(self._IRISStreamEvent.QUESTION_ASK, data=data, turn_id=turn_id)
        logger.info(
            "[AskUser] Asked set=%s (%d question(s), timeout=%ds)",
            qset.set_id, len(qset.questions), timeout_seconds,
        )
        return qset

    def wait_for_set(
        self,
        qset: QuestionSet,
        poll_interval: float = 0.1,
        filler_interval: float = FILLER_INTERVAL,
    ) -> QuestionSet:
        """Block until every question in the set is answered or its own
        timeout elapses (REQ-5 AC5).

        Polls all still-pending questions on ONE shared clock rather than
        waiting on them one at a time, so an early answer to question A
        never delays question B's own deadline. Each question times out
        independently: on return, the set is a mix of `answered` /
        `timed_out` per-question statuses — never one failed whole (edge
        case: "timeout with a partially-answered set reports answered
        ones as answered and unanswered as unanswered").
        """
        last_filler = time.time()
        while True:
            open_questions = [q for q in qset.questions if q.question_id in self._pending]
            if not open_questions:
                break
            now = time.time()
            for question in open_questions:
                if now - question.created_at >= question.timeout_seconds:
                    self._pending.pop(question.question_id, None)
                    question.status = "timed_out"
                    self._bus.emit(
                        self._IRISStreamEvent.QUESTION_TIMEOUT,
                        data={"question_id": question.question_id, "set_id": qset.set_id},
                        turn_id=question.turn_id,
                    )
            if now - last_filler >= filler_interval:
                for question in open_questions:
                    if question.question_id in self._pending:
                        self.send_filler(question.question_id)
                last_filler = now
            time.sleep(poll_interval)
        return qset

    def receive_answer(self, question_id: str, answer: Any) -> Optional[Question]:
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

    def resolve_answer(self, question_id: str, answer: Union[str, List[str]]) -> Optional[Question]:
        """SINGLE resolution funnel (REQ-14 AC5, CT-4 first-wins; T3/REQ-6
        AC1: card click, free text, and voice ALL route through here).

        Card click and voice BOTH route through here. First caller wins:
        `receive_answer` pops the question from `_pending`, so a second answer
        (e.g. voice after click) is a no-op. A parked source linked to the
        question is resumed (REQ-13 AC3) so the research run can pick it up.

        T3 (REQ-5 point 6 — multi-select normalization): a `multi_select`
        question's answer is normalized to a list of option strings here,
        regardless of whether the caller passed a bare string or a list, so
        every downstream consumer (the QUESTION_ANSWERED event, the stored
        `Question.answer`) sees one consistent type. A non-multi-select
        question always resolves to a string. Voice stays single-select —
        `fuzzy_match_answer` matches exactly one option, and multi-select by
        voice is explicitly out of scope; `resolve_via_voice` never passes a
        list here.

        AC5: an unknown or already-resolved `question_id` reaches
        `receive_answer`, which returns None without raising — callers (the
        gateway) log that outcome themselves.
        """
        pending = self._pending.get(question_id)
        if pending is not None:
            answer = _normalize_answer(pending, answer)
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


# ── T3 (REQ-5 point 6): multi-select answer normalization ──────────────────


def _normalize_answer(question: Question, answer: Union[str, List[str]]) -> Union[str, List[str]]:
    """Normalize an answer at the funnel so every downstream consumer sees
    one consistent type for a given question (T3 design point 6).

    - `question.multi_select` -> always a list of option strings, even if
      the caller passed a bare string (a single selection made on a
      multi-select question).
    - Otherwise -> always a string; a list answer (should not normally
      happen off the click/text path) collapses to a comma-joined string
      rather than being rejected, since resolution must never raise.
    """
    if question.multi_select:
        if isinstance(answer, list):
            return [str(a) for a in answer]
        return [] if answer is None else [str(answer)]
    if isinstance(answer, list):
        return ", ".join(str(a) for a in answer)
    return answer


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
