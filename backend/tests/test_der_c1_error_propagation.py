"""C1 — preserve error text on the failure path so graft recovery receives it
(Phase 0.1 of the hardening plan).

Before this fix, ``item.result`` was only set on the success path, so the
graft recovery prompt (which reads ``item.result or ""``) received an empty
error and designed blind recovery. This test drives a real failing step
through ``_execute_plan_der`` and asserts the graft handler sees the error.
"""
import pytest
from unittest.mock import MagicMock, patch


class _Step:
    def __init__(self, **kw):
        self.step_id = kw.get("step_id")
        self.step_number = kw.get("step_number", 1)
        self.description = kw.get("description", "do thing")
        self.tool = kw.get("tool")
        self.params = kw.get("params", {})
        self.critical = kw.get("critical", True)
        self.depends_on = kw.get("depends_on", [])
        self.parallel_safe = kw.get("parallel_safe", False)


class _Plan:
    original_task = "test task"
    plan_title = "test plan"
    strategy = "standard"
    steps = [_Step(step_id="s1", description="failing step",
                   tool="read_file", params={"path": "/x"})]


def test_failed_step_result_propagated_to_graft():
    from backend.agent import agent_kernel

    with patch("backend.agent.event_bus.get_event_bus", return_value=MagicMock()), \
         patch("backend.ws_manager.get_websocket_manager", return_value=None):
        kernel = MagicMock()
        kernel.session_id = "sess"
        kernel.conversation_id = "conv"
        kernel._tool_bridge = MagicMock()
        kernel._reviewer = MagicMock()
        kernel._reviewer.review.return_value = (MagicMock(), None)
        mem = MagicMock()
        mem.episodic.retrieve_similar.return_value = []
        mem.episodic.retrieve_failures.return_value = []
        kernel._memory_interface = mem
        kernel.clear_turn_trust_flag = MagicMock()

        captured = {}

        def _fake_run(*a, **k):
            return ("ConnectionError: server unreachable", False)

        def _fake_handle(item, queue, *a, **k):
            captured["item"] = item
            # terminate the loop so the test does not re-process the item
            queue.mark_failed(item.step_id)

        kernel._der_run_step_execution = _fake_run
        kernel._der_handle_step_failure = _fake_handle

        agent_kernel.AgentKernel._execute_plan_der.__get__(
            kernel, agent_kernel.AgentKernel
        )(plan=_Plan(), context_package=None, session_id="sess", turn_id="t1")

    assert captured.get("item") is not None
    assert captured["item"].result == "ConnectionError: server unreachable"
    assert captured["item"].result != ""
