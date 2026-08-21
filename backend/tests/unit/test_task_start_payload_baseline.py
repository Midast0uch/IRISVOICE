"""BASELINE — Wave 0, specs/task-card-v2-liquid-ink.

Pins behavior as of 2026-08-19, including the defects the baseline was
written to characterize. T1 (REQ-3) has now landed and INVERTED this file:
`_task_start_payload` is additive — the original seven keys are unchanged in
name, meaning and pass-through behavior, and `card_id` / `card_relation` /
`conversation_id` are now PRESENT rather than absent. Keeping this an exact
set-equality assertion is what keeps the addition provably additive rather
than a silent rename or drop elsewhere.

Inverted by: T1 (landed)

RE-INVERTED 2026-08-21 by cli-workspace-unification T9a (REQ-5 AC1 / CT-1),
CALLED OUT DELIBERATELY: `agent_id` (kernel session identity) and
`project_id` (active project folder scope) join the SAME single construction
point, additive only — the multi-agent Kanban tags are backend-emitted and
the frontend never fabricates them. WHAT THIS TEST ASSERTS IS UNCHANGED:
exact set equality, which is what proves T9a was additive rather than a
rewrite. Ten keys -> twelve.

RE-INVERTED 2026-08-21, session 244 (card↔response inline join), CALLED OUT
DELIBERATELY: `turn_id` (the kernel's current response turn id,
`self._current_turn_id`) joins additively — the SAME id space as the
assistant message id on the frontend, so a card can render INLINE with its
response (the join documents already use). WHAT THIS TEST ASSERTS IS
UNCHANGED: exact set equality. Twelve keys -> thirteen.
"""

import pytest

from backend.agent.agent_kernel import AgentKernel

EXPECTED_KEYS = {
    "task_id",
    "description",
    "plan_title",
    "mode",
    "steps",
    "total_steps",
    "origin",
    "card_id",
    "card_relation",
    "conversation_id",
    "agent_id",
    "project_id",
    "turn_id",
}


def _call(**overrides):
    kwargs = dict(
        task_id="task_123",
        description="Do the thing",
        plan_title="The Plan",
        mode="agentic",
        steps=[{"id": "s1", "description": "step one", "status": "pending"}],
        total_steps=1,
        origin="initial",
        card_id="card_task_123",
        card_relation="new",
        conversation_id="conv_1",
    )
    kwargs.update(overrides)
    return AgentKernel._task_start_payload(**kwargs)


class TestExactKeySet:
    def test_exact_key_set(self):
        """CT-1 (post-T9a): the payload's key set is now exactly these TWELVE
        keys — the original seven, unchanged, plus card_id / card_relation /
        conversation_id (T1) plus agent_id / project_id (cli-workspace-
        unification T9a). No more, no less."""
        payload = _call()
        assert set(payload.keys()) == EXPECTED_KEYS


class TestMultiAgentTagsPresent:
    """cli-workspace-unification T9a: the Kanban tags are part of the
    payload contract. Direct calls default them to None (the caller —
    `_multiagent_tags()` — supplies the kernel-resolved values); consumers
    fall back to conversationId-only keying when project_id is None."""

    def test_agent_id_defaults_to_none_and_passes_through(self):
        assert _call()["agent_id"] is None
        assert _call(agent_id="sess_abc")["agent_id"] == "sess_abc"

    def test_project_id_defaults_to_none_and_passes_through(self):
        assert _call()["project_id"] is None
        assert _call(project_id="proj_1")["project_id"] == "proj_1"


class TestNewKeysPresent:
    def test_card_id_present_and_passes_through(self):
        payload = _call(card_id="card_xyz")
        assert payload["card_id"] == "card_xyz"

    def test_card_relation_present_and_passes_through(self):
        payload = _call(card_relation="continues")
        assert payload["card_relation"] == "continues"

    def test_conversation_id_present_and_passes_through(self):
        payload = _call(conversation_id="conv_42")
        assert payload["conversation_id"] == "conv_42"

    def test_conversation_id_may_be_none(self):
        """The kernel's conversation_id can legitimately be None in some
        call paths; the payload must carry that through rather than
        requiring a truthy value."""
        payload = _call(conversation_id=None)
        assert payload["conversation_id"] is None


class TestPassThrough:
    def test_scalar_values_pass_through_verbatim(self):
        payload = _call(
            task_id="task_abc",
            description="A specific description",
            plan_title="A specific title",
            mode="full",
            total_steps=7,
            origin="sub_loop_split",
        )
        assert payload["task_id"] == "task_abc"
        assert payload["description"] == "A specific description"
        assert payload["plan_title"] == "A specific title"
        assert payload["mode"] == "full"
        assert payload["total_steps"] == 7
        assert payload["origin"] == "sub_loop_split"

    def test_steps_pass_through_by_identity(self):
        """No copying or transformation — the same list object comes back
        under the 'steps' key."""
        steps = [{"id": "s1", "description": "x", "status": "pending"}]
        payload = _call(steps=steps)
        assert payload["steps"] is steps


class TestOriginIsFreeFormToday:
    """Origin is documented as one of "initial" / "sub_loop_split" /
    "user_steering", but nothing in _task_start_payload validates it — any
    string passes through unchanged."""

    @pytest.mark.parametrize(
        "origin_value",
        ["initial", "sub_loop_split", "user_steering", "totally_made_up_origin"],
    )
    def test_arbitrary_origin_passes_through_unvalidated(self, origin_value):
        payload = _call(origin=origin_value)
        assert payload["origin"] == origin_value
