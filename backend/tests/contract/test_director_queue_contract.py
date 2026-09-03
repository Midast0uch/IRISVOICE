"""Contract tests: DirectorQueue mode management (Phase 3).

Verifies:
  - set_mode/escalate/de_escalate lifecycle
  - Mode history tracking
  - _decide_mode selection logic (all combinations)
  - check_escalation triggers
"""

from __future__ import annotations

import pytest

from backend.agent.der_constants import ExecutionMode, MODE_ORDER
from backend.agent.der_loop import DirectorQueue, QueueItem


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def queue():
    return DirectorQueue(objective="Test task", items=[])


# ── Mode enum tests ────────────────────────────────────────────────────────


class TestExecutionMode:
    def test_quick_escalates_to_agentic(self):
        assert ExecutionMode.QUICK.escalate() == ExecutionMode.AGENTIC

    def test_agentic_escalates_to_full(self):
        assert ExecutionMode.AGENTIC.escalate() == ExecutionMode.FULL

    def test_full_escalates_to_full(self):
        assert ExecutionMode.FULL.escalate() == ExecutionMode.FULL

    def test_agentic_deescalates_to_quick(self):
        assert ExecutionMode.AGENTIC.de_escalate() == ExecutionMode.QUICK

    def test_full_deescalates_to_agentic(self):
        assert ExecutionMode.FULL.de_escalate() == ExecutionMode.AGENTIC

    def test_quick_deescalates_to_quick(self):
        assert ExecutionMode.QUICK.de_escalate() == ExecutionMode.QUICK

    def test_from_string_valid(self):
        assert ExecutionMode.from_string("quick") == ExecutionMode.QUICK
        assert ExecutionMode.from_string("AGENTIC") == ExecutionMode.AGENTIC
        assert ExecutionMode.from_string("Full") == ExecutionMode.FULL

    def test_from_string_invalid_falls_back(self):
        assert ExecutionMode.from_string("unknown") == ExecutionMode.AGENTIC
        assert ExecutionMode.from_string("") == ExecutionMode.AGENTIC

    def test_mode_order_complete(self):
        assert MODE_ORDER == [ExecutionMode.QUICK, ExecutionMode.AGENTIC, ExecutionMode.FULL]


# ── set_mode tests ─────────────────────────────────────────────────────────


class TestSetMode:
    def test_set_mode_changes_mode(self, queue):
        queue.set_mode(ExecutionMode.AGENTIC, reason="Test escalation")
        assert queue.mode == ExecutionMode.AGENTIC

    def test_set_mode_records_history(self, queue):
        queue.set_mode(ExecutionMode.AGENTIC, reason="Need tools", turn_id="turn_001")
        assert len(queue.mode_history) == 1
        entry = queue.mode_history[0]
        assert entry.previous_mode == ExecutionMode.QUICK  # default
        assert entry.new_mode == ExecutionMode.AGENTIC
        assert entry.reason == "Need tools"
        assert entry.turn_id == "turn_001"

    def test_set_mode_keeps_full_history(self, queue):
        queue.set_mode(ExecutionMode.AGENTIC, reason="First")
        queue.set_mode(ExecutionMode.FULL, reason="Second")
        assert len(queue.mode_history) == 2

    def test_set_mode_logs_token_budget(self, queue):
        queue.set_mode(
            ExecutionMode.AGENTIC,
            reason="Test",
            token_budget=15000,
        )
        assert queue.mode_history[0].token_budget_remaining == 15000


class TestEscalate:
    def test_escalate_from_quick(self, queue):
        queue.mode = ExecutionMode.QUICK
        queue.escalate(reason="Need more power")
        assert queue.mode == ExecutionMode.AGENTIC

    def test_escalate_from_agentic(self, queue):
        queue.mode = ExecutionMode.AGENTIC
        queue.escalate(reason="Deep research needed")
        assert queue.mode == ExecutionMode.FULL

    def test_escalate_from_full_stays_full(self, queue):
        queue.mode = ExecutionMode.FULL
        queue.escalate(reason="Already max")
        assert queue.mode == ExecutionMode.FULL

    def test_escalate_records_reason(self, queue):
        queue.mode = ExecutionMode.QUICK
        queue.escalate(reason="More work needed")
        assert queue.mode_history[-1].reason == "More work needed"


class TestDeEscalate:
    def test_deescalate_from_full(self, queue):
        queue.mode = ExecutionMode.FULL
        queue.de_escalate(reason="Task was simpler")
        assert queue.mode == ExecutionMode.AGENTIC

    def test_deescalate_from_agentic(self, queue):
        queue.mode = ExecutionMode.AGENTIC
        queue.de_escalate(reason="Simple Q&A")
        assert queue.mode == ExecutionMode.QUICK

    def test_deescalate_from_quick_stays_quick(self, queue):
        queue.mode = ExecutionMode.QUICK
        queue.de_escalate(reason="Already min")
        assert queue.mode == ExecutionMode.QUICK


# ── _decide_mode tests ─────────────────────────────────────────────────────


class TestDecideMode:
    """Test the Director's mode selection logic."""

    def test_user_preference_overrides(self):
        mode = DirectorQueue._decide_mode(
            task_class="research",
            user_preference="quick",
        )
        assert mode == ExecutionMode.QUICK

    def test_user_preference_full(self):
        mode = DirectorQueue._decide_mode(
            task_class="question",
            user_preference="full",
        )
        assert mode == ExecutionMode.FULL

    def test_low_budget_returns_quick(self):
        mode = DirectorQueue._decide_mode(
            task_class="research",
            token_budget_remaining=1000,
        )
        assert mode == ExecutionMode.QUICK

    def test_high_conf_question_is_quick(self):
        mode = DirectorQueue._decide_mode(
            task_class="question",
            confidence=0.9,
            message_text="What's 2+2?",
        )
        assert mode == ExecutionMode.QUICK

    def test_high_conf_research_is_full(self):
        mode = DirectorQueue._decide_mode(
            task_class="research",
            confidence=0.9,
            message_text="Research the history of the Caducean Engine",
        )
        assert mode == ExecutionMode.FULL

    def test_high_conf_tool_request_is_agentic(self):
        mode = DirectorQueue._decide_mode(
            task_class="tool_request",
            confidence=0.9,
            message_text="Find all Python files with TODO comments",
        )
        assert mode == ExecutionMode.AGENTIC

    def test_short_message_is_quick(self):
        mode = DirectorQueue._decide_mode(
            task_class="unknown",
            message_text="Hi",
            confidence=0.5,
        )
        assert mode == ExecutionMode.QUICK

    def test_long_message_tends_to_full(self):
        mode = DirectorQueue._decide_mode(
            task_class="complex",
            message_text="Research the architecture, write a report, create a diagram, "
                         "send it to the team, and schedule a review meeting. " * 5,
            confidence=0.5,
        )
        assert mode == ExecutionMode.FULL

    def test_medium_message_defaults_agentic(self):
        mode = DirectorQueue._decide_mode(
            task_class="tool_request",
            message_text="Find files with TODOs and categorize them by importance",
            confidence=0.5,
        )
        assert mode == ExecutionMode.AGENTIC

    def test_voice_auto_with_short_message_is_quick(self):
        mode = DirectorQueue._decide_mode(
            task_class="voice_first",
            from_voice=True,
            message_text="What time is it?",
            voice_preference="auto",
        )
        assert mode == ExecutionMode.QUICK

    def test_voice_auto_with_long_message_is_agentic(self):
        mode = DirectorQueue._decide_mode(
            task_class="voice_first",
            from_voice=True,
            message_text="Find all Python files with TODO comments, categorize them by severity, "
                         "and generate a report with recommendations.",
            voice_preference="auto",
        )
        assert mode == ExecutionMode.AGENTIC

    def test_voice_quick_first_is_quick(self):
        mode = DirectorQueue._decide_mode(
            task_class="research",
            from_voice=True,
            message_text="Do comprehensive research",
            voice_preference="quick_first",
        )
        assert mode == ExecutionMode.QUICK

    def test_default_mode_is_agentic(self):
        mode = DirectorQueue._decide_mode(
            task_class="unknown",
            message_text="This is a medium length task that needs multiple steps to complete",
            confidence=0.3,
        )
        assert mode == ExecutionMode.AGENTIC


# ── check_escalation tests ─────────────────────────────────────────────────


class TestCheckEscalation:
    def test_veto_triggers_escalation(self, queue):
        queue.mode = ExecutionMode.QUICK
        from backend.agent.der_loop import ReviewVerdict

        escalated = queue.check_escalation(
            review_verdict=ReviewVerdict.VETO,
            tool_result_summary="Step failed",
            token_budget_remaining=20000,
        )
        assert escalated is True
        assert queue.mode == ExecutionMode.AGENTIC

    def test_pass_does_not_escalate(self, queue):
        queue.mode = ExecutionMode.QUICK
        from backend.agent.der_loop import ReviewVerdict

        escalated = queue.check_escalation(
            review_verdict=ReviewVerdict.PASS,
            tool_result_summary="Found the answer",
            token_budget_remaining=20000,
        )
        assert escalated is False
        assert queue.mode == ExecutionMode.QUICK

    def test_incomplete_result_triggers_escalation(self, queue):
        queue.mode = ExecutionMode.QUICK
        from backend.agent.der_loop import ReviewVerdict

        escalated = queue.check_escalation(
            review_verdict=ReviewVerdict.PASS,
            tool_result_summary="Found multiple files, need more research",
            token_budget_remaining=20000,
        )
        assert escalated is True
        assert queue.mode == ExecutionMode.AGENTIC

    def test_full_mode_does_not_escalate(self, queue):
        queue.mode = ExecutionMode.FULL
        from backend.agent.der_loop import ReviewVerdict

        escalated = queue.check_escalation(
            review_verdict=ReviewVerdict.VETO,
            tool_result_summary="Anything",
            token_budget_remaining=50000,
        )
        assert escalated is False  # Already at max

    def test_low_budget_does_not_escalate(self, queue):
        queue.mode = ExecutionMode.QUICK
        from backend.agent.der_loop import ReviewVerdict

        escalated = queue.check_escalation(
            review_verdict=ReviewVerdict.VETO,
            tool_result_summary="Failed",
            token_budget_remaining=1000,  # Below BUDGET_ABSOLUTE_MIN
        )
        assert escalated is False
