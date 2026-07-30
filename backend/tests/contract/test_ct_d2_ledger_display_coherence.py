"""CT-D2: ledger <-> display coherence.

Spec: specs/phase-6-der-integrity/design.md Testing Strategy > Contract table,
row CT-D2. "The `verified_label` in the ledger matches the status shown to
the user for the same step (Phase 2)."

Drives the REAL `AgentKernel._der_finalize_step` (not a re-implementation of
its logic) for one step and captures BOTH sinks it writes to:
  1. the commit ledger (`CaduceanTrajectoryRecorder.record_commit`,
     `verified_label=...`) — the AUDIT record.
  2. the `task:learning` event (`verified_label` field) — the signal the
     frontend uses to render the step's displayed status (Phase 2).

Asserts they carry the IDENTICAL value for the same step, for each of the
three labels. A scorer that inflated the displayed VERIFIED rate while the
ledger disagreed would be reward-hacking by accident (design.md's Ripple-
Effect Map, "Phase 2 displayed labels" row) — this pins that they cannot
diverge.
"""

from __future__ import annotations

import sqlite3

import pytest

import backend.agent.caducean_trajectory as _ct_module
import backend.agent.event_bus as _eb_module
from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import DirectorQueue, ExecutionMode, QueueItem


class _CapturingRecorder:
    """Spy standing in for CaduceanTrajectoryRecorder() inside the finalize
    step — captures record_commit(...) calls without touching any real DB."""

    calls = []

    def __init__(self, *a, **kw):
        pass

    def record_commit(self, **kwargs):
        _CapturingRecorder.calls.append(kwargs)


def _make_stub_kernel(conversation_id: str) -> AgentKernel:
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = conversation_id
    k._memory_interface = None
    k._trailing_director = None
    k._mcm_orch = None
    k._der_last_u_mag = None
    k._der_work_units = 10
    k._der_live_cad_state = lambda session: {"u": 0.5, "xi": 0.1}
    k._split_step = lambda item, reason, cad, wu: []  # never splits in this test
    return k


def _make_queue(item: QueueItem) -> DirectorQueue:
    q = DirectorQueue(objective="do the thing", items=[item])
    q.mode = ExecutionMode.QUICK
    return q


class _CapturingBus:
    def __init__(self):
        self.emitted = []

    def emit(self, event, data=None, **kw):
        self.emitted.append((getattr(event, "value", str(event)), data or {}))


@pytest.mark.parametrize("forced_label", ["VERIFIED", "UNVERIFIED", "FAILED"])
def test_ledger_label_matches_task_learning_event_label(monkeypatch, forced_label):
    _CapturingRecorder.calls = []
    monkeypatch.setattr(_ct_module, "CaduceanTrajectoryRecorder", _CapturingRecorder)
    bus = _CapturingBus()
    monkeypatch.setattr(_eb_module, "get_event_bus", lambda: bus)

    kernel = _make_stub_kernel(f"conv-ct-d2-{forced_label}")
    # Isolate the write-coherence contract from verification correctness —
    # CT-D2 is about whether both sinks agree on WHATEVER label was computed,
    # not about how that label was computed (that is CT-D1's job).
    kernel._verify_step_result = lambda goal, expected, result: forced_label

    item = QueueItem(
        step_id="step-ct-d2", step_number=1, description="do the thing",
        tool="run_command", params={}, critical=False,
        objective_anchor="do the thing", expected_output="done",
    )
    queue = _make_queue(item)

    kernel._der_finalize_step(
        item=item,
        step_result="some real output",
        step_success=True,
        step_outputs=[],
        completed_items=[],
        _tokens_used=0,
        _token_budget=10_000,
        _session="sess-ct-d2",
        _turn_id="t1",
        _phase=2,
        is_mature=False,
        _live_ctx=None,
        plan=type("P", (), {"original_task": "do the thing"})(),
        context_package=None,
        queue=queue,
        verdict=None,
    )

    assert len(_CapturingRecorder.calls) == 1, (
        f"expected exactly one commit-ledger row, got {_CapturingRecorder.calls}"
    )
    ledger_label = _CapturingRecorder.calls[0]["verified_label"]

    learning_events = [d for (name, d) in bus.emitted if name == "task:learning"]
    assert len(learning_events) == 1, (
        f"expected exactly one task:learning event, got {bus.emitted}"
    )
    display_label = learning_events[0]["verified_label"]

    assert ledger_label == forced_label
    assert display_label == forced_label
    assert ledger_label == display_label, (
        f"ledger wrote {ledger_label!r} but the displayed-status event "
        f"carried {display_label!r} for the SAME step — CT-D2 violated"
    )
