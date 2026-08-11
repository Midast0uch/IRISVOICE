"""Contract tests for T13 (REQ-13): non-blocking ask + ParkedSource registry.

Covers:
  - ask_non_blocking() returns immediately with a handle (AC1)
  - parked source registered (AC2), resumed on answer (AC3)
  - one question per domain per run (AC6)
  - first-wins resolution funnel (REQ-14 AC5 / CT-4): second answer is a no-op
  - timeout marks the parked source timed_out (REQ-16 logging path)
"""

from __future__ import annotations

import pytest

from backend.agent.tools.ask_user_tool import (
    AskUserTool,
    get_ask_user_tool,
    get_parked_source_registry,
    reset_ask_user_tool_for_testing,
    reset_parked_source_registry_for_testing,
)


@pytest.fixture(autouse=True)
def reset():
    reset_ask_user_tool_for_testing()
    reset_parked_source_registry_for_testing()
    yield


class TestNonBlockingAsk:
    def test_ask_non_blocking_returns_immediately_with_handle(self):
        tool = get_ask_user_tool()
        q = tool.ask_non_blocking(
            "Which source?", options=["option A", "option B"], parked_url="https://paywall.example/x",
        )
        # REQ-13 AC1: returns a handle immediately; the question is pending.
        assert q.question_id
        assert q.status == "pending"
        assert q.question_id in tool._pending

    def test_parked_source_registered_and_resumed_on_answer(self):
        tool = get_ask_user_tool()
        registry = get_parked_source_registry()
        q = tool.ask_non_blocking(
            "Wall detected", options=["Skip", "Try anyway"],
            parked_url="https://captcha.example/a", run_id="run_1",
        )
        parked = registry.get(q.question_id)
        assert parked is not None
        assert parked.domain == "captcha.example"
        assert parked.status == "parked"

        # REQ-13 AC3: answering resumes the parked source without restarting.
        tool.resolve_answer(q.question_id, "Skip")
        resolved = registry.get(q.question_id)
        assert resolved is None  # popped on resume
        assert parked.status == "resumed"
        assert parked.answer == "Skip"

    def test_one_question_per_domain_per_run(self):
        """REQ-13 AC6: repeated blocked source on the same domain -> no re-ask."""
        tool = get_ask_user_tool()
        registry = get_parked_source_registry()
        q1 = tool.ask_non_blocking(
            "First", parked_url="https://paywall.example/a", run_id="run_1",
        )
        q2 = tool.ask_non_blocking(
            "Second", parked_url="https://paywall.example/b", run_id="run_1",
        )
        parked2 = registry.get(q2.question_id)
        assert parked2 is None  # domain already asked this run

    def test_same_domain_different_run_asks_again(self):
        tool = get_ask_user_tool()
        registry = get_parked_source_registry()
        tool.ask_non_blocking("Run 1", parked_url="https://paywall.example/a", run_id="run_1")
        q2 = tool.ask_non_blocking("Run 2", parked_url="https://paywall.example/b", run_id="run_2")
        assert registry.get(q2.question_id) is not None

    def test_timeout_marks_parked_source_timed_out(self):
        tool = get_ask_user_tool()
        registry = get_parked_source_registry()
        q = tool.ask_non_blocking(
            "Question", parked_url="https://paywall.example/a", run_id="run_1",
        )
        registry.mark_timed_out(q.question_id)
        assert registry.get(q.question_id) is None
        assert q.status == "pending"  # question itself still tracked by tool

    def test_resume_of_unknown_question_returns_none(self):
        registry = get_parked_source_registry()
        assert registry.resume("nope", answer="x") is None


class TestFirstWinsFunnel:
    def test_first_wins_second_answer_is_noop(self):
        """REQ-14 AC5 / CT-4: card click and voice funnel to ONE resolution
        point; the second answer must be a no-op."""
        tool = get_ask_user_tool()
        q = tool.ask_non_blocking(
            "Which?", options=["A", "B"], parked_url="https://paywall.example/x",
        )
        first = tool.resolve_answer(q.question_id, "A")
        second = tool.resolve_answer(q.question_id, "B")
        assert first is not None
        assert first.answer == "A"
        assert second is None  # popped by the first caller

    def test_resolve_answer_emits_answered_event(self):
        from backend.agent.event_bus import IRISStreamEvent

        tool = AskUserTool()
        q = tool.ask("Which?")
        events = []
        orig_emit = tool._bus.emit

        def spy(ev, **kw):
            events.append(ev)
            return orig_emit(ev, **kw)

        tool._bus.emit = spy
        tool.resolve_answer(q.question_id, "A")
        assert IRISStreamEvent.QUESTION_ANSWERED in events
