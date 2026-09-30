"""Contract: a landed TOPO_VIOLATION (rec==3) halts the DER loop into its
targeted recovery (MCM pin_22b078571d73, option B, owner-delegated 2026-09-30).

Before: the rec==3 raise ran inside the physics job and was always swallowed
(finalize's broad except, later the lane job), and every shape-decision read
sits inside an advisory try — so _der_execute_with_recovery's recovery
(Caducean reset + DER_RECOVERY + one retry) never ran in production.
Now: _der_topology_halt, called at each step boundary outside any broad
except, raises once per landed rec==3 update and never waits on the lane.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.agent import agent_kernel
from backend.agent.exceptions import TopologyViolationException


def _owner(rec, landed=True):
    fold = SimpleNamespace(
        ready=threading.Event(), done=threading.Event(), lock=threading.Lock(),
        rec=rec, step=3,
    )
    if landed:
        fold.ready.set()
        fold.done.set()
    return SimpleNamespace(_der_physics_pending={"s": fold}), fold


def test_landed_violation_halts_once():
    owner, _ = _owner(3)
    with pytest.raises(TopologyViolationException):
        agent_kernel._der_topology_halt(owner, "s")
    # The recovery run must not halt again on the same update.
    agent_kernel._der_topology_halt(owner, "s")


@pytest.mark.parametrize("rec", [None, 0, 1, 2])
def test_no_halt_without_violation(rec):
    owner, _ = _owner(rec)
    agent_kernel._der_topology_halt(owner, "s")


def test_unlanded_update_never_waits_and_never_halts():
    owner, fold = _owner(3, landed=False)
    agent_kernel._der_topology_halt(owner, "s")  # returns at once (S3)
    fold.ready.set()
    with pytest.raises(TopologyViolationException):
        agent_kernel._der_topology_halt(owner, "s")  # caught at the next boundary


def test_no_pending_physics_is_a_no_op():
    agent_kernel._der_topology_halt(SimpleNamespace(), "s")
    agent_kernel._der_topology_halt(SimpleNamespace(_der_physics_pending={}), "s")


def test_halt_reaches_targeted_recovery():
    """The seam: a halt raised inside the plan run triggers the Caducean reset,
    DER_RECOVERY and one retry — not the ReAct fallback."""
    owner, _ = _owner(3)
    kernel = MagicMock()
    kernel._der_physics_pending = owner._der_physics_pending
    calls = {"n": 0}

    def _execute(*a, **k):
        calls["n"] += 1
        agent_kernel._der_topology_halt(kernel, "s")  # the step-boundary call
        return "recovered"

    kernel._execute_plan_der.side_effect = _execute
    with patch("backend.gateway.iris_ffi.ffi_caducean_init_session") as _init, \
         patch("backend.agent.event_bus.get_event_bus", return_value=MagicMock()) as _bus:
        result = agent_kernel.AgentKernel._der_execute_with_recovery.__get__(
            kernel, agent_kernel.AgentKernel
        )(_plan=MagicMock(), _context_package=None, _is_mature=False,
          _der_task_class="full", _session="s", from_voice=False,
          _confidence=0.5, task_id="t1")

    assert result == "recovered"
    assert calls["n"] == 2, "one halted run + one recovery run"
    assert _init.called, "the Caducean session is reset before the retry"
    _modes = [c.kwargs.get("data", {}).get("to_mode")
              for c in _bus.return_value.emit.call_args_list]
    assert "DER_RECOVERY" in _modes, _modes


def test_step_loop_calls_the_halt_before_the_steering_check():
    """Structural: the boundary call sits in the step loop, outside the
    advisory gates (inside them a raise is swallowed — the original bug)."""
    import inspect

    src = inspect.getsource(agent_kernel.AgentKernel._execute_plan_der)
    halt = src.find("_der_topology_halt(self, _session)")
    steer = src.find("self._der_check_steering(")
    assert halt != -1, "the step loop does not call _der_topology_halt"
    assert halt < steer, "the halt must run before the steering check"
