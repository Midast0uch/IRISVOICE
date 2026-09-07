"""BT (vision-goal-directed-search T31 / REQ-1 AC1.3): real-time goal
mutation lands on the LIVE GoalAnatomy — never a side plan.

Drives the REAL `AgentKernel.apply_follow_up` (built via `object.__new__`
so no kernel boot is needed; `_active_goals` is the only state touched)
and asserts the EFFECT: the SAME instance gains the new field and the
mutation is audit-logged in `memory_anchors`.
"""
from __future__ import annotations

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.core_models import GoalAnatomy, TaskType


def _kernel_with_goal(cid: str, goal: GoalAnatomy) -> AgentKernel:
    kernel = object.__new__(AgentKernel)
    kernel._active_goals = {cid: goal}
    return kernel


def test_follow_up_mutates_the_live_goal_in_place():
    goal = GoalAnatomy(
        objective="Find the RTX 5090 launch price",
        task_type=TaskType.DATA_EXTRACTION,
        fields=["price"],
    )
    kernel = _kernel_with_goal("conv-1", goal)

    assert kernel.apply_follow_up("conv-1", "also need the battery life") is True

    assert kernel._active_goals["conv-1"] is goal  # same instance, not a branch
    assert "battery" in (goal.fields or [])
    assert "price" in (goal.fields or [])  # prior fields retained
    log = (goal.memory_anchors or {}).get("mutation_log") or []
    assert log and "battery" in log[-1].lower()


def test_follow_up_with_no_active_goal_raises():
    kernel = object.__new__(AgentKernel)
    kernel._active_goals = {}
    with pytest.raises(LookupError):
        kernel.apply_follow_up("conv-missing", "need the price")
