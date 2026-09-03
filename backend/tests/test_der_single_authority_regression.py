"""Regression — single tool-resolution authority (F6 / System Invariant).

After the 5-phase DER rewrite, the ONLY runtime authority that may assign a
tool to a step is ``explorer.propose`` (called from ``_der_run_step_execution``
when ``item.tool`` is None). Two legacy paths used to assign ``tool``/``params``
directly from LLM output, bypassing the resolver:

  * critical-failure recovery (formerly ``_der_graft_recovery_plan``)
  * explorer continuation (``_der_plan_next_step`` in AGENTIC/FULL mode)

Both MUST now emit GOAL-ONLY items (tool=None) so the resolver fires. This
test locks that contract so a future edit cannot silently re-introduce a
second tool authority.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _kernel_with_split():
    """AgentKernel double that records split calls and returns goal-only kids."""
    from backend.agent import agent_kernel
    from backend.agent.der_loop import QueueItem

    kernel = MagicMock()
    kernel._memory_interface = None
    kernel._der_work_units = 12
    captured = {"split_called": False, "children": []}

    def _split_step(item, trigger, cad, work_units, step_result=""):
        captured["split_called"] = True
        captured["trigger"] = trigger
        # Children mirror the unified operator: GOAL ONLY (no tool).
        child = QueueItem(
            step_id=f"{item.step_id}_s0",
            step_number=item.step_number,
            description=f"{item.description} (sub 1)",
            tool=None,
            params={},
            is_subloop=True,
        )
        captured["children"] = [child]
        return [child]

    kernel._split_step.side_effect = _split_step
    kernel._der_live_cad_state.return_value = {"u": 0.1, "xi": 0.5}
    return kernel, agent_kernel, captured


def test_critical_failure_routes_through_split_not_graft():
    """Bypass A: critical failure MUST use _split_step, emit tool=None items."""
    from backend.agent import agent_kernel
    from backend.agent.der_loop import QueueItem, DirectorQueue

    kernel, ak, captured = _kernel_with_split()
    kernel._der_graft_recovery_plan = MagicMock()  # must NOT be called

    queue = DirectorQueue(objective="fix config")
    queue.graft_attempts = 0
    item = QueueItem(
        step_id="s1", step_number=1, description="edit binary config",
        tool="write_file", critical=True, result="boom",
    )

    with patch("backend.agent.event_bus.get_event_bus", return_value=MagicMock()):
        agent_kernel.AgentKernel._der_handle_step_failure.__get__(
            kernel, agent_kernel.AgentKernel
        )(
            item=item, queue=queue, plan=MagicMock(),
            _session="sess", _turn_id="t1", context_package=None,
        )

    assert captured["split_called"], "critical failure must route through _split_step"
    assert captured["trigger"] == "verify_failed"
    assert not kernel._der_graft_recovery_plan.called, \
        "legacy graft path must NOT assign tools"
    # The recovered child carries no tool -> resolver fires on execution.
    assert captured["children"]
    assert captured["children"][0].tool is None
    assert captured["children"][0].params == {}


def test_graft_recovery_helper_returns_goal_only():
    """Even if _der_graft_recovery_plan is called, it must NOT assign a tool."""
    from backend.agent import agent_kernel

    kernel = MagicMock()
    kernel._memory_interface = MagicMock()
    kernel._memory_interface.episodic.retrieve_failures.return_value = []
    kernel._memory_interface.episodic.retrieve_similar.return_value = []

    def _infer(prompt, **kw):
        return SimpleNamespace(
            raw_text='{"steps": [{"step_id": "r1", "description": "retry safely", '
                     '"tool": "read_file", "params": {"path": "x"}}]}'
        )

    kernel.infer.side_effect = _infer

    with patch("backend.agent.tool_registry.get_all_specs", return_value=[]):
        steps = agent_kernel.AgentKernel._der_graft_recovery_plan.__get__(
            kernel, agent_kernel.AgentKernel
        )(objective="fix config", failed_item=MagicMock(), error_msg="boom", _session="s")

    assert steps, "graft helper should still produce recovery steps"
    # The LLM's "tool"/"params" MUST be ignored — goal only.
    assert steps[0].tool is None, "graft helper must not assign a tool"
    assert steps[0].params == {}, "graft helper must not assign params"


def test_plan_next_step_returns_goal_only():
    """Bypass B: explorer continuation MUST return a goal, not a tool."""
    from backend.agent import agent_kernel
    from backend.agent.der_loop import QueueItem, ExecutionMode

    kernel = MagicMock()
    kernel._memory_interface = None

    def _infer(prompt, **kw):
        # LLM tries to name a tool — the method must ignore it.
        return SimpleNamespace(
            raw_text='{"done": false, "tool": "run_command", '
                     '"description": "verify the fix", "params": {"cmd": "x"}}'
        )

    kernel.infer.side_effect = _infer

    completed = [QueueItem(step_id="s1", step_number=1, description="edit file")]

    with patch("backend.agent.der_constants.ExecutionMode", ExecutionMode):
        result = agent_kernel.AgentKernel._der_plan_next_step.__get__(
            kernel, agent_kernel.AgentKernel
        )(
            task_objective="fix config", completed_items=completed,
            mode=ExecutionMode.AGENTIC, step_outputs=["ok"],
        )

    assert result is not None, "should propose a next step"
    assert "description" in result
    assert "tool" not in result, "continuation must not return a tool"
    assert "params" not in result, "continuation must not return params"
