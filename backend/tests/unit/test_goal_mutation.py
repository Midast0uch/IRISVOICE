"""T17 (REQ-1 AC1.3): Real-time goal mutation — user voice/text follow-ups
land on the active goal WITHOUT restarting the in-flight plan.

REQ-1 AC3 edge cases: the goal gets mutated mid-flight (open plan), late
arrivals after the plan closes are ignored (no zombie goals), mutations are
scoped per conversation (one conversation's follow-up can't bleed into
another's goal).
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.core_models import GoalAnatomy, TaskType


class _FakeRouter:
    def reply(self, prompt: str, **kw):
        return None


def _kern() -> AgentKernel:
    k = AgentKernel.__new__(AgentKernel)
    k._router = _FakeRouter()
    return k


def test_mid_run_followup_mutates_in_place():
    """A follow-up message must mutate the running goal, not spawn a fork."""
    k = _kern()
    # Seed a task in-flight
    conv_id = "conv-a"
    k._set_active_goal_for(conv_id, GoalAnatomy(
        objective="get price", task_type=TaskType.DATA_EXTRACTION,
        fields=["price"],
    ))
    before_id = id(k._get_active_goal_for(conv_id))
    k.apply_follow_up(conv_id, "also check availability")
    after = k._get_active_goal_for(conv_id)
    assert id(after) == before_id


def test_mutation_attaches_directive_to_active_goal():
    k = _kern()
    conv_id = "conv-x"
    k._set_active_goal_for(conv_id, GoalAnatomy(
        objective="find the price", fields=["price"],
    ))
    k.apply_follow_up(conv_id, "please also grab the warranty")
    goal = k._get_active_goal_for(conv_id)
    assert "warranty" in (goal.fields or []) or "warranty" in str(goal.memory_anchors or {})


def test_follow_up_blocked_when_no_active_goal():
    """Edge case: no in-flight task = no goal to mutate; the follow-up must
    be handled as a NEW plan, not silently swallowed."""
    k = _kern()
    conv_id = "conv-empty"
    assert k._get_active_goal_for(conv_id) is None
    with pytest.raises((LookupError, ValueError)):
        # An apply call on a missing goal must surface an error — never
        # mutate a goal that doesn't exist and silently drop the request.
        k.apply_follow_up(conv_id, "add sources")


def test_conversation_scope_isolation():
    """Conv-a follow-up must not mutate conv-b's goal."""
    k = _kern()
    k._set_active_goal_for("a", GoalAnatomy(objective="price"))
    k._set_active_goal_for("b", GoalAnatomy(objective="batteries"))
    k.apply_follow_up("a", "also check specs")
    ga = k._get_active_goal_for("a")
    gb = k._get_active_goal_for("b")
    assert "specs" in str(ga) or "specs" in str((ga.fields or []))
    assert "specs" not in str(gb) and "specs" not in str((gb.fields or []))


def test_mutation_log_keeps_sequence_for_review():
    """Each mutation is recorded so later review can audit who changed what."""
    k = _kern()
    k._set_active_goal_for("c", GoalAnatomy(objective="base"))
    k.apply_follow_up("c", "add warranty data")
    goal = k._get_active_goal_for("c")
    log = goal.memory_anchors.get("mutation_log", [])
    assert len(log) >= 1
    assert "warranty" in log[-1]