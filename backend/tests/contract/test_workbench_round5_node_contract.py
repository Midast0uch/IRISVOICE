"""Round 5 wave B: the node loop, the run_python handler, the step verdict and the code-node
prompts (advisor Round 5 on TG-7 v2 stage 1; owner 2026-11-16).

G1   a Workbench step that closed on a PASSED harness check is VERIFIED (scorer "harness_check"),
     the embedding verifier is skipped; a failed/absent check takes today's path.
K1a  run_node injects stdout_max (1,200 at a window <= 8,192 rising to 12,000 at >= 32,768);
     the handler gives it to the digest only for a run that assigned none of the brief's outputs.
E1   the handler reports assigned_outputs; a run that assigned none of the outputs is a look
     (not a failed check); a run that raised is still a real attempt.
E2   an escalation is never the last call: one extra call, once per node, only after an escalation.
Note after a look: "The next run must assign: <names>." once per look.
S3   a step after a file-changing step of the turn stays on the menu path.
S2/B8 the _WB_SYSTEM example list and the repair prompt wording.  R2: the code node's ground.
infer forwards reasoning_effort only when set.

Broken-copy demonstrations: WB_NODE_FILE (node.py copy), WB_EXECUTOR_FILE (node_executor copy),
WB_BRIDGE_FILE (tool_bridge copy), as in test_workbench_repair_contract / _check_contract."""
import asyncio
import importlib
import importlib.util
import json
import os
import sys
from types import SimpleNamespace

import pytest

from backend.tests.contract import _wb_common as common
from backend.tests.contract import test_workbench_repair_contract as repair_mod
from backend.tests.contract.test_workbench_repair_contract import (  # noqa: F401 - fixtures
    _CHECK, _node_module, _tool, _TOOLS, repair_node)

client_mod = common.mod("client")


def _load(env, default):
    path = os.environ.get(env)
    if not path:
        return importlib.import_module(default)
    spec = importlib.util.spec_from_file_location("_broken_" + env.lower(), path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


bridge_mod = _load("WB_BRIDGE_FILE", "backend.agent.tool_bridge")


@pytest.fixture(autouse=True)
def _drain_code_rows():
    """Every run_python writes a tool_results row on its lane; wait for the lane after each test."""
    yield
    from backend import conversation_store as cs

    cs._tr_lane().flush(10.0)


def _run(k):
    return k._der_run_node(k.item, "sess", "turn-1", [])


def _g(k):
    return k._der_run_node.__func__.__globals__


def _executor():
    """The node_executor the fixture's kernel really runs (a WB_EXECUTOR_FILE copy is registered
    in sys.modules by the fixture; a plain import gives the real one)."""
    return importlib.import_module("backend.agent.node_executor")


# --- G1 ------------------------------------------------------------------------------------
def test_g1_a_code_node_closed_on_a_passed_check_marks_the_step(repair_node):
    k = repair_node
    k.scripts += ["result = 42"]
    _text, ok = _run(k)
    assert ok is True
    assert getattr(k.item, "wb_check_passed", None) is True


def test_g1_a_node_that_never_passes_its_check_does_not_mark_the_step(repair_node):
    k = repair_node
    k.scripts += [f"result = {i}" for i in range(10)]
    _text, ok = _run(k)
    assert ok is False
    assert getattr(k.item, "wb_check_passed", None) is not True


def test_g1_a_two_step_plan_still_runs_s2_after_s1_passes_its_check(repair_node):
    k = repair_node
    k.scripts += ["result = 42", "result = 42"]
    _t1, ok1 = _run(k)
    s2 = SimpleNamespace(**dict(vars(k.item), step_id="s2"))
    _t2, ok2 = k._der_run_node(s2, "sess", "turn-1", [])
    assert ok1 is True and ok2 is True
    assert k.roles == ["tool_execution", "tool_execution"]          # s2 ran its own node
    assert s2.wb_check_passed is True and k.item.wb_check_passed is True


def _finalize(item, step_success=True):
    """Drive the REAL _der_finalize_step; return (verify spy, the trace records)."""
    from unittest.mock import MagicMock, patch

    from backend.agent import agent_kernel

    kernel = MagicMock()
    kernel.conversation_id = "conv"
    kernel.resolve_context_window.return_value = 8000
    kernel._memory_interface = None
    kernel._mcm_orch = None
    kernel._der_last_u_mag = 0.0
    kernel._verify_step_result.return_value = "UNVERIFIED"      # what the embedding verifier said
    records = []
    trace = SimpleNamespace(record=lambda kind, **kw: records.append((kind, kw)))
    with patch("backend.agent.event_bus.get_event_bus", return_value=MagicMock()), \
            patch("backend.agent.der_trace.get_der_trace", return_value=trace):
        agent_kernel.AgentKernel._der_finalize_step.__get__(kernel, agent_kernel.AgentKernel)(
            item=item, step_result="total = 26\n\ncheck: passed", step_success=step_success,
            step_outputs=[], completed_items=[], _tokens_used=0, _token_budget=50000,
            _session="sess", _turn_id="t1", _phase=0, is_mature=False, _live_ctx=None,
            plan=None, context_package=None, queue=MagicMock(), verdict=MagicMock())
    return kernel._verify_step_result, records


def _node_item(**extra):
    return SimpleNamespace(step_id="s1", step_number=1, description="Compute the total",
                           tool=None, expected_output="the total is 26", result="total = 26",
                           is_subloop=False, node_call_log=[], **extra)


def test_g1_a_successful_step_with_a_passed_check_is_verified_without_the_embedding_verifier():
    verify, records = _finalize(_node_item(wb_check_passed=True))
    verify.assert_not_called()
    labels = [kw["verified_label"] for kind, kw in records if kind == "verify_label"]
    assert labels == ["VERIFIED"]
    assert [kw["scorer_tag"] for kind, kw in records if kind == "verify"] == ["harness_check"]


def test_g1_no_check_or_a_failed_step_takes_todays_verifier_path():
    for item, success in ((_node_item(), True), (_node_item(wb_check_passed=False), True),
                          (_node_item(wb_check_passed=True), False)):
        verify, records = _finalize(item, success)
        verify.assert_called_once()
        assert "harness_check" not in [kw.get("scorer_tag") for _k, kw in records]


# --- K1a -----------------------------------------------------------------------------------
def test_k1a_the_stdout_budget_rises_linearly_with_the_window():
    f = _executor()._stdout_budget
    assert [f(0), f(4096), f(8192)] == [1200, 1200, 1200]
    assert f(32768) == 12000 and f(100000) == 12000
    assert f(20480) == 6600                      # 1200 + 12288 * 10800 / 24576
    assert f(8193) >= 1200 and f(32767) <= 12000


def test_k1a_run_node_injects_stdout_max_and_strips_a_model_written_one(repair_node, monkeypatch):
    k = repair_node
    seen = []
    tb = sys.modules["backend.agent.tool_bridge"]
    real = tb._run_python_tool

    async def spy(bridge, params, session_id, cwd):
        seen.append(dict(params))
        return await real(bridge, params, session_id, cwd)
    monkeypatch.setattr(tb, "_run_python_tool", spy)
    real_call = repair_mod._run_call

    def call(i, code):
        c = real_call(i, code)
        c["function"]["arguments"] = json.dumps(dict(json.loads(c["function"]["arguments"]),
                                                     stdout_max=99999))
        return c
    monkeypatch.setattr(repair_mod, "_run_call", call)
    k.scripts += ["result = 42"]
    _run(k)
    assert [p.get("stdout_max") for p in seen] == [1200]       # unknown window -> 1,200


@pytest.fixture
def run_python(monkeypatch):
    """The REAL _run_python_tool against a real worker (only the manager is stubbed)."""
    from backend.agent.workbench import manager

    workdir = common.make_workdir()
    c = client_mod.WorkbenchClient(common.PYTHON, workdir)
    c.start()
    monkeypatch.setattr(manager, "get_manager",
                        lambda: SimpleNamespace(workbench_for=lambda conv, cwd: c, touch=lambda conv: None))
    br = SimpleNamespace(_active_conversation_id={})

    def call(params):
        return asyncio.run(bridge_mod._run_python_tool(br, params, "s-r5", "."))
    try:
        yield call
    finally:
        c.close()
        common.drop(workdir)


_LOOK = "print('x' * 3000)"


def test_k1a_a_look_run_gets_the_larger_stdout_budget(run_python):
    out = run_python({"code": _LOOK, "outputs": ["result"], "stdout_max": 4000})
    assert "chars cut" not in out["text"] and out["text"].count("x") == 3000


def test_k1a_a_run_that_assigned_an_output_keeps_todays_digest(run_python):
    out = run_python({"code": _LOOK + "\nresult = 1", "outputs": ["result"], "stdout_max": 4000})
    assert "chars cut" in out["text"] and out["text"].count("x") == 1200


def test_k1a_without_stdout_max_the_digest_is_todays(run_python):
    out = run_python({"code": _LOOK, "outputs": ["result"]})
    assert "chars cut" in out["text"] and out["text"].count("x") == 1200


# --- E1 ------------------------------------------------------------------------------------
def test_e1_the_handler_reports_the_assigned_outputs(run_python):
    out = run_python({"code": "a = 1\nb = 2", "outputs": ["b", "c", "a"]})
    assert out["assigned_outputs"] == ["b", "a"]                # the brief's order
    assert run_python({"code": "z = 1", "outputs": ["a"]})["assigned_outputs"] == []


def test_e1_a_look_after_a_wrong_first_attempt_is_not_a_failed_check(repair_node):
    k = repair_node
    k.scripts += ["result = 1", "peek = 5", "result = 2", "exec(skeleton)"]
    _text, ok = _run(k)
    assert ok is True
    # the look (call 2: check False, not NameError, because result exists) did not count: the
    # Brain is called after the SECOND real failure (call 3)
    assert k.roles == ["tool_execution"] * 3 + ["reasoning", "tool_execution"]


def test_e1_a_run_that_raised_is_still_a_real_attempt(repair_node):
    k = repair_node
    k.scripts += ["result = 1", "raise ValueError('x')", "exec(skeleton)"]
    _text, ok = _run(k)
    assert ok is True
    assert k.roles == ["tool_execution"] * 2 + ["reasoning", "tool_execution"]


def test_e1_is_exploration_is_false_without_outputs_or_without_the_report():
    ex = _executor()
    ctx = SimpleNamespace(wb_outputs=("result",))
    assert ex._is_exploration(ctx, {"ok": True, "check_error": "", "assigned_outputs": []}) is True
    assert ex._is_exploration(ctx, {"ok": True, "check_error": "", "assigned_outputs": ["result"]}) is False
    assert ex._is_exploration(ctx, {"ok": True, "check_error": ""}) is False
    assert ex._is_exploration(SimpleNamespace(wb_outputs=()), {"ok": True, "assigned_outputs": []}) is False


# --- E2 ------------------------------------------------------------------------------------
def test_e2_an_escalation_at_the_last_allowed_call_gets_one_more_call(repair_node):
    k = repair_node
    # calls 1-4 explore (NameError), 5 and 6 are real failures: the escalation lands at call 6
    k.scripts += [f"peek = {i}" for i in range(4)] + ["result = 1", "result = 2", "exec(skeleton)"]
    _text, ok = _run(k)
    assert ok is True
    assert k.roles == ["tool_execution"] * 6 + ["reasoning", "tool_execution"]


def test_e2_the_extra_call_is_bounded_to_one_per_node(repair_node):
    k = repair_node
    k.scripts += [f"peek = {i}" for i in range(4)] + ["result = 1", "result = 2", "result = 3",
                                                      "exec(skeleton)"]
    _text, ok = _run(k)
    assert ok is False
    assert [c["tool"] for c in k.item.node_call_log] == ["run_python"] * 7
    assert k.roles.count("reasoning") == 1


def test_e2_no_escalation_no_extra_call(repair_node):
    k = repair_node
    k.scripts += [f"peek = {i}" for i in range(10)]
    _text, ok = _run(k)
    assert ok is False
    assert [c["tool"] for c in k.item.node_call_log] == ["run_python"] * 6
    assert k.roles.count("reasoning") == 0


# --- look note -----------------------------------------------------------------------------
_NOTE = "The next run must assign: result."


def test_the_look_note_comes_once_per_look_and_not_after_a_real_failure(repair_node):
    k = repair_node
    k.scripts += ["peek = 1", "peek = 2", "result = 1", "result = 42"]
    _text, ok = _run(k)
    assert ok is True
    assert k.prompts[0].count(_NOTE) == 0
    assert k.prompts[1].count(_NOTE) == 1          # after look 1
    assert k.prompts[2].count(_NOTE) == 2          # one per look, never repeated for the same look
    assert k.prompts[3].count(_NOTE) == 2          # a real failure adds none


def test_the_look_note_names_only_the_unassigned_outputs(repair_node):
    k = repair_node
    k.item.check, k.item.outputs = "result == 42 and other == 1", ["result: int", "other: int"]
    k.scripts += ["result = 42", "other = 1"]
    _text, ok = _run(k)
    assert ok is True
    assert "The next run must assign: other." in k.prompts[1]
    assert "must assign: result" not in k.prompts[1]


# --- S3 ------------------------------------------------------------------------------------
def test_s3_a_step_after_a_change_stays_on_the_menu_path(repair_node):
    k = repair_node
    code_mode = _g(k)["_wb_code_mode"]
    goal, tools = "Read the files and compute the result", _TOOLS
    assert code_mode(goal, tools, ".", k.item) is True
    k.item.wb_after_change = True
    assert code_mode(goal, tools, ".", k.item) is False


def test_s3_the_probe_reads_the_turns_earlier_steps(repair_node):
    k = repair_node
    probe = _g(k)["_wb_after_change"]
    me = SimpleNamespace(step_id="s2", depends_on=["s1"])

    def step(sid, **kw):
        base = dict(result="done", tool=None, node_call_log=[], description="Read a.py")
        return SimpleNamespace(step_id=sid, **dict(base, **kw))

    def q(*items):
        return SimpleNamespace(items=list(items) + [me])
    assert probe(me, q(step("s1"))) is False                                       # a read
    assert probe(me, q(step("s1", tool="write_file"))) is True                     # a direct write
    assert probe(me, q(step("s1", node_call_log=[{"tool": "edit_file", "ok": True}]))) is True
    assert probe(me, q(step("s1", node_call_log=[{"tool": "edit_file", "ok": False}]))) is False
    assert probe(me, q(step("s1", result="", description="Edit config.yaml"))) is True   # a WRITE dependency
    assert probe(me, q(step("s9", result="", description="Edit config.yaml"))) is False  # not a dependency
    assert probe(me, None) is False


def test_s3_the_caller_sets_the_flag_only_with_the_workbench_on():
    from backend.tests._kernel_source import kernel_function_source

    src = kernel_function_source("_der_run_step_execution")
    assert "if _wb_on():" in src and "item.wb_after_change = _wb_after_change(item, queue)" in src


# --- S2 / B8 -------------------------------------------------------------------------------
def test_s2_the_example_list_starts_with_pytest_and_drops_tsc():
    system = _node_module()._WB_SYSTEM
    assert ("Other languages run from the same script: sh('python -m pytest -q'), sh('node app.js'), "
            "sh('npm test'), or a JavaScript snippet with sh('node -', input=js_code); "
            "sh() returns a dict with code, stdout, stderr.") in system
    assert "npx tsc" not in system


def test_b8_the_repair_prompt_asks_for_one_sentence_on_the_cause():
    mod = _node_module()
    assert "one sentence on the cause" in mod._WB_REPAIR_PROMPT
    assert "at most three sentences" not in mod._WB_REPAIR_PROMPT
    assert mod._WB_REPAIR_MAX_TOKENS == 4096


# --- R2 ------------------------------------------------------------------------------------
def test_r2_the_ground_budget_rises_with_the_window(repair_node):
    f = _g(repair_node)["_wb_ground_chars"]
    assert [f(0), f(8192)] == [1200, 1200] and f(32768) == 4000 and f(65536) == 4000
    assert f(20480) == 2600


def test_r2_the_planner_call_keeps_profile_off_and_1200_chars(repair_node, monkeypatch):
    from backend.agent.workbench import ground as ground_mod

    asked = []
    monkeypatch.setattr(ground_mod, "ground", lambda workdir, **kw: asked.append(kw) or "G")
    assert _g(repair_node)["_wb_ground_text"]("some-folder", "req") == "G"
    assert asked == [{"text": "req", "profile": False, "max_chars": 1200}]


def test_r2_the_code_node_asks_for_the_profile(repair_node, monkeypatch):
    from backend.agent.workbench import ground as ground_mod

    k = repair_node
    asked = []
    monkeypatch.setattr(ground_mod, "ground", lambda workdir, **kw: asked.append(kw) or "G")
    k._tool_bridge = SimpleNamespace(_session_workdirs={"sess": "some-folder"})
    k.scripts += ["result = 42"]
    _text, ok = _run(k)
    assert ok is True
    assert len(asked) >= 1 and all(a["profile"] is True for a in asked)
    assert asked[0]["max_chars"] == 1200            # the fixture's window is unknown -> 1,200


# --- infer ---------------------------------------------------------------------------------
def test_infer_forwards_reasoning_effort_only_when_set():
    from backend.agent.agent_kernel import AgentKernel

    seen = []
    k = AgentKernel.__new__(AgentKernel)
    k._router = SimpleNamespace(last_usage=None,
                                generate=lambda role, messages, **kw: seen.append(kw) or ("t", "", []))
    k._accrue_tokens = lambda *a, **kw: None
    AgentKernel.infer(k, "p", max_tokens=64, reasoning_effort="low")
    AgentKernel.infer(k, "p", max_tokens=64)
    assert seen[0]["reasoning_effort"] == "low"
    assert "reasoning_effort" not in seen[1]
