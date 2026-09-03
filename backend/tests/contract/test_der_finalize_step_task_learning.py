"""Regression test: REQ-8 AC3 task:learning MUST actually emit.

Root cause (backend/logs/irisvoice.log.1, 2026-07-28 13:52:15, repeating):
    [DER] task:learning emit failed: cannot access local variable '_children'
    where it is not associated with a value

`_der_finalize_step` READ `_children` (to pick the "retried" vs "avoided"
signal) long before the one and only place it was ASSIGNED — the
verify_failed -> split-into-sub-loops block that used to sit at the very end
of the function, gated on `if not step_success and not item.is_subloop`. Since
a name assigned anywhere in a Python function is local for the WHOLE
function, every read before that point raised `UnboundLocalError`, and the
learning-signal block swallows exceptions (`except Exception as _learn_exc:
logger.debug(...)`) so the event silently never fired — on ANY step,
including a plain successful one (`step_success=True` never even reaches the
assignment, so `_children` was unbound there too).

These tests drive the REAL method (no stubbing of the buggy logic itself)
and assert the EFFECT: the event bus actually receives a `task:learning`
event. Before the fix, the emit is swallowed and the bus is never called.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


class _Item:
    step_id = "s1"
    step_number = 1
    description = "do the thing"
    tool = "read_file"
    expected_output = None
    result = "ok"
    is_subloop = False


def _base_kernel():
    kernel = MagicMock()
    kernel.conversation_id = "conv"
    kernel.resolve_context_window.return_value = 8000
    # Keep the huge amount of optional post-processing in _der_finalize_step
    # inert so this test isolates the REQ-8 emit path.
    kernel._memory_interface = None
    kernel._mcm_orch = None
    kernel._trailing_director = None
    kernel._der_last_u_mag = 0.0
    return kernel


def _run(kernel, queue, item, step_success, bus):
    from backend.agent import agent_kernel

    with patch("backend.agent.event_bus.get_event_bus", return_value=bus):
        agent_kernel.AgentKernel._der_finalize_step.__get__(
            kernel, agent_kernel.AgentKernel
        )(
            item=item,
            step_result="ok" if step_success else "FAILED: no real output",
            step_success=step_success,
            step_outputs=[],
            completed_items=[],
            _tokens_used=0,
            _token_budget=50000,
            _session="sess",
            _turn_id="t1",
            _phase=0,
            is_mature=False,
            _live_ctx=None,
            plan=None,
            context_package=None,
            queue=queue,
            verdict=MagicMock(),
        )


def _learning_events(bus):
    from backend.agent.event_bus import IRISStreamEvent

    return [
        c for c in bus.emit.call_args_list
        if c.args and c.args[0] == IRISStreamEvent.TASK_LEARNING
    ]


class TestTaskLearningActuallyEmits:
    def test_task_learning_emitted_on_verified_success(self):
        """The most common path (a plain successful step) MUST still emit.

        Before the fix this ALSO crashed: `_children` is only ever assigned
        inside the `if not step_success and not item.is_subloop:` branch,
        which a successful step never enters, so `_children` was unbound
        here too — the bug was not failure-only.
        """
        kernel = _base_kernel()
        kernel._verify_step_result.return_value = "VERIFIED"
        queue = MagicMock()
        queue.failed_ids = []
        bus = MagicMock()

        _run(kernel, queue, _Item(), step_success=True, bus=bus)

        events = _learning_events(bus)
        assert events, "task:learning event was never emitted (swallowed exception)"
        data = events[0].kwargs.get("data") or (events[0].args[1] if len(events[0].args) > 1 else None)
        assert data is not None, events[0]
        assert data["signal"] == "crystallized", data

    def test_task_learning_emitted_on_failed_step_avoided(self):
        """A FAILED, non-subloop step with no split children -> 'avoided'."""
        kernel = _base_kernel()
        kernel._verify_step_result.return_value = "FAILED"
        kernel._split_step.return_value = []
        queue = MagicMock()
        queue.failed_ids = []
        bus = MagicMock()

        item = _Item()
        item.is_subloop = False
        _run(kernel, queue, item, step_success=False, bus=bus)

        events = _learning_events(bus)
        assert events, "task:learning event was never emitted (swallowed exception)"
        data = events[0].kwargs.get("data") or (events[0].args[1] if len(events[0].args) > 1 else None)
        assert data is not None, events[0]
        assert data["signal"] == "avoided", data

    def test_task_learning_emitted_on_split_retried(self):
        """A FAILED, non-subloop step that DOES split -> 'retried'."""
        kernel = _base_kernel()
        kernel._verify_step_result.return_value = "FAILED"
        kernel._split_step.return_value = [MagicMock()]
        queue = MagicMock()
        queue.failed_ids = []
        bus = MagicMock()

        item = _Item()
        item.is_subloop = False
        with patch("backend.agent.agent_kernel.get_batcher") as _batcher, \
             patch("backend.agent.agent_kernel.debit_work_units", return_value=0):
            _batcher.return_value.offer.return_value = None
            _run(kernel, queue, item, step_success=False, bus=bus)

        events = _learning_events(bus)
        assert events, "task:learning event was never emitted (swallowed exception)"
        data = events[0].kwargs.get("data") or (events[0].args[1] if len(events[0].args) > 1 else None)
        assert data is not None, events[0]
        assert data["signal"] == "retried", data
