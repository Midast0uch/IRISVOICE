"""REQ-15 (T25) contract pins: mid-task steering / pause / stop channels.

Covers:
  - AC1: a mid-task message is made available to the running loop at the
    NEXT step boundary, never mid-step (the inbox is the ONLY queue and
    ``_der_check_steering`` is the ONLY consumer, driven at the boundary).
  - AC2: a steering message revises the remaining plan via REQ-14's
    revision channel (task:start re-emit with origin="user_steering"),
    without aborting the task and without poisoning ``failed_ids``.
  - AC3: an explicit stop aborts at the next step boundary (the boundary
    consumer latches stop; the loop breaks on it and the outcome path
    persists ``cancelled``).
  - AC6: three distinct, independently observable channels; a stop is
    latched BEFORE any steering work and suppresses the revision — a stop
    is never delayed behind an unrelated steering message's processing.

The boundary consumer is driven directly on a minimal ``AgentKernel``
instance with a REAL ``DirectorQueue``, mirroring the loop's call site; the
re-plan (``_plan_task``) is a deterministic seam (no LLM).
"""

import types

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import DirectorQueue, QueueItem
from backend.agent.event_bus import IRISStreamEvent
from backend.agent.steering import get_steering_inbox
from backend.core_models import ExecutionPlan, PlanStep


# ── fixtures / helpers ────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_inbox():
    get_steering_inbox().clear()
    yield
    get_steering_inbox().clear()


class _CapturingBus:
    def __init__(self):
        self.events = []

    def emit(self, event, *, data=None, **kwargs):
        self.events.append((event, data, kwargs))


def _make_kernel():
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "conv_steer_test"
    k.session_id = "conv_steer_test"
    k._der_stop_requested = False
    k._der_pause_requested = False
    k._canned_plan = ExecutionPlan(
        plan_id="plan-rev",
        original_task="Steered task",
        strategy="do_it_myself",
        reasoning="user steering",
        plan_title="Revised plan",
        steps=[
            PlanStep(step_id="rev-1", step_number=1, description="revised step A"),
            PlanStep(step_id="rev-2", step_number=2, description="revised step B"),
        ],
    )
    # Deterministic re-plan seam — the real _plan_task never runs.
    k._plan_task = types.MethodType(lambda self, text, **kw: self._canned_plan, k)
    return k


def _make_queue(*descriptions):
    q = DirectorQueue(objective="original objective")
    for i, d in enumerate(descriptions, start=1):
        q.add_item(QueueItem(step_id=f"step-{i}", step_number=i, description=d))
    return q


# ── AC1: next-boundary availability, never mid-step ───────────────────────


def test_records_stay_queued_until_the_next_boundary_consumer(monkeypatch):
    """AC1: a record pushed mid-step is NOT consumed until _der_check_steering
    runs (the boundary call). No mid-step code path reads the inbox."""
    k = _make_kernel()
    monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: _CapturingBus())
    get_steering_inbox().push("steer", "sess", text="later")

    # Mid-step: still pending — nothing has consumed it.
    assert get_steering_inbox().pending("sess") == 1

    # Next boundary: consumed exactly once.
    q = _make_queue("original A")
    result = k._der_check_steering("sess", plan=k._canned_plan, queue=q)
    assert result is not None
    assert result["steer"] == "later"
    assert result["revised"] is True
    assert get_steering_inbox().pending("sess") == 0


def test_no_records_returns_none_and_changes_nothing():
    k = _make_kernel()
    q = _make_queue("step one", "step two")
    result = k._der_check_steering("sess", plan=k._canned_plan, queue=q)
    assert result is None
    assert k._der_stop_requested is False
    assert k._der_pause_requested is False
    assert [i.step_id for i in q.items] == ["step-1", "step-2"]


# ── AC2: steering revises the plan via REQ-14's revision channel ──────────


def test_steer_revises_remaining_plan_via_req14_channel(monkeypatch):
    k = _make_kernel()
    q = _make_queue("original A", "original B")
    bus = _CapturingBus()
    monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: bus)
    get_steering_inbox().push("steer", "sess", text="Do it differently")

    result = k._der_check_steering("sess", plan=k._canned_plan, queue=q)

    assert result["steer"] == "Do it differently"
    assert result["revised"] is True
    assert result["stop"] is False
    # AC2: remaining pending steps are REPLACED (fresh "steer-N" items whose
    # ids cannot collide with the original plan's ids), not aborted.
    pending = [i.step_id for i in q.items if i.step_id not in q.completed_ids]
    assert pending == ["steer-1", "steer-2"]
    assert "step-1" not in pending and "step-2" not in pending
    # Replacement must NOT be recorded as a failure (the task itself did not
    # fail — the plan was redirected).
    assert not q.failed_ids
    # REQ-14 revision signal with origin="user_steering" (REQ-18 AC3 origin).
    starts = [e for e in bus.events if e[0] is IRISStreamEvent.TASK_START]
    assert len(starts) == 1
    payload = starts[0][1]
    assert payload["origin"] == "user_steering"
    # The payload carries exactly the revised (pending) steps, and the queue
    # agrees — the frontend merge-by-id sees the same ids.
    assert [s["id"] for s in payload["steps"]] == pending
    assert payload["total_steps"] == 2
    # The revision carries the queue's CURRENT mode (T23 _rev_mode semantics).
    assert payload["mode"] == "quick"


def test_multiple_steers_at_one_boundary_last_text_wins(monkeypatch):
    k = _make_kernel()
    q = _make_queue("original A")
    bus = _CapturingBus()
    monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: bus)
    get_steering_inbox().push("steer", "sess", text="first idea")
    get_steering_inbox().push("steer", "sess", text="latest instruction")

    result = k._der_check_steering("sess", plan=k._canned_plan, queue=q)

    assert result["steer"] == "latest instruction"
    assert result["revised"] is True
    # One REVISION, not two (the consumed records also emit steering:ack
    # "considered" — AC5/T26 — which is not counted here).
    assert len([e for e in bus.events if e[0] is IRISStreamEvent.TASK_START]) == 1


def test_whitespace_steer_is_consumed_without_revision(monkeypatch):
    k = _make_kernel()
    q = _make_queue("original A")
    bus = _CapturingBus()
    monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: bus)
    get_steering_inbox().push("steer", "sess", text="   ")

    result = k._der_check_steering("sess", plan=k._canned_plan, queue=q)

    assert result["steer"] is None
    assert result["revised"] is False
    # No revision — but the record WAS consumed, so AC5 acks it "considered".
    assert not [e for e in bus.events if e[0] is IRISStreamEvent.TASK_START]
    assert [i.step_id for i in q.items] == ["step-1"]  # unchanged


# ── AC3: explicit stop aborts at the next boundary ────────────────────────


def test_stop_latches_and_returns_stop(monkeypatch):
    k = _make_kernel()
    q = _make_queue("original A", "original B")
    monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: _CapturingBus())
    get_steering_inbox().push("stop", "sess", text="")

    result = k._der_check_steering("sess", plan=k._canned_plan, queue=q)

    assert result["stop"] is True
    assert k._der_stop_requested is True
    # Nothing was revised — the loop's boundary handler breaks on stop and
    # the outcome path persists `cancelled`.
    assert result["revised"] is False
    assert [i.step_id for i in q.items] == ["step-1", "step-2"]


# ── AC6: channel independence — stop is never delayed behind steering ─────


def test_stop_is_not_delayed_behind_a_steering_message(monkeypatch):
    k = _make_kernel()
    q = _make_queue("original A")
    bus = _CapturingBus()
    monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: bus)
    # Steering arrives first in the queue, stop second — at the SAME boundary.
    get_steering_inbox().push("steer", "sess", text="redirect me")
    get_steering_inbox().push("stop", "sess", text="")

    result = k._der_check_steering("sess", plan=k._canned_plan, queue=q)

    assert result["stop"] is True
    assert k._der_stop_requested is True
    # AC6: the stop is latched before any steering work and the revision is
    # suppressed entirely — the stop is NOT delayed behind the re-plan.
    assert result["revised"] is False
    # The only emits are AC5 steering:ack "considered" — never a revision.
    assert not [e for e in bus.events if e[0] is IRISStreamEvent.TASK_START]


def test_pause_is_a_distinct_channel_that_does_not_revise(monkeypatch):
    k = _make_kernel()
    q = _make_queue("original A")
    bus = _CapturingBus()
    monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: bus)
    get_steering_inbox().push("pause", "sess", text="")

    result = k._der_check_steering("sess", plan=k._canned_plan, queue=q)

    # A pause is NOT a stop and NOT a steer (AC6) — latched only.
    assert result["pause"] is True
    assert result["stop"] is False
    assert result["steer"] is None
    assert k._der_pause_requested is True
    assert result["revised"] is False
    # No revision — only the AC5 "considered" ack for the consumed pause.
    assert not [e for e in bus.events if e[0] is IRISStreamEvent.TASK_START]
    assert [i.step_id for i in q.items] == ["step-1"]  # unchanged
