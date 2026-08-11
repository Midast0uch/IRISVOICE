"""Contract tests for T15 (REQ-14): answering a question card by voice.

Verifies the testable core — AskUserTool.resolve_via_voice — against AC1-AC6:
  AC1: pending question -> next transcript is a candidate answer
  AC2: matched with fuzzy_match_answer
  AC3: at/above threshold -> resolved, same event as card click (first-wins)
  AC4: below threshold -> stays pending, user asked to repeat, no guessing
  AC5: card click can still resolve; first resolution wins
  AC6: no pending question -> transcript routes to normal path unchanged
"""

import pytest

from backend.agent.tools.ask_user_tool import (
    AskUserTool,
    get_parked_source_registry,
    reset_ask_user_tool_for_testing,
    reset_parked_source_registry_for_testing,
)


@pytest.fixture(autouse=True)
def reset():
    reset_ask_user_tool_for_testing()
    reset_parked_source_registry_for_testing()
    yield


def _ask(tool, session="s1", options=("red", "blue"), **kw):
    return tool.ask("Which color?", options=list(options), turn_id=session, **kw)


class TestResolveViaVoice:
    def test_ac6_no_pending_question_routes_normal(self):
        tool = AskUserTool()
        result = tool.resolve_via_voice("hello there", "s1")
        assert result == {"handled": False}

    def test_ac1_ac2_ac3_voice_answer_resolves(self):
        """Pending question + transcript matching an option at/above threshold
        resolves it via the SAME funnel a card click uses (AC1-AC3)."""
        tool = AskUserTool()
        q = _ask(tool)
        # "red" is an exact match -> confidence 1.0 >= 0.7
        result = tool.resolve_via_voice("red", "s1")
        assert result["handled"] is True
        assert result["resolved"] == "red"
        assert q.status == "answered"
        assert q.answer == "red"

    def test_ac4_below_threshold_asks_repeat_and_stays_pending(self):
        tool = AskUserTool()
        q = _ask(tool)
        # Unrelated utterance -> no match -> below threshold.
        result = tool.resolve_via_voice("the weather is nice", "s1")
        assert result == {"handled": False, "repeat": True}
        assert q.status == "pending"  # left pending, not guessed
        assert q.filler_count >= 1  # user asked to repeat

    def test_ac4_utterance_not_swallowed(self):
        """Below-threshold voice answer still returns handled=False so the
        caller routes it to the normal command path (edge, never swallowed)."""
        tool = AskUserTool()
        _ask(tool)
        result = tool.resolve_via_voice("zxywvut", "s1")
        assert result["handled"] is False

    def test_ac5_card_click_wins_over_voice(self):
        """First resolution wins: card click resolves; a later voice answer is
        a no-op (CT-4 first-wins funnel)."""
        tool = AskUserTool()
        q = _ask(tool)
        first = tool.resolve_answer(q.question_id, "red")  # card click
        assert first.answer == "red"
        # Voice arrives after the card resolved -> question gone -> normal path.
        result = tool.resolve_via_voice("blue", "s1")
        assert result == {"handled": False}
        assert q.answer == "red"  # unchanged by the late voice answer

    def test_ac5_voice_wins_over_late_card_click(self):
        """First resolution wins: voice resolves; a later card click is a no-op."""
        tool = AskUserTool()
        q = _ask(tool)
        voice = tool.resolve_via_voice("blue", "s1")
        assert voice["handled"] is True
        late = tool.resolve_answer(q.question_id, "red")  # late card click
        assert late is None  # question already resolved by voice
        assert q.answer == "blue"

    def test_two_questions_most_recent_wins(self):
        """REQ-14 edge: two pending questions -> the most recent gets the
        transcript; the other stays pending."""
        tool = AskUserTool()
        q_old = _ask(tool, session="s1")
        import time
        time.sleep(0.01)
        q_new = tool.ask("Second?", options=["x", "y"], turn_id="s1")
        assert tool.pending_for_session("s1").question_id == q_new.question_id
        result = tool.resolve_via_voice("y", "s1")
        assert result["handled"] is True
        assert q_new.status == "answered"
        assert q_old.status == "pending"

    def test_session_scoped_pending(self):
        """Pending questions are scoped to their session (turn_id)."""
        tool = AskUserTool()
        _ask(tool, session="s1")
        assert tool.pending_for_session("s2") is None
        assert tool.pending_for_session("s1") is not None

    def test_parked_source_resumed_by_voice_answer(self):
        """Voice-answering a parked-source question resumes it (REQ-13 AC3 +
        REQ-14 AC3 combined)."""
        tool = AskUserTool()
        q = tool.ask_non_blocking(
            "Wall?", options=["Skip", "Retry"],
            parked_url="https://paywall.example/x", run_id="run_1", turn_id="s1",
        )
        result = tool.resolve_via_voice("skip", "s1")
        assert result["handled"] is True
        registry = get_parked_source_registry()
        parked = registry.get(q.question_id)
        assert parked is None  # popped on resume
        assert registry.pending("run_1") == []
