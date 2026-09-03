"""Contract tests: web-search document rendering + format escalation.

Verifies the ChatCard-redesign contract (pin_9e97e21340e7):

1. Web/crawler results are CAPTURED into the document store (reformat-able) so
   the agent can render them as Prism Glass document cards.
2. The RENDER is the AGENT'S CHOICE — it must come from the agent's ``show``
   payload (format chosen by the agent), NOT a hardcoded auto-emit. So
   _capture_tool_result must NOT emit DOCUMENT_RENDER on its own.
3. ESCALATION — if the agent returns a web result WITHOUT a ``show`` (didn't
   choose a format), _maybe_escalate_web_format asks the user via a
   QuestionCard (ask_user_question with format options). The frontend renders
   that as a multiple-choice QuestionCard (components/chat/QuestionCard.tsx).

Frontend contract (components/chat-view.tsx handleDocumentRender) requires:
  content (required), format (optional, default markdown), alternatives,
  turn_id, document_id, trust (optional).

Frontend contract (components/chat/QuestionCard.tsx) requires:
  question_ask event with text + options[] (label/value) -> multiple-choice pills.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.event_bus import (
    IRISStreamEvent,
    get_event_bus,
    reset_event_bus_for_testing,
)


@pytest.fixture(autouse=True)
def _reset_bus():
    reset_event_bus_for_testing()
    yield
    reset_event_bus_for_testing()


def _make_kernel() -> AgentKernel:
    # Real instance (not MagicMock) so the actual methods run; only stub the
    # collaborators that touch external state.
    kernel = AgentKernel.__new__(AgentKernel)
    kernel._conversation_id = "conv-1"
    kernel._turn_id = "turn-1"
    kernel._store_document_data = MagicMock(return_value=None)
    kernel._pending_web_doc_id = None
    kernel._last_render_emitted = False
    return kernel


def _collect(event_type):
    captured = []
    get_event_bus().subscribe(event_type, lambda data, **k: captured.append(data))
    return captured


class TestWebResultCaptureContract:
    def test_web_result_is_captured_not_auto_rendered(self):
        """Web results are stored (reformat-able) but NOT auto-rendered — the
        render is the agent's choice via its `show` payload."""
        kernel = _make_kernel()
        renders = _collect(IRISStreamEvent.DOCUMENT_RENDER)
        doc_id = AgentKernel._capture_tool_result(
            kernel,
            tool_name="crawler_query",
            result={"content": "# Research\n\n- Found A\n- Found B", "pages": []},
            conversation_id="conv-1",
            turn_id="turn-1",
        )
        # Captured into the store (reformat-able) -> doc_id returned.
        assert doc_id is not None
        # Pending web doc tracked for escalation check.
        assert kernel._pending_web_doc_id == doc_id
        # NOT auto-rendered with a hardcoded format — agent must choose.
        assert len(renders) == 0

    def test_trusted_tool_does_not_trigger_web_escalation(self):
        kernel = _make_kernel()
        doc_id = AgentKernel._capture_tool_result(
            kernel,
            tool_name="read_file",
            result={"content": "file contents " * 50},  # long enough to be capture-worthy
            conversation_id="conv-1",
            turn_id="turn-1",
        )
        assert doc_id is not None
        assert kernel._pending_web_doc_id is None  # trusted tools don't escalate


class TestWebFormatEscalationContract:
    def test_escalates_when_agent_did_not_render(self):
        """If the agent returned a web result without a `show` (no render),
        escalate to a QuestionCard with format options."""
        kernel = _make_kernel()
        kernel._pending_web_doc_id = "doc-xyz"
        kernel._last_render_emitted = False
        questions = _collect(IRISStreamEvent.QUESTION_ASK)
        with patch(
            "backend.agent.tools.ask_user_tool.get_ask_user_tool"
        ) as mock_get:
            # Mock tool whose ask() emits the real question:ask event, mirroring
            # the production AskUserTool.ask behavior.
            mock_tool = MagicMock()

            def _fake_ask(**kwargs):
                get_event_bus().emit(
                    IRISStreamEvent.QUESTION_ASK,
                    data={
                        "text": kwargs.get("text", ""),
                        "options": kwargs.get("options", []),
                        "allow_other": kwargs.get("allow_other", False),
                        "turn_id": kwargs.get("turn_id"),
                        "conversation_id": kwargs.get("conversation_id"),
                        "context": kwargs.get("context", {}),
                    },
                    turn_id=kwargs.get("turn_id"),
                    conversation_id=kwargs.get("conversation_id"),
                )

            mock_tool.ask.side_effect = _fake_ask
            mock_get.return_value = mock_tool
            kernel._maybe_escalate_web_format("turn-1", "conv-1")
        # QuestionCard event emitted with format options (flat string list,
        # matching the frontend QuestionCard `options?: string[]` contract).
        assert len(questions) == 1
        payload = questions[0].data
        assert "format" in payload["text"].lower() or "present" in payload["text"].lower()
        opts = set(payload["options"])
        assert {"Markdown", "Table", "HTML", "Diagram", "Plain text"}.issubset(opts)
        # Flag cleared after escalation.
        assert kernel._pending_web_doc_id is None

    def test_no_escalation_when_agent_rendered(self):
        """If the agent already rendered (chose a format), no escalation."""
        kernel = _make_kernel()
        kernel._pending_web_doc_id = "doc-xyz"
        kernel._last_render_emitted = True
        questions = _collect(IRISStreamEvent.QUESTION_ASK)
        kernel._maybe_escalate_web_format("turn-1", "conv-1")
        assert len(questions) == 0
        assert kernel._pending_web_doc_id is None
