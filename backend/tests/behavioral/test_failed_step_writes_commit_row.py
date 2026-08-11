"""Behavioral: a FAILED step writes a commit row with miss-scoring and an
'avoided' learning signal (REQ-1 AC4).

Spec: specs/phase-6-der-integrity/requirements.md REQ-1 AC4.

Drives the REAL `AgentKernel._der_finalize_step` (same harness pattern as
CT-D2) for a step whose verification is forced to FAILED, and asserts:
  - a commit-ledger row IS written (not silently dropped â€” the exact bug
    this phase's REQ-1 exists to close: the old contract gated the write on
    VERIFIED, starving the failure-learning channel).
  - the row's label is FAILED, not coerced to something else.
  - the `task:learning` signal is 'avoided' (miss-scoring path), which is
    the trigger evidence.py's AVOID/tier-3 failure header machinery
    (`_avoid_list`, outcome_type='miss') consumes downstream.
"""

from __future__ import annotations

import pytest

import backend.agent.caducean_trajectory as _ct_module
import backend.agent.event_bus as _eb_module
from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import DirectorQueue, ExecutionMode, QueueItem


class _CapturingRecorder:
    calls = []

    def __init__(self, *a, **kw):
        pass

    def record_commit(self, **kwargs):
        _CapturingRecorder.calls.append(kwargs)


class _CapturingBus:
    def __init__(self):
        self.emitted = []

    def emit(self, event, data=None, **kw):
        self.emitted.append((getattr(event, "value", str(event)), data or {}))


def _make_stub_kernel(conversation_id: str) -> AgentKernel:
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = conversation_id
    k._memory_interface = None
    k._trailing_director = None
    k._mcm_orch = None
    k._der_last_u_mag = None
    k._der_work_units = 10
    k._der_live_cad_state = lambda session: {"u": 0.5, "xi": 0.1}
    k._split_step = lambda item, reason, cad, wu, step_result="": []
    return k


class TestFailedStepWritesCommitRow:
    def test_failed_step_writes_a_row_labeled_failed(self, monkeypatch):
        # REQ-20 (T37) moved the record_commit seam from direct
        # `CaduceanTrajectoryRecorder()` construction (which silently fell back
        # to the BUILD-memory DB) to `get_trajectory_recorder(memory_interface)`,
        # which returns a no-op for `memory_interface=None`. The seam under test
        # is therefore the binding function, not the recorder class; the real
        # binding is separately pinned by tests/contract/test_trajectory_recorder_binding.py.
        _CapturingRecorder.calls = []
        monkeypatch.setattr(_ct_module, "get_trajectory_recorder", lambda mi: _CapturingRecorder())
        bus = _CapturingBus()
        monkeypatch.setattr(_eb_module, "get_event_bus", lambda: bus)

        kernel = _make_stub_kernel("conv-failed-step")
        kernel._verify_step_result = lambda goal, expected, result, tool=None, success=False: "FAILED"

        item = QueueItem(
            step_id="step-fail-1", step_number=1, description="risky action",
            tool="run_command", params={}, critical=False,
            objective_anchor="do the thing", expected_output="done",
        )
        queue = DirectorQueue(objective="do the thing", items=[item])
        queue.mode = ExecutionMode.QUICK

        kernel._der_finalize_step(
            item=item,
            step_result="it did not work",
            step_success=True,  # deliberately True on input â€” must be
                                 # overridden by the FAILED verification
            step_outputs=[],
            completed_items=[],
            _tokens_used=0,
            _token_budget=10_000,
            _session="sess-fail",
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
            "a FAILED step must still write exactly one commit row â€” the old "
            "contract silently dropped it (audit finding B)"
        )
        assert _CapturingRecorder.calls[0]["verified_label"] == "FAILED"

        learning = [d for (name, d) in bus.emitted if name == "task:learning"]
        assert len(learning) == 1
        assert learning[0]["verified_label"] == "FAILED"
        assert learning[0]["signal"] == "avoided", (
            "a FAILED step with no recovery children must emit the "
            "'avoided' (miss-scoring) signal, not 'retried' or 'crystallized'"
        )
