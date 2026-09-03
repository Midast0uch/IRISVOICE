"""Behavioral tests — T15 (REQ-3 continue-vs-branch, REQ-4 rehydration).

specs/task-card-v2-liquid-ink. Drives the REAL `AgentKernel._resolve_card_identity`
(no stub — a bare kernel instance carries all the state the method needs) and the
REAL card persistence path (`ConversationContextStore.save_card` /
`get_cards_for_conversation`, plus the kernel's own `_persist_card_snapshot`
through the background write queue):

  - REQ-3: a follow-up task that CONTINUES an existing card must REUSE the same
    card — the SECOND card must NOT appear. A "new" relation must create a
    second, DISTINCT card.
  - REQ-4: after persisting a card for conversation A, switching to B (empty)
    and back to A rehydrates the card from the persistence store.

The `_resolve_card_identity(task_id, origin)` contract (agent_kernel.py:7748):
  a. task_id already registered -> same card_id, relation "continues"
     (the known early-skeleton + DER-queue double emit for one task);
  b. origin != "initial" and an active card exists -> register the new task_id
     against the ACTIVE card and continue it;
  c. otherwise -> mint `card_{task_id}`, register it, make it active, "new".

So a follow-up that "continues" is driven by re-emitting the SAME task_id (or
emitting a non-initial origin): the resolution RETURNS relation "continues" and
the SAME card_id. A follow-up that is genuinely "new" is a fresh task_id with
origin "initial": it RETURNS relation "new" and a DISTINCT card_id.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.conversation_context_store import (
    CardState,
    CardStepSnapshot,
    ConversationContextStore,
)


def _bare_kernel(session_id: str) -> AgentKernel:
    """A REAL AgentKernel object carrying only the state `_resolve_card_identity`
    needs — constructed via `__new__` so the heavy `__init__` side effects
    (LFM model warm-up thread, ModelRouter, etc.) never run in a test. The
    method under test is the real production code, called on a minimal-but-real
    instance (the task's "callable without a full kernel" path)."""
    kern = AgentKernel.__new__(AgentKernel)
    kern.conversation_id = session_id
    kern._card_by_task = {}
    kern._active_card_id = None
    kern._CARD_REGISTRY_CAP = 200
    return kern


@pytest.fixture
def kernel():
    return _bare_kernel("test_continue_vs_branch")


@pytest.fixture
def store():
    """Isolated store backed by a tmp_path SQLite DB — never touches
    data/databases/conversation_contexts.db."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="iris_test_continue_branch_"))
    db_path = tmp_dir / "test_contexts.db"
    s = ConversationContextStore(db_path=db_path)
    yield s
    s.close()
    shutil.rmtree(str(tmp_dir), ignore_errors=True)


def _make_card(card_id: str, conversation_id: str) -> CardState:
    return CardState(
        card_id=card_id,
        conversation_id=conversation_id,
        card_relation="new",
        plan_title="Research the weather",
        mode="agentic",
        steps=[
            CardStepSnapshot(id="s1", description="Search", status="done", tool_name="web_search"),
            CardStepSnapshot(id="s2", description="Summarize", status="done"),
        ],
        current_step=2,
        total_steps=2,
        terminal_state="done",
    )


class TestContinueReusesSameCard:
    """REQ-3: a follow-up that CONTINUES an existing card must reuse the SAME
    card — the second card must NOT appear. This is the whole point of REQ-3."""

    def test_follow_up_continues_reuses_same_card(self, kernel):
        """Two task:start events for the SAME task_id: the first resolves
        relation "new" and mints the card; the second resolves relation
        "continues" and returns the IDENTICAL card_id — no second card."""
        # First task:start — relation "initial" -> mints the card.
        first_card_id, first_relation = kernel._resolve_card_identity("task_1", "initial")
        assert first_relation == "new"

        # Second task:start for the SAME task_id -> resolves "continues".
        second_card_id, second_relation = kernel._resolve_card_identity("task_1", "initial")
        assert second_relation == "continues"
        # RIPPLE: the resolved card_id is IDENTICAL — the second card must NOT appear.
        assert second_card_id == first_card_id
        # Only ONE card exists in the registry's set of values.
        assert len(set(kernel._card_by_task.values())) == 1

    def test_continue_via_non_initial_origin_reuses_active_card(self, kernel):
        """A follow-up task with a non-initial origin (e.g. a sub-loop split)
        also CONTINUES the active card — a branch WITHIN a card, never a
        second card (REQ-3 edge case)."""
        parent_id, parent_relation = kernel._resolve_card_identity("parent_task", "initial")
        assert parent_relation == "new"

        child_id, child_relation = kernel._resolve_card_identity("child_task", "sub_loop_split")
        assert child_relation == "continues"
        assert child_id == parent_id
        # Still exactly one card — no second card appeared.
        assert len(set(kernel._card_by_task.values())) == 1


class TestNewRelationCreatesDistinctCard:
    """REQ-3: a genuinely new follow-up (relation "new") must create a second,
    DISTINCT card."""

    def test_new_relation_creates_distinct_second_card(self, kernel):
        first_id, first_relation = kernel._resolve_card_identity("task_a", "initial")
        second_id, second_relation = kernel._resolve_card_identity("task_b", "initial")

        assert first_relation == "new"
        assert second_relation == "new"
        assert second_id != first_id  # DISTINCT second card
        assert len(set(kernel._card_by_task.values())) == 2


class TestRehydrationAcrossSwitch:
    """REQ-4: switching conversation context does not lose a conversation's
    card; switching back rehydrates it from the persistence store."""

    def test_card_rehydrates_after_switch_away_and_back(self, store):
        """Persist a card for conv A, "switch" to conv B (empty), switch back
        to A — the persistence store returns the card (rehydration)."""
        assert store.save_card(_make_card("card_a", "conv_a")) is True

        # "Switch" to conversation B — empty (A's card is not visible there).
        assert store.get_cards_for_conversation("conv_b") == []

        # "Switch back" to A — the card rehydrates from the persistence store.
        restored = store.get_cards_for_conversation("conv_a")
        assert len(restored) == 1
        assert restored[0].card_id == "card_a"
        assert restored[0].plan_title == "Research the weather"
        assert [s.id for s in restored[0].steps] == ["s1", "s2"]

    def test_switch_does_not_lose_first_conversations_card(self, store):
        store.save_card(_make_card("card_a", "conv_a"))
        store.save_card(_make_card("card_b", "conv_b"))

        # Switching to B and back to A: B never sees A's card, A still has it.
        assert [c.card_id for c in store.get_cards_for_conversation("conv_b")] == ["card_b"]
        assert [c.card_id for c in store.get_cards_for_conversation("conv_a")] == ["card_a"]

    def test_kernel_persist_snapshot_rehydrates_after_switch(self):
        """Drive the kernel's REAL persistence helper end to end:
        `_persist_card_snapshot` -> `enqueue_card_write` -> CardWriteQueue
        (background thread) -> `store.save_card`, with the singleton store
        pointed at a tmp DB. Then switch away/back and assert the card
        rehydrates — the same path the DER emit sites use at task:start."""
        import backend.agent.conversation_context_store as _ccs

        tmp_dir = Path(tempfile.mkdtemp(prefix="iris_test_kernel_persist_"))
        _orig_store = _ccs._store_instance
        try:
            tmp_store = _ccs.ConversationContextStore(db_path=tmp_dir / "test_contexts.db")
            _ccs._store_instance = tmp_store
            _ccs.reset_card_write_queue_for_testing()

            kernel = _bare_kernel("test_kernel_persist")
            kernel.conversation_id = "conv_a"
            kernel._persist_card_snapshot(
                card_id="card_a",
                conversation_id="conv_a",
                card_relation="new",
                plan_title="Research the weather",
                mode="agentic",
                steps=[
                    {"id": "s1", "description": "Search", "status": "done", "toolName": "web_search"},
                    {"id": "s2", "description": "Summarize", "status": "done"},
                ],
                total_steps=2,
                terminal_state="done",
            )
            # The write queue is a background thread — block until drained.
            assert _ccs.get_card_write_queue().wait_idle(timeout=3.0), \
                "card write never drained from the background queue"

            # Switch to conv B (empty), switch back to A -> rehydrates.
            assert tmp_store.get_cards_for_conversation("conv_b") == []
            restored = tmp_store.get_cards_for_conversation("conv_a")
            assert len(restored) == 1
            assert restored[0].card_id == "card_a"
            assert restored[0].plan_title == "Research the weather"
            assert [s.id for s in restored[0].steps] == ["s1", "s2"]
        finally:
            _ccs._store_instance = _orig_store
            _ccs.reset_card_write_queue_for_testing()
            tmp_store.close()
            shutil.rmtree(str(tmp_dir), ignore_errors=True)