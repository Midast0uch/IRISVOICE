"""Contract (reply-surface-contract REQ-11 AC1/AC2 + REQ-12 AC3; audit
2026-09-22, F1): questions carry the LIVE turn id, not the WS session id.

Before the fix, tool_bridge passed ``turn_id=session_id`` (e.g.
``session_<client_id>``) while the frontend anchors question cards to
per-turn message ids — the two namespaces never matched, so in-turn
anchoring and reply-supersession dismissal were dead in production. The
session linkage (voice-answer routing, pending reattach) now rides an
explicit ``session_id`` field on the question instead.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import patch

from backend.agent.tool_bridge import AgentToolBridge
from backend.agent.tools.ask_user_tool import AskUserTool, Question


class _FakeAskTool:
    """Records ask() kwargs; resolves immediately as timed out."""

    def __init__(self):
        self.ask_kwargs = None

    def ask(self, **kw):
        self.ask_kwargs = kw
        return SimpleNamespace(question_id="q_test1")

    def wait_for_answer(self, question):
        return SimpleNamespace(
            status="timed_out", answer=None, question_id=question.question_id
        )


def _bridge() -> AgentToolBridge:
    bridge = AgentToolBridge.__new__(AgentToolBridge)
    bridge._active_conversation_id = {}
    bridge._logger = logging.getLogger("test_question_turn_anchor")
    return bridge


def _drive(bridge, kernel, tool):
    async def run():
        with patch(
            "backend.agent.agent_kernel.get_agent_kernel", return_value=kernel
        ), patch(
            "backend.agent.tools.ask_user_tool.get_ask_user_tool",
            return_value=tool,
        ):
            return await bridge._handle_ask_user_question(
                {"text": "Which format?"}, "sess-99"
            )

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run())
    finally:
        loop.close()


class TestQuestionCarriesTheLiveTurnId:
    def test_turn_id_is_the_live_turn_not_the_session(self):
        tool = _FakeAskTool()
        kernel = SimpleNamespace(_current_turn_id="turn-live-77")
        _drive(_bridge(), kernel, tool)
        assert tool.ask_kwargs is not None
        assert tool.ask_kwargs["turn_id"] == "turn-live-77", (
            "the frontend anchors question cards on message turn ids — a "
            "session id never matches"
        )
        assert tool.ask_kwargs["session_id"] == "sess-99", (
            "session linkage must stay explicit for voice-answer routing"
        )

    def test_fallback_to_session_when_no_turn_is_known(self):
        tool = _FakeAskTool()
        kernel = SimpleNamespace(_current_turn_id=None)
        _drive(_bridge(), kernel, tool)
        assert tool.ask_kwargs["turn_id"] == "sess-99"


class TestSessionLinkageSurvivesTurnAnchoring:
    """ask_user_tool.pending_for_session linked by turn_id == session_id;
    with real turn ids that lookup goes through the session_id field, with a
    fallback for legacy questions."""

    def test_pending_for_session_matches_on_session_id(self):
        tool = AskUserTool()
        q = Question(text="?", turn_id="turn-1", session_id="sess-A")
        tool._pending[q.question_id] = q
        assert tool.pending_for_session("sess-A").question_id == q.question_id

    def test_pending_for_session_fallback_keeps_legacy_questions(self):
        tool = AskUserTool()
        legacy = Question(text="?", turn_id="sess-legacy")  # pre-F1 shape
        tool._pending[legacy.question_id] = legacy
        assert (
            tool.pending_for_session("sess-legacy").question_id
            == legacy.question_id
        )
        assert tool.pending_for_session("some-other-session") is None
