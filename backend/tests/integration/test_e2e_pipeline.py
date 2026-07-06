"""Phase 6 — End-to-end integration test: full pipeline verification.

Exercises the key cross-cutting flows across all phases:
  1. ExecutionMode selection → Director decision → queue setup
  2. EventBus emission → TaskKernel subscription
  3. Tool classification → Permission check (auto-approve for READ_ONLY)
  4. Conversation context persistence → save/restore roundtrip
  5. Mode escalation triggers → verify behavior under veto
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.agent.der_constants import ExecutionMode, get_token_budget
from backend.agent.der_loop import DirectorQueue, QueueItem, ReviewVerdict
from backend.agent.event_bus import EventBus, IRISStreamEvent
from backend.agent.task_kernel import TaskKernel, Task
from backend.agent.conversation_context_store import ConversationContext, ConversationContextStore
from backend.agent.permissions import classify_tool, PermissionTier, get_permission_action, PermissionAction


# ── Cross-phase integration tests ──────────────────────────────────────────


@pytest.fixture
def bus():
    return EventBus()


class TestFlow1_ModeSelectionExecution:
    """Phase 3: Mode selection → Director decision → task execution."""

    def test_director_selects_agentic_for_complex_tasks(self):
        mode = DirectorQueue._decide_mode(
            task_class="tool_request",
            message_text="Find all configuration files and analyze their security settings",
            confidence=0.85,
        )
        assert mode == ExecutionMode.AGENTIC
        assert get_token_budget(mode.value) == 30_000  # AGENTIC budget

    def test_director_selects_quick_for_simple_questions(self):
        mode = DirectorQueue._decide_mode(
            task_class="question",
            message_text="What's 2+2?",
            confidence=0.9,
        )
        assert mode == ExecutionMode.QUICK
        assert get_token_budget(mode.value) == 15_000  # QUICK budget

    def test_director_selects_full_for_research(self):
        mode = DirectorQueue._decide_mode(
            task_class="research",
            message_text="Research the MCM system architecture",
            confidence=0.85,
        )
        assert mode == ExecutionMode.FULL
        assert get_token_budget(mode.value) == 60_000  # FULL budget

    def test_director_escalates_on_veto(self):
        queue = DirectorQueue(objective="Test", items=[])
        queue.mode = ExecutionMode.QUICK
        queue.check_escalation(ReviewVerdict.VETO, "Step failed", token_budget_remaining=20000)
        assert queue.mode == ExecutionMode.AGENTIC
        assert len(queue.mode_history) == 1


class TestFlow2_EventBusTaskKernel:
    """Phase 2 + 3: EventBus emissions → TaskKernel subscription."""

    def test_tool_call_flow(self, bus):
        tk = TaskKernel(event_bus=bus)

        # Emit a tool call via EventBus (as the DER loop does)
        bus.emit(
            IRISStreamEvent.TOOL_CALL,
            data={"tool_name": "read_file", "task_id": "e2e_001"},
            conversation_id="conv_e2e",
        )

        task = tk.get_task("e2e_001")
        assert task is not None
        assert task.status == "in_progress"
        assert task.conversation_id == "conv_e2e"

        # Emit tool result
        bus.emit(
            IRISStreamEvent.TOOL_RESULT,
            data={"task_id": "e2e_001", "result_summary": "Found the file"},
        )

        task = tk.get_task("e2e_001")
        assert task.steps[-1].status == "completed"

    def test_multi_step_task_progress(self, bus):
        tk = TaskKernel(event_bus=bus)

        # Three sequential tool calls (simulating DER loop AGENTIC mode)
        for i in range(3):
            bus.emit(
                IRISStreamEvent.TOOL_CALL,
                data={"tool_name": f"step_{i}", "task_id": "e2e_multi", "description": f"Step {i}"},
            )
            bus.emit(
                IRISStreamEvent.TOOL_RESULT,
                data={"task_id": "e2e_multi", "result_summary": f"Done {i}"},
            )

        task = tk.get_task("e2e_multi")
        assert task is not None
        assert len(task.steps) == 3
        assert all(s.status == "completed" for s in task.steps)


class TestFlow3_PermissionClassification:
    """Phase 4: Tool classification → Permission tier → Auto-approve."""

    def test_read_only_auto_approves(self):
        tier = classify_tool("read_file")
        action = get_permission_action(tier, "developer")
        assert action == PermissionAction.AUTO_APPROVE

    def test_side_effect_requires_approval_in_developer(self):
        tier = classify_tool("write_file")
        action = get_permission_action(tier, "developer")
        assert action == PermissionAction.REQUIRE_APPROVAL

    def test_destructive_param_escalation(self):
        tier = classify_tool("run_command", {"command": "rm -rf /tmp"})
        assert tier == PermissionTier.DESTRUCTIVE

    def test_personal_mode_auto_approves_side_effect(self):
        tier = classify_tool("write_file")
        action = get_permission_action(tier, "personal")
        assert action == PermissionAction.AUTO_APPROVE


class TestFlow4_ContextPersistence:
    """Phase 1: Conversation context save/restore roundtrip."""

    def test_save_and_restore(self, tmp_path):
        db_path = tmp_path / "e2e_contexts.db"
        store = ConversationContextStore(db_path=db_path)

        ctx = ConversationContext(conversation_id="e2e_conv")
        ctx.tokens_used = 1234
        ctx.current_mode = "agentic"
        ctx.add_message("user", "hello", turn_id="t1")
        ctx.add_message("assistant", "hi there", turn_id="t2")

        store.save("e2e_conv", ctx)
        restored = store.get_or_restore("e2e_conv")

        assert restored is not None
        assert restored.conversation_id == "e2e_conv"
        assert restored.tokens_used == 1234
        assert restored.current_mode == "agentic"
        assert len(restored.messages) == 2
        assert restored.messages[0].turn_id == "t1"

        store.close()

    def test_conversation_isolation(self, tmp_path):
        """Two conversations don't interfere."""
        db_path = tmp_path / "e2e_isolation.db"
        store = ConversationContextStore(db_path=db_path)

        ctx_a = ConversationContext(conversation_id="conv_a")
        ctx_a.tokens_used = 100
        store.save("conv_a", ctx_a)

        ctx_b = ConversationContext(conversation_id="conv_b")
        ctx_b.tokens_used = 200
        store.save("conv_b", ctx_b)

        assert store.get_or_restore("conv_a").tokens_used == 100
        assert store.get_or_restore("conv_b").tokens_used == 200

        store.close()
