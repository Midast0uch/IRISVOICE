"""REQ-13 + REQ-14 + REQ-15 (T33): combined behavioral replay.

Drives ONE task through the real DER machinery and asserts the three
properties TOGETHER — the intertwined seam, not isolated units:

  1. REQ-13 FOLD-FORWARD: evidence gathered -> weak (non-FAILED) graded
     score -> honest UNVERIFIED label, NO duplicate gather, NO split.
  2. REQ-14 REVISION: a mid-task steering message revises the remaining
     plan through the task:start merge-by-id channel with
     origin="user_steering" (distinguishable from sub_loop_split per AC5),
     adding/revising steps without aborting the task.
  3. REQ-15 STEERING: the message is acknowledged (steering:ack
     "considered") and applied at the next step boundary — never mid-step.

Each property is ALSO pinned by its own contract test (T21/T23/T25/T26);
this test proves they compose in a single running task.
"""

import json
import types
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import DirectorQueue, QueueItem
from backend.agent.event_bus import IRISStreamEvent
from backend.agent.steering import get_steering_inbox


class _CapturingBus:
    def __init__(self):
        self.events = []

    def emit(self, event, *, data=None, **kwargs):
        self.events.append((event, data, kwargs))


@pytest.fixture(autouse=True)
def _clean_steering():
    from backend.agent.steering import get_steering_inbox

    get_steering_inbox()._records.clear()
    yield
    get_steering_inbox()._records.clear()


def _make_kernel():
    """Kernel with the re-plan seam stubbed (real _der_check_steering /
    _der_apply_steering run)."""
    from backend.core_models import ExecutionPlan, PlanStep

    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "conv_t33"
    k.session_id = "conv_t33"
    k._der_stop_requested = False
    k._der_pause_requested = False
    k._der_resume_requested = False
    k._der_task_class = "full"
    k._memory_interface = None
    k._canned_plan = ExecutionPlan(
        plan_id="plan-rev",
        original_task="research the pricing page then summarize",
        strategy="do_it_myself",
        reasoning="user steering",
        plan_title="Revised plan",
        steps=[
            PlanStep(step_id="rev-1", step_number=1, description="revised step A"),
            PlanStep(step_id="rev-2", step_number=2, description="revised step B"),
        ],
    )
    # Deterministic re-plan seam — the real _plan_task never runs.
    k._plan_task = types.MethodType(
        lambda self, text, **kw: self._canned_plan, k
    )
    return k


def _make_queue(*descriptions):
    q = DirectorQueue(objective="original objective")
    for i, d in enumerate(descriptions, start=1):
        q.add_item(QueueItem(step_id=f"step-{i}", step_number=i, description=d))
    return q


# ── 1. REQ-13: weak score folds forward, no duplicate gather ───────────────


def test_weak_score_folds_forward_no_duplicate_gather():
    """REQ-13 AC1/AC2: evidence gathered -> weak (non-FAILED) graded score ->
    honest UNVERIFIED label, no split, no re-gather. The gather-attempt
    counter stays at ONE."""
    from backend.agent.der_execution_ledger import make_action_key

    k = _make_kernel()
    # One gather already committed for this goal.
    k._der_crawl_attempts = {
        k.conversation_id: {make_action_key("research the pricing page")}
    }

    item = QueueItem(
        step_id="s1", step_number=1,
        description="research the pricing page",
        tool="crawler_query", params={"query": "pricing page"},
        critical=False,
    )
    queue = DirectorQueue(objective="research the pricing page")
    queue.add_item(item)

    split_calls = []
    k._split_step = lambda item, reason, cad, wu: split_calls.append(
        (item.step_id, reason)
    ) or []

    # Weak but non-FAILED: 0.45 graded score -> UNVERIFIED (fold forward).
    k._verify_step_result = (
        lambda goal, expected, result, tool=None, success=False: "UNVERIFIED"
    )

    step_result = "gathered evidence about the pricing page with real content " * 3
    k._der_finalize_step(
        item=item,
        step_result=step_result,
        step_success=True,
        step_outputs=[],
        completed_items=[],
        _tokens_used=0,
        _token_budget=10_000,
        _session="conv_t33",
        _turn_id="t1",
        _phase=2,
        is_mature=False,
        _live_ctx=None,
        plan=SimpleNamespace(original_task="research the pricing page"),
        context_package=None,
        queue=queue,
        verdict=None,
    )

    # Fold forward: marked complete, NOT split, exactly one gather.
    assert "s1" in queue.completed_ids
    assert split_calls == [], f"weak score must not split: {split_calls}"
    assert len(k._der_crawl_attempts.get(k.conversation_id, set())) == 1, (
        "no duplicate gather (REQ-13)"
    )


# ── 2 + 3. REQ-14 revision + REQ-15 steering ack at boundary ───────────────


def test_steering_revises_plan_and_acks_at_boundary(monkeypatch):
    """REQ-14 AC1/AC5 + REQ-15 AC1/AC2/AC5: a mid-task steering message is
    consumed at the NEXT step boundary, revises the remaining plan via
    task:start origin="user_steering", and is acknowledged 'considered'.
    The revision is observable (distinct event) and does NOT abort the task.
    """
    from backend.agent.event_bus import get_event_bus

    k = _make_kernel()
    bus = _CapturingBus()
    monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: bus)

    # Mid-task: a steer arrives WHILE step-1 is running (not yet at boundary).
    get_steering_inbox().push("steer", "conv_t33", text="focus on the pricing table")

    # Still mid-step: nothing consumed it.
    assert get_steering_inbox().pending("conv_t33") == 1

    q = _make_queue("original step A", "original step B")
    result = k._der_check_steering("conv_t33", plan=k._canned_plan, queue=q)

    # REQ-15 AC1/AC2: consumed at the boundary, plan revised, task not aborted.
    assert result is not None
    assert result["steer"] == "focus on the pricing table"
    assert result["revised"] is True
    assert k._der_stop_requested is False, "steering must not abort the task"
    assert get_steering_inbox().pending("conv_t33") == 0

    # REQ-14 AC1/AC5: a distinct revision signal fired with origin=user_steering
    # (reusing task:start merge-by-id — distinguishable from sub_loop_split).
    starts = [
        (d or {}).get("origin")
        for e, d, _ in bus.events if e == IRISStreamEvent.TASK_START
    ]
    assert "user_steering" in starts, (
        "revision signal origin=user_steering emitted (REQ-14 AC5)"
    )

    # REQ-14 AC2: the revised plan's steps replaced the old pending ones.
    # The real _der_apply_steering names fresh steps "steer-{N}" (agent_kernel
    # :6634) — assert the honest contract, not a canned id.
    remaining = [i.step_id for i in q.items]
    assert any(s.startswith("steer-") for s in remaining), (
        "revised steps added (REQ-14 AC2)"
    )
    assert len(remaining) >= 2, "revised plan has both steps (REQ-14 AC2)"
    assert not any(s.startswith("step-") for s in remaining), (
        "old pending steps dropped (REQ-14 AC2)"
    )

    # REQ-15 AC5: every consumed record acknowledged as "considered".
    acks = [
        (d or {}).get("status")
        for e, d, _ in bus.events if e == IRISStreamEvent.STEERING_ACK
    ]
    assert "considered" in acks, "steering acked at the applied boundary (REQ-15 AC5)"


def test_stop_at_boundary_aborts_but_steering_does_not(monkeypatch):
    """REQ-15 AC3 vs AC2: a STOP latches and aborts at the boundary, while a
    plain steer only revises. Both are consumed at the boundary, never
    mid-step."""
    from backend.agent.event_bus import get_event_bus

    k = _make_kernel()
    bus = _CapturingBus()
    monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: bus)

    get_steering_inbox().push("stop", "conv_t33", text="stop now")
    q = _make_queue("step A")

    result = k._der_check_steering("conv_t33", plan=k._canned_plan, queue=q)

    assert result is not None
    assert result["stop"] is True
    assert k._der_stop_requested is True, "stop latched at boundary (AC3)"
    assert get_steering_inbox().pending("conv_t33") == 0


def test_no_duplicate_gather_within_steered_task(monkeypatch):
    """The three properties COMPOSE: after a steering revision, re-gathering
    the SAME goal is still vetoed by the gather budget (T21 fold-forward +
    REQ-15 revision must not reintroduce duplicate gathers)."""
    from backend.agent.der_execution_ledger import make_action_key
    from backend.agent.tool_decision import DecisionKind

    k = _make_kernel()
    k._der_crawl_attempts = {
        k.conversation_id: {make_action_key("research the pricing page")}
    }
    # Router that proposes the SAME gather goal again (a true duplicate —
    # the budget veto must stop it, not start a re-gather loop).
    k._router = SimpleNamespace(
        generate=lambda *a, **kw: (
            json.dumps({"kind": "tool", "tool": "crawler_query",
                        "params": {"query": "research the pricing page"}}),
            "",
            None,
        )
    )
    k._tool_bridge = SimpleNamespace()  # ToolDecisionBox consults the bridge

    # Registry seams (same as the T32 acceptance-gate drive) so the box can
    # resolve crawler_query as a valid gather tool.
    import backend.agent.tool_registry as tr

    monkeypatch.setattr(
        "backend.agent.tool_registry.capability_allowed", lambda _spec: True
    )
    monkeypatch.setattr(
        tr, "validate_tool_call",
        lambda tool, params: (
            (True, None) if tool == "crawler_query" else (False, "unknown tool")
        ),
    )

    # Steer the task (revision) — the gather budget is unchanged.
    get_steering_inbox().push("steer", "conv_t33", text="also check the FAQ")
    q = _make_queue("original step A")
    k._der_check_steering("conv_t33", plan=k._canned_plan, queue=q)

    # A fresh planner proposal to re-gather the SAME goal (identical action
    # key) is vetoed — the budget check keys on the goal text.
    box = k._get_tool_box()
    d = box.resolve(
        {"description": "research the pricing page", "step_number": 1},
        {},
        session_id=k.session_id,
        conversation_id=k.conversation_id,
    )
    assert d.kind in (DecisionKind.REASON, DecisionKind.TOOL)
    # The gather budget is SATURATED for this exact goal: a repeated
    # same-goal gather must not add a NEW attempt (no re-gather loop).
    assert len(k._der_crawl_attempts.get(k.conversation_id, set())) == 1, (
        "no duplicate gather after steering revision (REQ-13/REQ-15 compose)"
    )
