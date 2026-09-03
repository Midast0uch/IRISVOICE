"""Contract tests: AskUserQuestion tool.

Verifies:
  - ask() creates pending question, emits QUESTION_ASK event
  - receive_answer() resolves question
  - fuzzy_match_answer() matches user input to options
  - wait_for_answer() timeout
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.agent.tools.ask_user_tool import (
    AskUserTool,
    Question,
    fuzzy_match_answer,
    get_ask_user_tool,
    reset_ask_user_tool_for_testing,
)


@pytest.fixture(autouse=True)
def reset():
    reset_ask_user_tool_for_testing()
    yield


class TestAskUserTool:
    def test_ask_creates_pending_question(self):
        tool = AskUserTool()
        q = tool.ask("Which file?", options=["a.txt", "b.txt"])
        assert q.status == "pending"
        assert q.text == "Which file?"
        assert len(q.options) == 2

    def test_ask_emits_question_ask_event(self):
        tool = AskUserTool()
        with patch.object(tool._bus, "emit") as mock_emit:
            tool.ask("Test?", options=["yes", "no"])
            events = [
                call for call in mock_emit.call_args_list
                if call[0][0].value == "question:ask"
            ]
            assert len(events) >= 1

    def test_receive_answer_resolves(self):
        tool = AskUserTool()
        q = tool.ask("Which color?", options=["red", "blue"])
        result = tool.receive_answer(q.question_id, "blue")
        assert result is not None
        assert result.status == "answered"
        assert result.answer == "blue"

    def test_receive_answer_unknown_returns_none(self):
        tool = AskUserTool()
        result = tool.receive_answer("nonexistent", "test")
        assert result is None

    def test_send_filler_returns_text(self):
        tool = AskUserTool()
        q = tool.ask("Test?", options=["a", "b"])
        filler = tool.send_filler(q.question_id)
        assert filler is not None
        assert isinstance(filler, str)

    def test_max_fillers_reached(self):
        tool = AskUserTool()
        q = tool.ask("Test?", options=["a", "b"])
        tool.send_filler(q.question_id)  # 1
        tool.send_filler(q.question_id)  # 2
        filler3 = tool.send_filler(q.question_id)  # 3 — capped at MAX_FILLERS=2
        assert filler3 is None

    def test_send_filler_unknown_returns_none(self):
        tool = AskUserTool()
        filler = tool.send_filler("no_such_q")
        assert filler is None

    def test_wait_for_answer_timeout(self):
        tool = AskUserTool()
        q = tool.ask("Timed?", options=["a", "b"], timeout_seconds=0.05)
        import time
        resolved = tool.wait_for_answer(q, poll_interval=0.02, filler_interval=10)
        assert resolved.status == "timed_out"


class TestFuzzyMatch:
    def test_exact_match(self):
        opt, conf, exact = fuzzy_match_answer("red", ["red", "blue"])
        assert opt == "red"
        assert conf == 1.0
        assert exact is True

    def test_numbered_choice(self):
        opt, conf, exact = fuzzy_match_answer("option 2", ["red", "blue"])
        assert opt == "blue"
        assert conf == 0.9
        assert exact is False

    def test_substring_match(self):
        opt, conf, exact = fuzzy_match_answer("the red one", ["red", "blue"])
        assert opt == "red"
        assert conf >= 0.7

    def test_word_overlap_match(self):
        opt, conf, exact = fuzzy_match_answer("read the document and summarize", ["read the document", "search the web"])
        assert opt is not None
        assert conf >= 0.5

    def test_no_match(self):
        opt, conf, exact = fuzzy_match_answer("zxywvut", ["red", "blue"])
        assert opt is None
        assert conf == 0.0
