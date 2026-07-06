"""Behavioral tests: Director mode selection, escalation, and agentic explorer.

Verifies end-to-end behavior:
  - Director picks the right mode for different task types
  - Mode escalates when reviewer vetoes or tool result indicates more work
  - Agentic explorer re-plans next steps when queue is complete
  - Voice tasks can be multi-step (no hard cap)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, ANY

import pytest

from backend.agent.der_loop import (
    DirectorQueue,
    QueueItem,
    ReviewVerdict,
    ExecutionMode,
)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def queue():
    return DirectorQueue(objective="Test objective", items=[])


# ── Mode selection end-to-end ──────────────────────────────────────────────


class TestModeSelectionBehavior:
    def test_simple_question_gets_quick_mode(self):
        mode = DirectorQueue._decide_mode(
            task_class="question",
            message_text="What's 2+2?",
            confidence=0.9,
        )
        assert mode == ExecutionMode.QUICK

    def test_research_task_gets_full_mode(self):
        mode = DirectorQueue._decide_mode(
            task_class="research",
            message_text="Research the Caducean engine and its role in the MCM system",
            confidence=0.85,
        )
        assert mode == ExecutionMode.FULL

    def test_tool_request_gets_agentic_mode(self):
        mode = DirectorQueue._decide_mode(
            task_class="tool_request",
            message_text="Find all Python files and analyze their structure",
            confidence=0.85,
        )
        assert mode == ExecutionMode.AGENTIC

    def test_mode_persists_through_queue(self, queue):
        queue.set_mode(ExecutionMode.AGENTIC, reason="Initial")
        assert queue.mode == ExecutionMode.AGENTIC
        items = [
            QueueItem(step_id="s1", step_number=1, description="Step 1", tool="read_file"),
            QueueItem(step_id="s2", step_number=2, description="Step 2", tool="search"),
        ]
        for item in items:
            queue.add_item(item)
        queue.mark_complete("s1")
        assert queue.mode == ExecutionMode.AGENTIC  # unchanged


# ── Escalation behavior ────────────────────────────────────────────────────


class TestEscalationBehavior:
    def test_escalation_gives_higher_budget(self, queue):
        """Higher mode = higher token budget."""
        from backend.agent.der_constants import get_token_budget

        queue.mode = ExecutionMode.QUICK
        assert get_token_budget(queue.mode.value) == 15_000

        queue.escalate(reason="Need more budget")
        assert queue.mode == ExecutionMode.AGENTIC
        assert get_token_budget(queue.mode.value) == 30_000

        queue.escalate(reason="Even more")
        assert queue.mode == ExecutionMode.FULL
        assert get_token_budget(queue.mode.value) == 60_000

    def test_escalation_until_veto_resolved(self, queue):
        """Multiple vetos escalate step by step."""
        queue.mode = ExecutionMode.QUICK

        queue.check_escalation(
            ReviewVerdict.VETO, "Failed", token_budget_remaining=20000
        )
        assert queue.mode == ExecutionMode.AGENTIC

        queue.check_escalation(
            ReviewVerdict.VETO, "Failed again", token_budget_remaining=20000
        )
        assert queue.mode == ExecutionMode.FULL

        prev = queue.mode
        queue.check_escalation(
            ReviewVerdict.VETO, "Failed thrice", token_budget_remaining=20000
        )
        assert queue.mode == prev  # stays FULL

    def test_mode_history_tracks_chain(self, queue):
        queue.mode = ExecutionMode.QUICK
        queue.escalate(reason="Veto", turn_id="t1")
        queue.escalate(reason="Complex", turn_id="t2")
        queue.de_escalate(reason="Simpler", turn_id="t3")

        assert len(queue.mode_history) == 3
        assert queue.mode_history[0].new_mode == ExecutionMode.AGENTIC
        assert queue.mode_history[1].new_mode == ExecutionMode.FULL
        assert queue.mode_history[2].new_mode == ExecutionMode.AGENTIC


# ── Explorer re-planning behavior (direct method call) ─────────────────────


class TestExplorerBehavior:
    def _call_explorer(self, kernel_mock, task, completed, mode):
        """Helper: call the explorer method with a mock self."""
        from backend.agent.agent_kernel import AgentKernel
        # Use a real logger to capture warnings
        import logging
        kernel_mock._logger = logging.getLogger(__name__)
        return AgentKernel._der_plan_next_step(kernel_mock, task, completed, mode)

    def test_explorer_adds_next_step_when_more_work(self):
        """When LLM says more work is needed, explorer adds next tool."""
        mock_self = MagicMock()
        mock_self._logger = MagicMock()
        mock_response = MagicMock()
        mock_response.raw_text = json.dumps({
            "done": False,
            "tool": "search",
            "description": "Search for more results",
            "params": {"query": "extended research"},
        })
        mock_self.infer = MagicMock(return_value=mock_response)

        completed = [
            QueueItem(step_id="s1", step_number=1, description="Initial search", tool="search"),
        ]

        result = self._call_explorer(mock_self, "Research topic", completed, ExecutionMode.AGENTIC)

        assert result is not None
        assert result["tool"] == "search"
        assert result["description"] == "Search for more results"
        mock_self.infer.assert_called_once()

    def test_explorer_returns_none_when_done(self):
        """When LLM says objective is met, explorer returns None."""
        mock_self = MagicMock()
        mock_self._logger = MagicMock()
        mock_response = MagicMock()
        mock_response.raw_text = json.dumps({"done": True})
        mock_self.infer = MagicMock(return_value=mock_response)

        completed = [
            QueueItem(step_id="s1", step_number=1, description="Found answer", tool="search"),
        ]

        result = self._call_explorer(mock_self, "Simple question", completed, ExecutionMode.QUICK)

        assert result is None

    def test_explorer_handles_empty_completed(self):
        """Explorer returns None when no steps completed yet."""
        mock_self = MagicMock()
        mock_self._logger = MagicMock()
        result = self._call_explorer(mock_self, "Test", [], ExecutionMode.AGENTIC)
        assert result is None

    def test_explorer_graceful_on_parse_error(self):
        """If LLM returns bad JSON, explorer returns None (no crash)."""
        mock_self = MagicMock()
        mock_self._logger = MagicMock()
        mock_response = MagicMock()
        mock_response.raw_text = "This is not JSON at all!!!"
        mock_self.infer = MagicMock(return_value=mock_response)

        completed = [QueueItem(step_id="s1", step_number=1, description="Step 1", tool="read")]

        result = self._call_explorer(mock_self, "Test", completed, ExecutionMode.AGENTIC)
        assert result is None


# ── Voice no-hard-cap behavior ─────────────────────────────────────────────


class TestVoiceBehavior:
    def test_voice_task_can_be_multi_step(self):
        """Voice tasks are NOT hard-capped to 1 step — Director decides by content."""
        mode = DirectorQueue._decide_mode(
            task_class="voice_first",
            from_voice=True,
            message_text="Find all Python files with security vulnerabilities and fix them",
            voice_preference="auto",
        )
        assert mode == ExecutionMode.AGENTIC

    def test_voice_quick_question_stays_quick(self):
        """But a voice quick question still gets QUICK mode."""
        mode = DirectorQueue._decide_mode(
            task_class="question",
            from_voice=True,
            message_text="What time is it?",
            voice_preference="auto",
        )
        assert mode == ExecutionMode.QUICK
