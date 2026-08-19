"""Unit tests for `AgentKernel._resolve_card_identity` / `_register_card`
(REQ-3, T2) — specs/task-card-v2-liquid-ink.

Covers the three branches of the resolution rule plus the two hardening
requirements the design calls out:
  - a sub-loop split (and every other non-"initial" origin, including the
    undocumented "amendment" origin) CONTINUES the active card rather than
    branching a second one;
  - the per-kernel `_card_by_task` registry is bounded and evicts the oldest
    insertion first once it hits its cap, rather than growing without limit.
"""

import pytest

from backend.agent.agent_kernel import AgentKernel


@pytest.fixture
def kernel():
    return AgentKernel(session_id="test_card_identity_resolution")


class TestDoubleEmitContinues:
    """(a) task_id already registered -> same card_id, relation 'continues'.
    This is the known early-skeleton + DER-queue double emit for one task
    (REQ-3 edge case: same card_id, relation 'continues', no flicker)."""

    def test_same_task_id_reemitted_with_initial_origin_continues(self, kernel):
        card_id_1, relation_1 = kernel._resolve_card_identity("task_1", "initial")
        card_id_2, relation_2 = kernel._resolve_card_identity("task_1", "initial")

        assert relation_1 == "new"
        assert relation_2 == "continues"
        assert card_id_2 == card_id_1

    def test_card_id_is_derived_from_task_id_not_random(self, kernel):
        card_id, relation = kernel._resolve_card_identity("task_42", "initial")
        assert relation == "new"
        assert card_id == "card_task_42"


class TestNonInitialOriginContinuesActiveCard:
    """(b) origin != 'initial' AND an active card exists -> register the new
    task_id against the ACTIVE card and continue it. Parametrized over every
    documented origin plus the undocumented fourth origin "amendment" — the
    rule is "not initial", not a membership test, so a future fifth origin
    must behave identically."""

    @pytest.mark.parametrize(
        "origin",
        ["sub_loop_split", "user_steering", "amendment", "some_future_origin"],
    )
    def test_non_initial_origin_continues_the_active_card(self, kernel, origin):
        parent_card_id, parent_relation = kernel._resolve_card_identity(
            "parent_task", "initial"
        )
        assert parent_relation == "new"

        child_card_id, child_relation = kernel._resolve_card_identity(
            "child_task", origin
        )

        assert child_relation == "continues"
        assert child_card_id == parent_card_id

    def test_sub_loop_split_is_a_branch_within_the_card_not_a_second_card(
        self, kernel
    ):
        """REQ-3 edge case, stated explicitly: a sub-loop split continues
        the parent card. It must never mint a second card_id."""
        parent_card_id, _ = kernel._resolve_card_identity("parent_task", "initial")
        split_card_id, split_relation = kernel._resolve_card_identity(
            "split_child_task", "sub_loop_split"
        )
        assert split_relation == "continues"
        assert split_card_id == parent_card_id
        # Only one card in the registry's set of values — no branching.
        assert len(set(kernel._card_by_task.values())) == 1

    def test_non_initial_origin_with_no_active_card_still_starts_one(self, kernel):
        """No active card exists yet (a bare kernel) -> falls through to the
        'new' branch rather than crashing or returning an invalid pair."""
        card_id, relation = kernel._resolve_card_identity(
            "orphan_task", "user_steering"
        )
        assert relation == "new"
        assert card_id == "card_orphan_task"


class TestGenuinelyNewTask:
    """(c) neither (a) nor (b) applies -> a fresh card, and it becomes the
    new active card for subsequent non-initial origins."""

    def test_new_initial_task_after_an_unrelated_active_card(self, kernel):
        first_card_id, first_relation = kernel._resolve_card_identity(
            "task_a", "initial"
        )
        second_card_id, second_relation = kernel._resolve_card_identity(
            "task_b", "initial"
        )

        assert first_relation == "new"
        assert second_relation == "new"
        assert second_card_id != first_card_id

    def test_new_active_card_becomes_target_of_later_revisions(self, kernel):
        kernel._resolve_card_identity("task_a", "initial")
        second_card_id, _ = kernel._resolve_card_identity("task_b", "initial")

        # A revision after task_b became active continues task_b's card, not
        # task_a's.
        revision_card_id, revision_relation = kernel._resolve_card_identity(
            "task_b_revision", "sub_loop_split"
        )
        assert revision_relation == "continues"
        assert revision_card_id == second_card_id


class TestRegistryBound:
    """The registry must not grow without limit — oldest insertion evicted
    first once the cap is hit (CLAUDE.md quality check: no unbounded cache)."""

    def test_registry_does_not_grow_past_the_cap(self, kernel):
        cap = kernel._CARD_REGISTRY_CAP
        for i in range(cap + 50):
            kernel._resolve_card_identity(f"task_{i}", "initial")

        assert len(kernel._card_by_task) <= cap

    def test_oldest_entry_is_evicted_first(self, kernel):
        cap = kernel._CARD_REGISTRY_CAP
        for i in range(cap):
            kernel._resolve_card_identity(f"task_{i}", "initial")

        assert "task_0" in kernel._card_by_task

        # One more insertion past the cap must evict the oldest (task_0).
        kernel._resolve_card_identity(f"task_{cap}", "initial")

        assert len(kernel._card_by_task) == cap
        assert "task_0" not in kernel._card_by_task
        assert f"task_{cap}" in kernel._card_by_task


class TestResolutionNeverRaises:
    """Resolution must not raise — a failure to resolve returns a safe
    value and logs, it never breaks a task emit."""

    def test_empty_task_id_returns_a_safe_pair_instead_of_raising(self, kernel):
        card_id, relation = kernel._resolve_card_identity("", "initial")
        assert card_id  # non-empty, usable
        assert relation == "new"
        # An empty task_id is never registered — nothing to key continuation on.
        assert "" not in kernel._card_by_task


class TestCardEnvelope:
    """`_card_envelope` is a pure lookup — it must never register a new
    card, only surface the one already bound to task_id (REQ-3 AC6)."""

    def test_known_task_id_returns_its_card(self, kernel):
        card_id, _ = kernel._resolve_card_identity("task_1", "initial")
        envelope = kernel._card_envelope("task_1")
        assert envelope["card_id"] == card_id
        assert envelope["conversation_id"] == kernel.conversation_id

    def test_unknown_task_id_returns_none_rather_than_inventing_one(self, kernel):
        envelope = kernel._card_envelope("never_seen_task")
        assert envelope["card_id"] is None

    def test_none_task_id_returns_none_without_raising(self, kernel):
        envelope = kernel._card_envelope(None)
        assert envelope["card_id"] is None
