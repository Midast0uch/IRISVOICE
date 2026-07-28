"""Phase 3 — Recovery & Safety Hardening (3.1–3.5).

3.1 (M.3.3): graft recovery prompt receives past-failure + proven-approach
             memory and an AVAILABLE TOOLS list.
3.2 (N.4 + O.6 + RC11): TopologyViolationException triggers targeted recovery
             (Caducean reset + MODE_CHANGED event + one retry) instead of the
             blanket ReAct fallback; recovery failure falls back to ReAct.
3.3 (RC6): token-budget exhaustion emits plan:budget_exhausted (not silent stop).
3.4 (M1): simple 1–2 step tasks do not escalate on unused budget; complex tasks do.
3.5 (M2): non-critical failures are stored in PACMAN (zone="failure") and signal
             Caducean (action=1 -> failure accumulator y).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ── 3.1 — Memory-aware graft recovery ────────────────────────────────────────

def _graft_kernel(retrieve_failures, retrieve_similar, specs):
    kernel = MagicMock()
    kernel._memory_interface = MagicMock()
    kernel._memory_interface.episodic.retrieve_failures.return_value = retrieve_failures
    kernel._memory_interface.episodic.retrieve_similar.return_value = retrieve_similar

    captured = {}

    def _infer(prompt, **kw):
        captured["prompt"] = prompt
        captured["raw"] = (
            '{"steps": [{"step_id": "r1", "description": "retry", '
            '"tool": "read_file", "params": {}}]}'
        )
        return SimpleNamespace(raw_text=captured["raw"])

    kernel.infer.side_effect = _infer
    return kernel, captured


def test_graft_prompt_includes_failure_memory():
    """M.3.3: graft recovery MUST receive past failure context."""
    from backend.agent import agent_kernel

    kernel, captured = _graft_kernel(
        retrieve_failures=[{"task_summary": "edit binary config",
                            "failure_reason": "corrupted file"}],
        retrieve_similar=[],
        specs=[SimpleNamespace(name="read_file")],
    )
    failed = SimpleNamespace(description="edit binary config", tool="write_file")

    with patch("backend.agent.tool_registry.get_all_specs",
               return_value=[SimpleNamespace(name="read_file")]):
        steps = agent_kernel.AgentKernel._der_graft_recovery_plan.__get__(
            kernel, agent_kernel.AgentKernel
        )(objective="fix config", failed_item=failed, error_msg="boom", _session="s")

    assert steps, "graft should produce recovery steps"
    assert "PAST FAILURES" in captured["prompt"], captured["prompt"]
    assert "AVOID: edit binary config" in captured["prompt"]


def test_graft_prompt_includes_alternative_approaches():
    """M.3.3: graft recovery MUST receive proven alternative approaches."""
    from backend.agent import agent_kernel

    kernel, captured = _graft_kernel(
        retrieve_failures=[],
        retrieve_similar=[{
            "task_summary": "read config safely",
            "tool_sequence": [{"tool": "read_file"}, {"tool": "write_file"}],
        }],
        specs=[SimpleNamespace(name="read_file")],
    )
    failed = SimpleNamespace(description="edit binary config", tool="write_file")

    with patch("backend.agent.tool_registry.get_all_specs",
               return_value=[SimpleNamespace(name="read_file")]):
        steps = agent_kernel.AgentKernel._der_graft_recovery_plan.__get__(
            kernel, agent_kernel.AgentKernel
        )(objective="fix config", failed_item=failed, error_msg="boom", _session="s")

    assert steps
    assert "ALTERNATIVE PROVEN APPROACHES" in captured["prompt"], captured["prompt"]
    assert "read_file -> write_file" in captured["prompt"]


def test_graft_works_with_empty_memory():
    """M.3.3: graft MUST still work when memory store is empty."""
    from backend.agent import agent_kernel

    kernel, captured = _graft_kernel(
        retrieve_failures=[],
        retrieve_similar=[],
        specs=[],
    )
    failed = SimpleNamespace(description="edit binary config", tool="write_file")

    with patch("backend.agent.tool_registry.get_all_specs", return_value=[]):
        steps = agent_kernel.AgentKernel._der_graft_recovery_plan.__get__(
            kernel, agent_kernel.AgentKernel
        )(objective="fix config", failed_item=failed, error_msg="boom", _session="s")

    assert steps, "graft must still produce steps with empty memory"
    assert "PAST FAILURES" not in captured["prompt"]
    assert "ALTERNATIVE PROVEN APPROACHES" not in captured["prompt"]


# ── 3.2 — Caducean exit -> targeted recovery ─────────────────────────────────

def test_topology_violation_triggers_targeted_recovery():
    """N.4: TopologyViolationException MUST trigger recovery, not ReAct fallback."""
    from backend.agent import agent_kernel
    from backend.agent.exceptions import TopologyViolationException

    kernel = MagicMock()
    calls = {"n": 0}

    def _execute(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TopologyViolationException("topo violation")
        return "recovered"

    kernel._execute_plan_der.side_effect = _execute

    with patch("backend.gateway.iris_ffi.ffi_caducean_init_session") as _init, \
         patch("backend.agent.event_bus.get_event_bus",
               return_value=MagicMock()) as _bus:
        result = agent_kernel.AgentKernel._der_execute_with_recovery.__get__(
            kernel, agent_kernel.AgentKernel
        )(_plan=MagicMock(), _context_package=None, _is_mature=False,
          _der_task_class="full", _session="s", from_voice=False,
          _confidence=0.5, task_id="t1")

    assert result == "recovered"
    assert calls["n"] == 2, "should retry once after violation"
    assert _init.called, "Caducean session must be reset before recovery"
    _emit = _bus.return_value.emit
    assert _emit.called
    _modes = [c.kwargs.get("data", {}).get("to_mode")
              for c in _emit.call_args_list]
    assert "DER_RECOVERY" in _modes, _modes


def test_recovery_failure_falls_back_to_react():
    """N.4: if recovery also fails, ReAct fallback MUST still engage (None)."""
    from backend.agent import agent_kernel
    from backend.agent.exceptions import TopologyViolationException

    kernel = MagicMock()
    kernel._execute_plan_der.side_effect = TopologyViolationException("topo")

    with patch("backend.gateway.iris_ffi.ffi_caducean_init_session"), \
         patch("backend.agent.event_bus.get_event_bus", return_value=MagicMock()):
        result = agent_kernel.AgentKernel._der_execute_with_recovery.__get__(
            kernel, agent_kernel.AgentKernel
        )(_plan=MagicMock(), _context_package=None, _is_mature=False,
          _der_task_class="full", _session="s", from_voice=False,
          _confidence=0.5, task_id="t1")

    assert result is None, "recovery failure must fall back to ReAct (None)"


# ── 3.3 — Budget exhaustion surfacing ───────────────────────────────────────

def test_budget_exhaustion_emits_event():
    """RC6: budget exhaustion MUST emit plan:budget_exhausted, not silently stop."""
    from backend.agent import agent_kernel
    from backend.agent.event_bus import IRISStreamEvent

    kernel = MagicMock()
    kernel.conversation_id = "conv"
    kernel.resolve_context_window.return_value = 8000
    bus = MagicMock()

    class _Item:
        step_id = "s1"
        step_number = 1
        description = "do thing"
        tool = "read_file"
        expected_output = None
        result = "ok"

    queue = MagicMock()
    queue.items = [_Item()]
    queue.completed_ids = []
    queue.failed_ids = []

    with patch("backend.agent.event_bus.get_event_bus", return_value=bus):
        agent_kernel.AgentKernel._der_finalize_step.__get__(
            kernel, agent_kernel.AgentKernel
        )(
            item=_Item(),
            step_result="ok",
            step_success=True,
            step_outputs=[],
            completed_items=[],
            _tokens_used=50000,
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

    _emit = bus.emit
    assert _emit.called
    _events = [c.args[0] for c in _emit.call_args_list]
    assert IRISStreamEvent.BUDGET_EXHAUSTED in _events, _events
    _budget_call = [c for c in _emit.call_args_list
                    if c.args[0] == IRISStreamEvent.BUDGET_EXHAUSTED][0]
    _data = _budget_call.kwargs.get("data")
    assert _data["tokens_used"] >= 50000
    assert _data["token_budget"] == 50000
    assert _data["steps_remaining"] >= 0


# ── 3.4 — Fix premature mode escalation (M1) ─────────────────────────────────

def test_simple_task_does_not_escalate_on_budget():
    """M1: simple tasks MUST NOT escalate just because budget is unused."""
    from backend.agent.der_loop import QueueItem, DirectorQueue, ExecutionMode

    q = DirectorQueue(objective="test")
    q.mode = ExecutionMode.QUICK
    q.items = [
        QueueItem(step_id="s1", step_number=1, description="a", tool="read_file"),
    ]
    escalated = q.check_escalation(
        review_verdict=None,
        tool_result_summary="Done",
        token_budget_remaining=11000,
    )
    assert not escalated


def test_complex_task_escalates_on_budget():
    """M1: complex tasks SHOULD still escalate when budget is mostly unused."""
    from backend.agent.der_loop import QueueItem, DirectorQueue, ExecutionMode

    q = DirectorQueue(objective="test")
    q.mode = ExecutionMode.QUICK
    q.items = [
        QueueItem(
            step_id=f"s{i}", step_number=i, description=f"step {i}",
            tool="read_file" if i % 2 else "write_file",
        )
        for i in range(1, 6)
    ]
    escalated = q.check_escalation(
        review_verdict=None,
        tool_result_summary="Done",
        token_budget_remaining=11000,
    )
    assert escalated


# ── 3.5 — Non-critical failure memory + Caducean signal (M2) ─────────────────

def test_noncritical_failure_stored_in_memory():
    """M2: non-critical failures MUST be stored in PACMAN with zone='failure'."""
    from backend.agent import agent_kernel

    kernel = MagicMock()
    kernel._memory_interface = MagicMock()
    kernel._memory_interface.episodic.fragment_and_store = MagicMock()

    class _Item:
        step_id = "s2"
        step_number = 2
        description = "optional cleanup"
        tool = "run_command"
        critical = False
        result = "FileNotFoundError: no such file"

    queue = MagicMock()
    queue.graft_attempts = 0
    queue.mark_failed = MagicMock()
    queue.abort_descendants.return_value = []

    with patch("backend.gateway.iris_ffi.ffi_caducean_update") as _upd:
        agent_kernel.AgentKernel._der_handle_step_failure.__get__(
            kernel, agent_kernel.AgentKernel
        )(item=_Item(), queue=queue, plan=MagicMock(), _session="sess",
          _turn_id="t1", context_package=None)

    frag = kernel._memory_interface.episodic.fragment_and_store
    assert frag.called, "non-critical failure should be fragmented"
    _call = frag.call_args
    assert _call.kwargs.get("chunk_type") == "der_failure", _call.kwargs
    # PACMAN alignment: failures stored in TRUSTED membrane (trusted://episodic/failures),
    # not off-membrane "der_failure" zone. chunk_type stays der_failure as discriminator.
    assert _call.kwargs.get("zone") == "trusted", _call.kwargs
    assert _upd.called, "Caducean should be signaled on non-critical failure"
    # action=1 -> COMPRESS (increments failure accumulator y)
    assert _upd.call_args.args[1] == 1, _upd.call_args
