"""T3 (Wave 0) + Wave 1.5 evidence: per-turn LLM call count, 5-step FULL task.

Offline measurement of the DER loop's per-turn LLM call count, with and
without sub-loop batching (T25 / REQ-7), on two task shapes:

  no_splits   : 5 steps, all verified (sanity: both modes must agree)
  with_splits : 5 steps, step 3 FAILS -> _split_step -> 3 sub-loop children
                (one full batch group, BATCH_MAX_CHILDREN=3)

Modes:
  baseline : get_batcher patched to never group (offer/flush -> None) so
             children fall through to the pre-T25 per-child resolve path
             (agent_kernel._der_route_subloop_children 7413-7416). Each child
             resolves with its own router.generate call.
  batched  : real batcher; children group -> ONE dispatch_batch call; each
             child is pre-seeded with item.result and short-circuits at
             agent_kernel._der_run_step_execution:8270 (no resolve call).

The counting router wraps kernel._router and counts EVERY router.generate
call: planner (_plan_task:4284), per-step resolve (tool_decision.py:297),
and batched dispatch (batch_dispatch.py:259). Response discriminator:
  user msg contains "<subloop id="      -> batched call (return per-child tags)
  user msg contains "tool-selection"    -> resolve call (return tool JSON)
  otherwise                             -> planner call (return 5-step plan)

Prints machine-readable [MEASURE] lines and exits 0/1.
"""
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Running as a script puts scripts/ on sys.path, not the repo root. Insert
# the repo root so `import backend` resolves the same way pytest does.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.chdir(Path(__file__).resolve().parent.parent)

_PLAN_JSON = json.dumps({
    "strategy": "do_it_myself",
    "plan_title": "measure",
    "reasoning": "measurement task",
    "steps": [
        {"step_id": "s1", "step_number": 1, "description": "step one",
         "tool": None, "params": {}, "depends_on": [], "critical": True},
        {"step_id": "s2", "step_number": 2, "description": "step two",
         "tool": None, "params": {}, "depends_on": [], "critical": True},
        {"step_id": "s3", "step_number": 3, "description": "step three",
         "tool": None, "params": {}, "depends_on": [], "critical": True},
        {"step_id": "s4", "step_number": 4, "description": "step four",
         "tool": None, "params": {}, "depends_on": [], "critical": True},
        {"step_id": "s5", "step_number": 5, "description": "step five",
         "tool": None, "params": {}, "depends_on": [], "critical": True},
    ],
})


class _StubBatcher:
    """Never groups: mirrors the pre-T25 batcher state (offer returns None,
    no join point is ever flushed). Children fall through to per-child path."""
    def offer(self, child, quota_id=None):
        return None

    def flush(self, join_point=None):
        return None

    def flush_expired(self):
        return []

    def abandon(self, join_point=None):
        pass


class _CountingRouter:
    def __init__(self):
        self.calls = 0
        self.by_branch = {"planner": 0, "resolve": 0, "batch": 0, "other": 0}

    def generate(self, role_or_model, messages, tools=None, **kw):
        self.calls += 1
        user = "\n".join(
            (m.get("content", "") or "") for m in (messages or [])
            if m.get("role") == "user"
        )
        if "<subloop id=" in user:
            self.by_branch["batch"] += 1
            ids = re.findall(r'<subloop id="([^"]+)"', user)
            return (
                "\n".join(
                    f'<subloop id="{i}">\nresult for {i}\n</subloop>' for i in ids
                ),
                "",
                [],
            )
        if "tool-selection" in user:
            self.by_branch["resolve"] += 1
            # Derive UNIQUE params from the goal so the kernel's dispatch
            # dedup (tool+args hash) never flags a step as a duplicate call.
            _gm = re.search(r"GOAL:\s*(.+)", user)
            _goal = (_gm.group(1).strip() if _gm else f"step{self.calls}")
            return (
                json.dumps({
                    "kind": "tool", "tool": "run_command",
                    "params": {"cmd": f"pytest --run {_goal}"},
                    "rationale": "m",
                }),
                "",
                [],
            )
        self.by_branch["planner"] += 1
        return (_PLAN_JSON, "", [])


def _build_kernel(router):
    from backend.agent.agent_kernel import AgentKernel

    k = AgentKernel.__new__(AgentKernel)
    k._memory_interface = None
    k._tool_bridge = None
    k._reviewer = None
    k._mcm_orch = None
    k._trailing_director = None
    k._der_task_class = "full"
    k._der_completed_tools = []
    k._der_work_units = 30000
    k.conversation_id = "measure-conv"
    k.session_id = "measure-session"
    k._personality = None
    k._caducean_modulate_temperature = lambda base, sid: base
    k._get_failure_warnings = lambda text: "None"
    k._build_planning_prompt = lambda **kw: "PLAN PROMPT"
    k.resolve_context_window = lambda: 30000
    k._router = router
    k.infer = lambda prompt, **kw: SimpleNamespace(
        raw_text=('{"kind": "tool", "tool": "run_command", '
                  '"params": {"cmd": "pytest"}}')
    )
    k._der_live_cad_state = lambda sid: {"u": 0.2, "xi": 0.1, "x": 0.1, "y": 0.1}
    k._der_ledger = MagicMock()
    k._der_last_u_mag = 0.0
    k._der_crawl_attempts = {}
    k._cancel_requested = SimpleNamespace(is_set=lambda: False)
    k._selected_reasoning_model = "local-model"
    # Real _der_finalize_step re-verifies internally (agent_kernel.py:9122) and
    # FORCES step_success=False if _verify_step_result returns "FAILED" — a real
    # verifier would mark our stub outputs as failed and split every step.
    # Stub it deterministically: the caller controls failure via the shape.
    k._verify_step_result = lambda desc, exp, result, tool=None, success=True: (
        "VERIFIED" if success else "FAILED"
    )

    async def _execute_tool(tool_name=None, params=None, **kw):
        return {"success": True, "output": f"ran {tool_name} ok",
                "tool_name": tool_name}

    k._tool_bridge = SimpleNamespace(execute_tool=_execute_tool)
    return k


def _run_shape(router, with_splits, batched):
    """Drive the real DER loop for one (shape, mode) pair; return calls."""
    from backend.agent.agent_kernel import AgentKernel
    from backend.agent.der_loop import DirectorQueue, QueueItem

    # module-level registry stubs (smoke-test pattern) so the real
    # ToolDecisionBox can validate run_command offline. The box is built by
    # _get_tool_box (agent_kernel.py:8059) with get_registry_tools and
    # validate_tool_call imported DIRECTLY from tool_registry, so stub that
    # module (stubbing explorer's re-export is not enough).
    import backend.agent.explorer as ex
    import backend.agent.tool_registry as tr

    ex.get_registry_tools = lambda: [
        {"name": "run_command"}, {"name": "write_file"}]
    tr.get_registry_tools = lambda: [
        {"name": "run_command"}, {"name": "write_file"}]
    tr.validate_tool_call = lambda tool, params: (
        (True, None) if tool in ("run_command", "write_file")
        else (False, "unknown tool")
    )

    k = _build_kernel(router)
    ctx = SimpleNamespace()
    plan = k._plan_task("do the five step thing", session_id=k.session_id)
    steps = plan.steps
    plan_ns = SimpleNamespace(
        steps=steps, original_task="do the five step thing",
        plan_title="measure",
    )
    queue = DirectorQueue(objective="measure")
    items = []
    for s in steps:
        item = QueueItem(
            step_id=s.step_id, step_number=s.step_number,
            description=s.description, objective_anchor=plan.original_task,
            depth_layer=0, expected_output="done",
            tool=getattr(s, "tool", None), params=getattr(s, "params", {}),
            critical=getattr(s, "critical", True),
        )
        queue.add_item(item)
        items.append(item)

    def _finalize(item, result, success):
        k._der_finalize_step(
            item=item, step_result=result, step_success=success,
            step_outputs=[(item, result)], completed_items=[item],
            _tokens_used=0, _token_budget=50000,
            _session=k.session_id, _turn_id="turn-1", _phase=0,
            is_mature=False, _live_ctx=None, plan=plan_ns,
            context_package=ctx, queue=queue, verdict=MagicMock(),
        )

    for idx, item in enumerate(items):
        res, ok = k._der_run_step_execution(
            item, ctx, k.session_id, "turn-1", plan_ns
        )
        if with_splits and item.step_id == "s3":
            _finalize(item, "FAILED: could not complete the step", False)
        else:
            _finalize(item, res, ok)

    # Execute the sub-loop children the split routed into the queue. In
    # baseline mode they have NO pre-seeded result -> each resolves (1 call).
    # In batched mode they carry item.result -> short-circuit (0 calls).
    for child in queue.items[len(items):]:
        k._der_run_step_execution(child, ctx, k.session_id, "turn-1", plan_ns)

    return router.calls, getattr(k, "_der_turn_calls", 0)


def main():
    from backend.agent import agent_kernel
    from backend.agent.batch_dispatch import reset_batcher_for_testing

    results = {}

    # ---- Shape 1: no splits ---------------------------------------------
    for mode, batched in (("baseline", False), ("batched", True)):
        router = _CountingRouter()
        if batched:
            reset_batcher_for_testing()
            calls, der_calls = _run_shape(router, with_splits=False,
                                          batched=True)
        else:
            with patch("backend.agent.agent_kernel.get_batcher",
                       return_value=_StubBatcher()):
                calls, der_calls = _run_shape(router, with_splits=False,
                                              batched=False)
        results[("no_splits", mode)] = calls
        print(f"[MEASURE] shape=no_splits mode={mode} calls={calls}")

    # ---- Shape 2: with splits -------------------------------------------
    for mode, batched in (("baseline", False), ("batched", True)):
        router = _CountingRouter()
        if batched:
            reset_batcher_for_testing()
            calls, der_calls = _run_shape(router, with_splits=True, batched=True)
            print(f"[MEASURE] shape=with_splits mode=batched "
                  f"calls={calls} der_calls={der_calls}")
        else:
            with patch("backend.agent.agent_kernel.get_batcher",
                       return_value=_StubBatcher()):
                calls, der_calls = _run_shape(router, with_splits=True,
                                              batched=False)
            print(f"[MEASURE] shape=with_splits mode=baseline calls={calls}")
        results[("with_splits", mode)] = calls

    # ---- Assertions ------------------------------------------------------
    no_b = results[("no_splits", "baseline")]
    no_t = results[("no_splits", "batched")]
    sp_b = results[("with_splits", "baseline")]
    sp_t = results[("with_splits", "batched")]

    print(f"[MEASURE] reduction_with_splits={sp_b - sp_t}")

    ok = True
    if no_b != no_t:
        ok = False
        print(f"[MEASURE] FAIL: no_splits baseline({no_b}) != batched({no_t})")
    if not (sp_t < sp_b):
        ok = False
        print(f"[MEASURE] FAIL: batched({sp_t}) not below baseline({sp_b})")
    if not (sp_b - sp_t >= 1):
        ok = False
        print(f"[MEASURE] FAIL: reduction {sp_b - sp_t} < 1")

    print("T3_BASELINE_OK" if ok else "T3_BASELINE_FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
