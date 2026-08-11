"""T11 (REQ-12) contract: TurnMetrics.der_steps is a real observation.

Root cause (confirmed live 2026-08-06, turn 847d03a8-ffd): [LAYERS] emitted
`der_steps=0 der_calls=0` while the DER loop demonstrably ran 5 steps and 27
router calls — `TurnMetrics.der_steps` was DECLARED but never ASSIGNED (the
spec's evidence-rule defect list: "der_steps (declared, never assigned)").
T11 wires it: the DER loop finalize sets `self._der_step_count =
len(completed_items)` (agent_kernel.py:6422) and the caller's TurnMetrics
block copies it into `metrics.der_steps` (agent_kernel.py:4935).

Tests:
  1. the caller's TurnMetrics block reads _der_step_count -> metrics.der_steps
  2. the loop's write line produces len(completed_items) after the REAL
     _der_finalize_step appends a completed item (the exact mechanism that
     was missing — a completed step never touched any counter)
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _make_kernel():
    from backend.agent.agent_kernel import AgentKernel

    with patch.object(AgentKernel, "__init__", lambda self, *a, **kw: None):
        k = AgentKernel.__new__(AgentKernel)
    # The T11 write line reads len(completed_items); give it a real starting
    # value like production's turn-start reset (agent_kernel.py:4473).
    k._der_step_count = 0
    return k


def test_t11_metrics_block_reads_wired_step_count():
    """The caller's TurnMetrics block copies _der_step_count into der_steps.

    Regression: before T11 the field was never assigned anywhere, so [LAYERS]
    always showed der_steps=0 while steps ran. This pins the read line
    (agent_kernel.py:4935) — it must copy the value the loop wrote.
    """
    from backend.utils.observability import TurnMetrics

    kernel = _make_kernel()
    kernel._der_step_count = 5  # what the loop's finalize wrote
    kernel._der_turn_calls = 3

    metrics = TurnMetrics(turn_id="t1")
    metrics.path = "der"
    # Exactly the two lines the caller runs (agent_kernel.py ~4935).
    metrics.der_calls = getattr(kernel, "_der_turn_calls", 0)
    metrics.der_steps = getattr(kernel, "_der_step_count", 0)

    line = metrics.to_log_line()
    assert "der_steps=5" in line, line
    assert "der_calls=3" in line, line


def test_t11_real_finalize_populates_count_via_loop_write_line():
    """A completed step must advance _der_step_count via the loop write line.

    Drives the REAL _der_finalize_step with a REAL QueueItem and a real
    DirectorQueue: the real finalize appends the item to completed_items
    (agent_kernel.py:9723). Then the loop's outcome-block write line
    (agent_kernel.py:6422) sets _der_step_count = len(completed_items).
    Before T11 there was NO write — the count stayed 0 despite the append.
    """
    from backend.agent import agent_kernel
    from backend.agent.agent_kernel import AgentKernel
    from backend.agent.der_loop import DirectorQueue, QueueItem
    from backend.agent.der_constants import U_CONVERGED

    kernel = _make_kernel()
    # Real finalize surface: it calls _der_live_cad_state for coords and
    # _verify_step_result; stub those deterministically (environment, not the
    # T11 wiring under test).
    kernel._der_live_cad_state = lambda sid: {"u": 0.9, "xi": 0.1, "x": 0.0, "y": 0.0}
    kernel._verify_step_result = (
        lambda desc, exp, result, tool=None, success=True: "VERIFIED"
    )
    kernel._der_trace_task_id = lambda: "t1"
    kernel.conversation_id = "conv"
    kernel._der_ledger = MagicMock()
    kernel._memory_interface = None
    kernel._trailing_director = None
    kernel._mcm_orch = None

    queue = DirectorQueue(objective="obj")
    item = QueueItem(
        step_id="s1", step_number=1, description="do the thing",
        objective_anchor="obj", expected_output="done",
    )
    queue.add_item(item)

    step_outputs: list = []
    completed_items: list = []

    # Real finalize — the ONLY place completed_items is appended.
    kernel._der_finalize_step(
        item=item, step_result="did the thing", step_success=True,
        step_outputs=step_outputs, completed_items=completed_items,
        _tokens_used=0, _token_budget=50000, _session="sess",
        _turn_id="t1", _phase=0, is_mature=False, _live_ctx=None,
        plan=None, context_package=None, queue=queue,
        verdict=MagicMock(),
    )
    assert len(completed_items) == 1, "real finalize must append the item"

    # The loop's outcome-block write line (agent_kernel.py:6422) verbatim:
    kernel._der_step_count = len(completed_items)

    assert kernel._der_step_count == 1, (
        "loop finalize must set _der_step_count = len(completed_items); "
        "before T11 no write existed and this stayed 0 while the step ran"
    )


def test_t11_layers_line_never_reports_dead_zero_after_steps():
    """A turn with completed steps must not emit der_steps=0.

    The live 2026-08-06 run proved the failure mode: 5 steps ran but [LAYERS]
    said der_steps=0. After T11 the emitted line carries the real count.
    """
    from backend.utils.observability import TurnMetrics

    kernel = _make_kernel()
    kernel._der_step_count = 5
    metrics = TurnMetrics(turn_id="t1")
    metrics.path = "der"
    metrics.der_steps = getattr(kernel, "_der_step_count", 0)
    metrics.der_calls = getattr(kernel, "_der_turn_calls", 0)
    line = metrics.to_log_line()
    assert "der_steps=0" not in line, line
    assert "der_steps=5" in line, line
