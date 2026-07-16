"""DER Coupled Action Cycle — full integration smoke test.

Composes the real Phase 0-4 methods end-to-end with lightweight stubs (no live
model / FFI / DB required) to prove the pieces wire together:

  planner (_plan_task)  -> goal-only steps (Phase 1)
  resolver (explorer.propose, via _der_run_step_execution) -> picks a real tool (Phase 1)
  execution             -> tool runs via _tool_bridge (Phase 1)
  verify (FAILED)       -> _split_step appends Sub-Loop children, NO commit (Phase 2 + G5)
  verify (VERIFIED)     -> record_commit writes a ledger row (G5)
  session exit          -> OuterTuner.run_once learns from ledgers (Phase 4)

This is a SMOKE test: it asserts the cross-module wiring works, not exhaustive
behavior. Each phase's unit tests cover the details.
"""

import sqlite3
import types

import pytest


def _build_kernel():
    """AgentKernel with the minimal surface stubbed for an offline run."""
    from backend.agent.agent_kernel import AgentKernel

    k = AgentKernel.__new__(AgentKernel)
    k._memory_interface = None
    k._tool_bridge = None
    k._reviewer = None
    k._mcm_orch = None
    k._der_task_class = "full"
    k._der_completed_tools = []
    k._der_work_units = 0
    k.conversation_id = "smoke-conv"
    k.session_id = "smoke-session"
    # planner helpers touched by _plan_task
    k._personality = None
    k._caducean_modulate_temperature = lambda base, sid: base
    k._get_failure_warnings = lambda text: "None"
    k._build_planning_prompt = lambda **kw: "PLAN PROMPT"

    # resolve_context_window -> drives DER_WORK_UNITS_0 (Phase 2 D2.4)
    k.resolve_context_window = lambda: 30000

    # _router.generate -> planner output (goal-only; tool dropped by _plan_task)
    _PLAN = (
        '{"steps": ['
        '{"step_id": "s1", "step_number": 1, "description": "run the build", '
        '"tool": "run_command", "params": {"cmd": "pytest"}},'
        '{"step_id": "s2", "step_number": 2, "description": "write a report", '
        '"tool": "write_file", "params": {}}'
        ']}'
    )
    k._router = types.SimpleNamespace(generate=lambda *a, **kw: (_PLAN, "", None))

    # infer -> resolver proposal (valid registry tool) + tool-less fallback
    def _infer(prompt, **kw):
        class _R:
            raw_text = '{"kind": "tool", "tool": "run_command", "params": {"cmd": "pytest"}, "rationale": "smoke"}'

        return _R()

    k.infer = _infer

    # _tool_bridge.execute_tool is ASYNC in production (the kernel calls it via
    # asyncio.run). The stub must match that contract.
    async def _execute_tool(tool_name=None, params=None, **kw):
        return {"success": True, "output": f"ran {tool_name} ok", "tool_name": tool_name}

    k._tool_bridge = types.SimpleNamespace(execute_tool=_execute_tool)
    return k


def _make_queue(items):
    from backend.agent.der_loop import DirectorQueue

    q = DirectorQueue(objective="smoke")
    for it in items:
        q.add_item(it)
    return q


def test_integration_full_cycle():
    from backend.agent.der_loop import QueueItem
    from backend.agent.tool_registry import get_registry_tools

    k = _build_kernel()

    # ── Phase 1: planner emits GOALS only (tool dropped) ──
    plan = k._plan_task("build and report", session_id=k.session_id)
    assert len(plan.steps) == 2
    assert all(s.tool is None for s in plan.steps), "planner must emit goals only"

    # Build the execution queue exactly like _execute_plan_der does.
    items = [
        QueueItem(
            step_id=s.step_id,
            step_number=s.step_number,
            description=s.description,
            objective_anchor=plan.original_task,
            depth_layer=0,
            expected_output="build passes; report written",
            tool=s.tool,  # None (goal-only)
            params=s.params,
            critical=s.critical,
        )
        for s in plan.steps
    ]
    queue = _make_queue(items)

    # ── Phase 1 + 2: resolver fires in _der_run_step_execution, picks a tool ──
    # Ensure the resolver can validate run_command (registry may be empty in the
    # test env). We stub the validation + tool listing so the resolver picks a
    # real, known tool — proving the wiring, not the registry contents.
    import backend.agent.explorer as ex
    import backend.agent.tool_registry as tr

    ex.get_registry_tools = lambda: [{"name": "run_command"}, {"name": "write_file"}]
    tr.validate_tool_call = lambda tool, params: (
        (True, None) if tool in ("run_command", "write_file") else (False, "unknown tool")
    )

    ctx = types.SimpleNamespace()
    plan_ns = types.SimpleNamespace(
        steps=plan.steps, original_task=plan.original_task, plan_title="smoke"
    )
    step_result, step_success = k._der_run_step_execution(
        items[0], ctx, k.session_id, "turn-1", plan_ns
    )
    # Resolver must have set the tool (Phase 1 single authority)
    assert items[0].tool == "run_command", "resolver must choose a real tool"
    assert step_success is True, "tool execution succeeded"
    assert "ran run_command" in step_result

    # ── Phase 2 + G5: a FAILED step triggers _split_step, NO commit ──
    # Observe the commit ledger by patching the class method (the kernel imports
    # CaduceanTrajectoryRecorder lazily inside _der_finalize_step, so we patch the
    # class method, not a module attribute). This is a test observer, not a code
    # change — the production record_commit writes to the real ledger.
    from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder
    from backend.agent.der_constants import derive_work_units_0

    # The real orchestrator (_der_execute_with_recovery) initializes the unified
    # termination budget from the live context window. Simulate that here.
    k._der_work_units = derive_work_units_0(k.resolve_context_window())

    _commit_calls = []

    def _spy_record_commit(self, session_id, step_id, commit_hash, message, u=None, xi=None):
        _commit_calls.append((session_id, step_id, commit_hash, message))

    _orig_record_commit = CaduceanTrajectoryRecorder.record_commit
    CaduceanTrajectoryRecorder.record_commit = _spy_record_commit

    fail_item = QueueItem(
        step_id="s9", step_number=9, description="do risky thing",
        objective_anchor="obj", depth_layer=0,
        expected_output="thing done correctly",
    )
    queue2 = _make_queue([fail_item])
    # finalize with a STUB result -> FAILED -> split, no commit
    k._der_finalize_step(
        fail_item,
        "[step 9 completed]",
        False,
        [(fail_item, "[step 9 completed]")],
        [fail_item],
        0,
        30000,
        k.session_id,
        "turn-9",
        "execute",
        False,
        None,
        plan_ns,
        ctx,
        queue2,
        None,
    )
    # Split must have appended Sub-Loop children (Phase 2)
    assert len(queue2.items) >= 1, "verify_failed must trigger _split_step"
    assert any(c.is_subloop for c in queue2.items), "children are Sub-Loops"
    # G5: NO commit written on FAILED
    assert len(_commit_calls) == 0, "no commit on FAILED (G5)"

    # ── G5: a VERIFIED step writes a commit ──
    ok_item = QueueItem(
        step_id="s10", step_number=10, description="do safe thing",
        objective_anchor="obj", depth_layer=0,
        expected_output="thing done correctly",
    )
    queue3 = _make_queue([ok_item])
    k._der_finalize_step(
        ok_item,
        "thing done correctly and verified",
        True,
        [(ok_item, "thing done correctly and verified")],
        [ok_item],
        0,
        30000,
        k.session_id,
        "turn-10",
        "execute",
        False,
        None,
        plan_ns,
        ctx,
        queue3,
        None,
    )
    assert len(_commit_calls) == 1, "VERIFIED step writes a commit (G5)"

    # restore the real method
    CaduceanTrajectoryRecorder.record_commit = _orig_record_commit

    # ── Phase 4: outer loop fires on session exit and learns ──
    from backend.agent.outer_loop import OuterTuner, run_outer_loop

    # Seed session exits so the tuner has data.
    seed = __import__(
        "backend.agent.caducean_trajectory", fromlist=["CaduceanTrajectoryRecorder"]
    ).CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))
    for i in range(6):
        seed.record_session_exit(f"se{i}", "general", natural_exit=True)

    # Real OuterTuner pointed at the seeded recorder.
    tuner = OuterTuner(recorder=seed, held_out_count=3)
    change = tuner.run_once(domain="general")
    assert change is not None, "outer loop proposes a change with enough data"
    # And the top-level entry point is safe to call (no data -> None, no raise).
    out = run_outer_loop(k.session_id, domain="general")
    assert out is None or isinstance(out, dict)
