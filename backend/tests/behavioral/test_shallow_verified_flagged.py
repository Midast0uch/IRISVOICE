"""Behavioral: a VERIFIED-but-shallow step still runs `analyze_gaps` and can
still add a gap item to the queue (REQ-5 AC1/AC2).

Spec: specs/phase-6-der-integrity/requirements.md REQ-5.

Drives the REAL `AgentKernel._der_finalize_step` (same harness pattern as
CT-D2 / test_failed_step_writes_commit_row) with the TRAILING_GAP_MIN cadence
DELIBERATELY not hit and `_phase` NOT forcing gap analysis, so the ONLY thing
that can trigger `analyze_gaps` is the depth check itself (REQ-5 AC1). A
VERIFIED step with real depth must NOT trigger it off-cadence; a VERIFIED
step that is measurably thin MUST — "verified but inadequate" must not pass
silently just because it missed the periodic cadence.
"""

from __future__ import annotations

import backend.agent.caducean_trajectory as _ct_module
import backend.agent.event_bus as _eb_module
from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_constants import TRAILING_GAP_MIN
from backend.agent.der_loop import DirectorQueue, ExecutionMode, QueueItem


class _NoOpRecorder:
    def __init__(self, *a, **kw):
        pass

    def record_commit(self, **kwargs):
        pass


class _NoOpBus:
    def emit(self, event, data=None, **kw):
        pass


class _SpyTrailingDirector:
    def __init__(self):
        self.calls = []

    def analyze_gaps(self, completed_step, plan, context_package, is_mature):
        self.calls.append(completed_step.step_id)
        return []


def _make_kernel(conversation_id: str) -> AgentKernel:
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = conversation_id
    k._memory_interface = None
    k._mcm_orch = None
    k._der_last_u_mag = None
    k._der_work_units = 10
    k._der_live_cad_state = lambda session: {"u": 0.5, "xi": 0.1}
    k._split_step = lambda item, reason, cad, wu: []
    return k


def _run_finalize(kernel, item, step_result, completed_items):
    """Drives `_der_finalize_step` off the TRAILING_GAP_MIN cadence.

    `_der_finalize_step` appends `item` to `completed_items` BEFORE the
    trailing-director cadence check, so the cadence is evaluated against
    `len(completed_items) + 1`, not the length passed in here.
    """
    assert (len(completed_items) + 1) % TRAILING_GAP_MIN != 0, (
        "test fixture bug: post-append completed_items length must NOT be "
        "a cadence hit"
    )
    queue = DirectorQueue(objective="build the widget", items=[item])
    queue.mode = ExecutionMode.QUICK
    kernel._der_finalize_step(
        item=item,
        step_result=step_result,
        step_success=True,
        step_outputs=[],
        completed_items=completed_items,
        _tokens_used=0,
        _token_budget=10_000,
        _session="sess-depth",
        _turn_id="t1",
        _phase=2,  # NOT 3 -> _force_gap is False
        is_mature=False,
        _live_ctx=None,
        plan=type("P", (), {"original_task": "build the widget"})(),
        context_package=None,
        queue=queue,
        verdict=None,
    )


class TestShallowVerifiedFlagged:
    def test_shallow_verified_step_triggers_gap_analysis_off_cadence(self, monkeypatch):
        monkeypatch.setattr(_ct_module, "CaduceanTrajectoryRecorder", _NoOpRecorder)
        monkeypatch.setattr(_eb_module, "get_event_bus", lambda: _NoOpBus())

        kernel = _make_kernel("conv-shallow")
        kernel._verify_step_result = lambda goal, expected, result: "VERIFIED"
        spy = _SpyTrailingDirector()
        kernel._trailing_director = spy

        item = QueueItem(
            step_id="shallow-1", step_number=1, description="build the widget",
            tool="code", params={}, critical=False,
            objective_anchor="build the widget", expected_output="a widget",
            depth_layer=1,
        )
        # A one-word result -> far below EXPECTED_DEPTH_MIN_TOKENS.
        _run_finalize(kernel, item, "done.", completed_items=[])

        assert spy.calls == ["shallow-1"], (
            "a VERIFIED-but-shallow step must still trigger analyze_gaps "
            "even off the TRAILING_GAP_MIN cadence (REQ-5 AC1)"
        )

    def test_deep_verified_step_does_not_trigger_off_cadence(self, monkeypatch):
        monkeypatch.setattr(_ct_module, "CaduceanTrajectoryRecorder", _NoOpRecorder)
        monkeypatch.setattr(_eb_module, "get_event_bus", lambda: _NoOpBus())

        kernel = _make_kernel("conv-deep")
        kernel._verify_step_result = lambda goal, expected, result: "VERIFIED"
        spy = _SpyTrailingDirector()
        kernel._trailing_director = spy

        item = QueueItem(
            step_id="deep-1", step_number=1, description="build the widget",
            tool="code", params={}, critical=False,
            objective_anchor="build the widget", expected_output="a widget",
            depth_layer=1,
        )
        # A long, substantive result -> above EXPECTED_DEPTH_MIN_TOKENS.
        _run_finalize(kernel, item, "x" * 3000, completed_items=[])

        assert spy.calls == [], (
            "a VERIFIED step with real depth must NOT trigger analyze_gaps "
            "off-cadence — the depth check is a targeted flag, not a "
            "second unconditional gap pass"
        )

    def test_excluded_task_class_never_flags_even_when_thin(self, monkeypatch):
        """REQ-5 AC3: documented exclusion, not silent coverage loss."""
        monkeypatch.setattr(_ct_module, "CaduceanTrajectoryRecorder", _NoOpRecorder)
        monkeypatch.setattr(_eb_module, "get_event_bus", lambda: _NoOpBus())

        kernel = _make_kernel("conv-excluded")
        kernel._verify_step_result = lambda goal, expected, result: "VERIFIED"
        kernel._der_task_class = "question"  # excluded (der_constants.DEPTH_EXCLUDED_TASK_CLASSES)
        spy = _SpyTrailingDirector()
        kernel._trailing_director = spy

        item = QueueItem(
            step_id="q-1", step_number=1, description="what's 2+2",
            tool=None, params={}, critical=False,
            objective_anchor="what's 2+2", expected_output="4", depth_layer=1,
        )
        _run_finalize(kernel, item, "4", completed_items=[])

        assert spy.calls == []
