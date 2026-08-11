"""REQ-15 (T26) contract pins: pause/stop lifecycle + acknowledgement/resend.

Covers:
  - AC4: a pause suspends execution at the next step boundary, persists the
    in-progress state (ledger lifecycle "paused" + task:paused), and resumes
    without duplicating completed side effects (completed_ids are the
    persisted state; next_ready skips them). A stop arriving while suspended
    aborts. Steer records arriving while suspended STAY queued and are
    applied at the post-resume boundary — never dropped.
  - AC5: every consumed record emits steering:ack "considered"; the WS layer
    emits steering:ack "queued" on landing; an unacknowledged (stale,
    unconsumed) record's queued ack is re-sent via resend_stale_acks.
  - AC6 (three-channel distinction): steer/pause/stop are distinct channels,
    and resume is a fourth lifecycle-only channel never conflated with them.

The boundary consumer and the suspend task are driven directly on a minimal
``AgentKernel`` instance with a REAL ``DirectorQueue``; the re-plan
(``_plan_task``) is a deterministic seam (no LLM). The suspend loop exits on
its first poll because the resume/stop record is pushed before the call.
"""

import types

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import DirectorQueue, QueueItem
from backend.agent.event_bus import IRISStreamEvent
from backend.agent.steering import (
    STEERING_CHANNELS,
    CHANNEL_RESUME,
    emit_queued_ack,
    get_steering_inbox,
    resend_stale_acks,
)
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


def _task_events(bus, event):
    return [e for e in bus.events if e[0] is event]


def _make_kernel():
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "conv_pause_test"
    k.session_id = "conv_pause_test"
    k._der_stop_requested = False
    k._der_pause_requested = False
    k._der_resume_requested = False
    k._der_ledger = None
    k._canned_plan = ExecutionPlan(
        plan_id="plan-rev",
        original_task="Steered task",
        strategy="do_it_myself",
        reasoning="user steering",
        plan_title="Revised plan",
        steps=[
            PlanStep(step_id="rev-1", step_number=1, description="revised step A"),
        ],
    )
    k._plan_task = types.MethodType(lambda self, text, **kw: self._canned_plan, k)
    return k


def _make_queue(*descriptions):
    q = DirectorQueue(objective="original objective")
    for i, d in enumerate(descriptions, start=1):
        q.add_item(QueueItem(step_id=f"step-{i}", step_number=i, description=d))
    return q


# ── AC4: pause suspends at the next boundary and resumes idempotently ─────


def test_pause_latches_and_suspend_resumes_without_duplicating_side_effects(monkeypatch):
    k = _make_kernel()
    q = _make_queue("original A", "original B")
    bus = _CapturingBus()
    monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: bus)
    get_steering_inbox().push("pause", "sess", text="")

    boundary = k._der_check_steering("sess", plan=k._canned_plan, queue=q)
    assert boundary["pause"] is True
    assert k._der_pause_requested is True
    # The pause record was consumed and acknowledged (AC5).
    assert [e[1]["status"] for e in _task_events(bus, IRISStreamEvent.STEERING_ACK)] == ["considered"]

    # Resume is pre-queued so the suspend loop exits on its first poll.
    get_steering_inbox().push("resume", "sess", text="")
    get_steering_inbox().push("steer", "sess", text="while paused, redirect")

    verdict = k._der_suspend_task("sess", plan=k._canned_plan, queue=q, _turn_id="t1")

    assert verdict == "resume"
    assert k._der_resume_requested is True
    # AC4: in-progress state persisted — task:paused BEFORE task:resumed, and
    # the ledger returns to "running".
    paused = _task_events(bus, IRISStreamEvent.TASK_PAUSED)
    resumed = _task_events(bus, IRISStreamEvent.TASK_RESUMED)
    assert len(paused) == 1 and len(resumed) == 1
    assert bus.events.index(paused[0]) < bus.events.index(resumed[0])
    assert k._der_ledger.get_task("conv_pause_test").lifecycle == "running"
    # Idempotent resume: completed_ids untouched — nothing re-executes.
    assert q.completed_ids == []
    # AC4 edge: a steer that arrived WHILE suspended stayed queued and is
    # applied at the post-resume boundary (never dropped).
    assert get_steering_inbox().pending("sess") == 1
    post = k._der_check_steering("sess", plan=k._canned_plan, queue=q)
    assert post["steer"] == "while paused, redirect"
    assert post["revised"] is True
    assert [i.step_id for i in q.items if i.step_id not in q.completed_ids] == ["steer-1"]


def test_stop_during_suspend_aborts(monkeypatch):
    k = _make_kernel()
    q = _make_queue("original A")
    bus = _CapturingBus()
    monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: bus)
    get_steering_inbox().push("pause", "sess", text="")
    assert k._der_check_steering("sess", plan=k._canned_plan, queue=q)["pause"] is True

    # Stop pre-queued: the suspend loop exits "stop" on its first poll.
    get_steering_inbox().push("stop", "sess", text="")
    verdict = k._der_suspend_task("sess", plan=k._canned_plan, queue=q, _turn_id="t1")

    assert verdict == "stop"
    assert k._der_stop_requested is True
    # The paused state WAS persisted before the stop took over (the loop's
    # outcome tail moves it to `cancelled`, per REQ-15 AC3 / T25).
    assert len(_task_events(bus, IRISStreamEvent.TASK_PAUSED)) == 1
    assert not _task_events(bus, IRISStreamEvent.TASK_RESUMED)
    assert k._der_ledger.get_task("conv_pause_test").lifecycle == "paused"


def test_suspend_holds_pending_items_untouched(monkeypatch):
    """AC4: suspension never mutates the queue — completed work stays done and
    pending work is simply held for re-pull after resume."""
    k = _make_kernel()
    q = _make_queue("done A", "pending B")
    q.mark_complete("step-1")
    bus = _CapturingBus()
    monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: bus)

    get_steering_inbox().push("pause", "sess", text="")
    assert k._der_check_steering("sess", plan=k._canned_plan, queue=q)["pause"] is True
    get_steering_inbox().push("resume", "sess", text="")
    verdict = k._der_suspend_task("sess", plan=k._canned_plan, queue=q, _turn_id="t1")

    assert verdict == "resume"
    # completed_ids preserved (idempotent resume) — next_ready skips step-1
    # and re-offers only the pending step.
    assert q.completed_ids == ["step-1"]
    nxt = q.next_ready("sess")
    assert nxt is not None and nxt.step_id == "step-2"


# ── AC5: acknowledgement (queued / considered) + re-send ──────────────────


def test_consumed_records_are_acked_as_considered(monkeypatch):
    k = _make_kernel()
    q = _make_queue("original A")
    bus = _CapturingBus()
    monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: bus)
    r1 = get_steering_inbox().push("steer", "sess", text="go this way")
    r2 = get_steering_inbox().push("stop", "sess", text="")

    k._der_check_steering("sess", plan=k._canned_plan, queue=q)

    acks = _task_events(bus, IRISStreamEvent.STEERING_ACK)
    assert len(acks) == 2
    payloads = sorted((e[1] for e in acks), key=lambda p: p["channel"])
    assert [p["status"] for p in payloads] == ["considered", "considered"]
    assert {p["channel"] for p in payloads} == {"steer", "stop"}
    assert {p["message_id"] for p in payloads} == {r1.message_id, r2.message_id}
    # The stop record WAS considered (latched) — ack before the loop breaks.
    assert k._der_stop_requested is True


def test_queued_ack_emitted_on_landing(monkeypatch):
    bus = _CapturingBus()
    monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: bus)
    rec = get_steering_inbox().push("steer", "sess", text="do it")

    emit_queued_ack(rec)

    acks = _task_events(bus, IRISStreamEvent.STEERING_ACK)
    assert len(acks) == 1
    assert acks[0][1] == {
        "channel": "steer",
        "message_id": rec.message_id,
        "status": "queued",
    }


def test_unacknowledged_stale_record_is_resent(monkeypatch):
    bus = _CapturingBus()
    monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: bus)
    stale = get_steering_inbox().push("steer", "sess", text="old message")
    stale.queued_at -= 30  # backdate past the resend window
    fresh = get_steering_inbox().push("steer", "sess", text="new message")

    resent = resend_stale_acks("sess", max_age_seconds=10)

    # Only the stale (unacknowledged) record is re-sent — the fresh one is not.
    assert [r.message_id for r in resent] == [stale.message_id]
    assert fresh.message_id not in [r.message_id for r in resent]
    # And the record is still queued (unconsumed) — re-send does not consume.
    assert get_steering_inbox().pending("sess") == 2
    acks = _task_events(bus, IRISStreamEvent.STEERING_ACK)
    assert len(acks) == 1
    assert acks[0][1]["message_id"] == stale.message_id
    assert acks[0][1]["status"] == "queued"


# ── AC6: three-channel distinction + resume is a separate channel ─────────


def test_three_channels_stay_distinct_and_resume_is_not_a_steering_channel():
    inbox = get_steering_inbox()
    inbox.push("steer", "sess", text="s")
    inbox.push("pause", "sess", text="p")
    inbox.push("stop", "sess", text="t")

    drained = inbox.drain("sess")

    # Channel identity is preserved end to end — nothing is conflated.
    assert [r.channel for r in drained] == ["steer", "pause", "stop"]
    assert STEERING_CHANNELS == frozenset({"steer", "pause", "stop"})
    # AC4: resume is a fourth, lifecycle-only channel — never a steering one.
    assert CHANNEL_RESUME == "resume"
    assert CHANNEL_RESUME not in STEERING_CHANNELS
