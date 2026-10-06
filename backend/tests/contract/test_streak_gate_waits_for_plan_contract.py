"""The streak gate's coverage arms wait until the original plan has settled.

Live 2026-10-06 (developer turn, conv-940): two read nodes settled at
C=0.667 while the planned summary node (s3) was still pending; the coverage
RATE arm fired ("coverage_rate:rho=0.0000<0.05"), and two re-plans ran the
same reads again: 10 steps for a 3-goal plan. "No progress toward the facts"
can only be judged once the plan has had its chance; the streak arms
(repeat / empty / mismatch / topology) still fire at any time.

Guard: fails on the old gate (it fired with s3 pending).
"""
from __future__ import annotations

from backend.agent.der_loop import DirectorQueue, QueueItem


class _Kernel:
    """Stand-in binding the REAL gate; the re-plan is recorded, never run."""

    def __init__(self, coverage: float = 0.667):
        from backend.agent.agent_kernel import AgentKernel

        self.conversation_id = "conv_gate"
        self.steering_calls: list = []
        self._der_streak_gate = AgentKernel._der_streak_gate.__get__(self)
        self._der_apply_steering = self._record
        # Coverage below 1, unmoved for one settled node, rate 0: the rate arm's
        # firing condition (GOAL_STALL_RATE 0.05). No contract object, so
        # _goal_contract_met is False and the gate evaluates.
        self._goal_contract_state = {"C": coverage, "unmoved": 1, "rho": 0.0}

    def _record(self, text, _session, plan, queue, budget_deadline=None):
        self.steering_calls.append(text)
        return True


def _plan(n: int = 3):
    from backend.core_models import ExecutionPlan, PlanStep

    return ExecutionPlan(
        plan_id="p1", original_task="read two files and summarise them",
        strategy="do_it_myself", reasoning="r", plan_title="read",
        steps=[PlanStep(step_id=f"s{i}", step_number=i, description=f"step {i}")
               for i in range(1, n + 1)],
    )


def _queue(settled: int, n: int = 3) -> DirectorQueue:
    from backend.agent.tool_envelope import ToolResultEnvelope

    items = []
    for i in range(1, n + 1):
        it = QueueItem(step_id=f"s{i}", step_number=i, description=f"step {i}")
        if i <= settled:  # a healthy settled node: new, matched
            it.envelope = ToolResultEnvelope(
                status="success", summary="ok", match="matched", novelty="new",
                stuck_shape="none", step_id=f"s{i}",
            )
        items.append(it)
    q = DirectorQueue(objective="obj", items=items)
    for it in items[:settled]:
        q.completed_ids.append(it.step_id)
    return q


def test_coverage_arms_wait_while_a_planned_step_is_pending():
    k = _Kernel()
    assert not k._der_streak_gate(_plan(), _queue(settled=2), "sess"), (
        "the gate re-planned while the plan's own step s3 was still pending"
    )
    assert k.steering_calls == []


def test_coverage_arm_still_fires_once_the_plan_has_settled():
    k = _Kernel()
    assert k._der_streak_gate(_plan(), _queue(settled=3), "sess")
    assert len(k.steering_calls) == 1
    assert "coverage_rate" in k.steering_calls[0]
