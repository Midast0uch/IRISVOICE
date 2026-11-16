"""CLM-11 Round 3 / T7.14 + T7.15: the repair loop and its Oracle shadow question.

T7.14 - the escalation hook, proven end to end. The REAL `AgentKernel._der_run_node`
(code mode) runs over a real Workbench worker and the real `_run_python_tool`; only the
router (it records the ROLE of each generate call) and the tool box are stand-ins. A step
with a brief and a check whose first scripts fail shows: two tool-model attempts, ONE
Brain call (the repair brief), a third tool-model attempt that passes. The Brain is never
called a second time (one escalation per node), and a node that keeps failing ends at
max_calls and goes to recovery.

T7.15 - `repair_route`: a shadow row per failed check (REPAIR or ESCALATE), labelled by
whether the next attempt passed. Nothing here changes what the node does.

The node module (WB_NODE_FILE), the executor (WB_EXECUTOR_FILE) and the shadow module
(WB_REPAIR_ROUTE_FILE) can be pointed at a deliberately broken copy for the failure
demonstrations; the workbench package through WORKBENCH_PKG / WORKBENCH_PKG_PATH.
"""
import asyncio
import importlib
import importlib.util
import json
import logging
import os
import sys
import threading
import types
from types import SimpleNamespace

import pytest

from backend.tests.contract import _wb_common as common

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


def _node_module():
    return _load("WB_NODE_FILE", "backend.agent.kernel.der.node")


def _tool(name, req=()):
    props = {k: {"type": "string"} for k in req}
    return {"type": "function", "function": {"name": name, "description": name, "parameters": {
        "type": "object", "properties": props, "required": list(req)}}}


_TOOLS = [_tool("read_file", ("path",)), _tool("run_python", ("code",))]
_CHECK = "result == 42"
_SKELETON = "result = 42"
_BRIEF_TEXT = "The script never set result. Run the skeleton.\n```python\n" + _SKELETON + "\n```"


def _run_call(i, code):
    return {"id": f"c{i}", "type": "function", "function": {
        "name": "run_python", "arguments": json.dumps({"code": code, "purpose": f"attempt {i}"})}}


@pytest.fixture
def repair_node(monkeypatch):
    """A stub kernel whose REAL _der_run_node runs a code-mode node with a brief + check."""
    from backend.agent import tool_bridge
    from backend.agent.agent_kernel import AgentKernel
    from backend.agent.workbench import manager

    monkeypatch.setenv("IRIS_WORKBENCH", "1")
    ex_path = os.environ.get("WB_EXECUTOR_FILE")        # a deliberately broken run_node
    if ex_path:
        spec = importlib.util.spec_from_file_location("backend.agent.node_executor", ex_path)
        ex = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, "backend.agent.node_executor", ex)   # before exec: dataclasses
        spec.loader.exec_module(ex)
    workdir = common.make_workdir()
    c = client_mod.WorkbenchClient(common.PYTHON, workdir)
    c.start()
    stub = SimpleNamespace(workbench_for=lambda conv, cwd: c, touch=lambda conv: None)
    monkeypatch.setattr(manager, "get_manager", lambda: stub)

    roles, prompts, scripts = [], [], []
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "conv-wb-repair"
    k._tool_bridge = None
    k._der_turn_id = "turn-1"
    k._der_turn_active = True
    k._der_stop_requested = False
    k._der_card_hold = {"lock": threading.Lock(), "calls": 0, "released": False,
                        "turn": "turn-1", "queue": None, "plan": None}
    br = SimpleNamespace(_active_conversation_id={"sess": "conv-wb-repair"})

    class _Router:
        last_usage = None

        def generate(self, role, messages, **kw):
            roles.append(role)
            prompts.append(json.dumps(messages))
            if role == "reasoning":                 # the Brain: the repair brief
                return _BRIEF_TEXT, "", []
            n = roles.count("tool_execution")
            if kw.get("tools") is not None and n <= len(scripts):
                return "", "", [_run_call(n, scripts[n - 1])]
            return "Gave up.\nSTATUS: failed: check", "", []

        def resolve(self, role):
            return SimpleNamespace(id=f"{role}-model")   # two models: a helper would exist

    class _Box:
        def dispatch(self, decision, **kw):
            raw = asyncio.run(tool_bridge._run_python_tool(br, decision.params, "sess", ".")) \
                if decision.tool == "run_python" else {"success": True, "content": "ok"}
            return SimpleNamespace(result=raw, error="")

        def record_shadow_tool_choice(self, **kw):
            pass

        def record_tool_call(self, *a, **kw):
            pass

    k._router = _Router()
    k._get_tool_box = lambda: _Box()
    k._get_openai_tools = lambda: _TOOLS
    k._accrue_tokens = lambda *a, **kw: None
    k._der_tool_deadline = lambda name: 60.0
    k._format_tool_result_for_step = lambda raw, name: json.dumps(raw, default=str)[:400]
    mod = _node_module()
    k._der_run_node = types.MethodType(mod.DerNodeMixin._der_run_node, k)
    item = SimpleNamespace(description="Read the files and compute the result", objective_anchor="",
                           expected_output="", parent_description="", review_feedback="",
                           step_id="s1", node_calls=[], node_call_log=[],
                           check=_CHECK, inputs=["path: a.py"], outputs=["result: int"],
                           approach="set result", tools=[])
    k.item, k.scripts, k.roles, k.prompts = item, scripts, roles, prompts
    try:
        yield k
    finally:
        c.close()
        common.drop(workdir)


# --- T7.14 -----------------------------------------------------------------------
def test_two_failed_attempts_one_brain_call_a_third_attempt_that_passes(repair_node, caplog):
    k = repair_node
    k.scripts += ["result = 1", "result = 2", "exec(skeleton)"]
    with caplog.at_level(logging.INFO):
        _text, ok = k._der_run_node(k.item, "sess", "turn-1", [])
    assert ok is True
    # the roles in order: two tool-model attempts, ONE Brain call, the third attempt
    assert k.roles == ["tool_execution", "tool_execution", "reasoning", "tool_execution"]
    brain_prompt = k.prompts[2]
    assert "set result" in brain_prompt and "path: a.py" in brain_prompt      # the brief
    assert _CHECK in brain_prompt                                              # the check
    assert "result = 2" in brain_prompt                                        # the LAST code
    assert "check: failed" in brain_prompt                                     # the digest
    assert "result = 1" not in brain_prompt                                    # last, not first
    # the skeleton reached the namespace and the note reached attempt 3
    assert "REPAIR BRIEF" in k.prompts[3] and "skeleton" in k.prompts[3]
    assert "REPAIR BRIEF" not in k.prompts[1]                                  # not before attempt 2
    msgs = [r.getMessage() for r in caplog.records]
    assert "[workbench] conv=conv-wb-repair escalated to the Brain after 2 failed checks" in msgs


def test_the_brain_is_called_once_per_node_and_the_node_ends_at_max_calls(repair_node, caplog):
    k = repair_node
    k.scripts += [f"result = {i}" for i in range(10)]          # every attempt fails the check
    with caplog.at_level(logging.INFO):
        _text, ok = k._der_run_node(k.item, "sess", "turn-1", [])
    assert ok is False                                        # goes to DER recovery as before
    assert k.roles.count("reasoning") == 1                    # a 4th and 5th failure: no second call
    # max_calls (6) bound the node: six run_python attempts, then the node's own forced
    # closing STATUS call (tools=None) - that one is not an attempt and runs no script
    assert k.roles.count("tool_execution") == 7
    assert k.roles[:4] == ["tool_execution", "tool_execution", "reasoning", "tool_execution"]
    assert sum("escalated to the Brain" in r.getMessage() for r in caplog.records) == 1
    assert [c["tool"] for c in k.item.node_call_log] == ["run_python"] * 6


# --- T7.15: repair_route shadow rows ------------------------------------------------
def _rr_module():
    """The shadow module the node uses. WB_REPAIR_ROUTE_FILE points at a deliberately
    broken copy; it is installed under the REAL name (node.py imports it by name)."""
    path = os.environ.get("WB_REPAIR_ROUTE_FILE")
    if not path:
        return importlib.import_module("backend.agent.repair_route_shadow")
    spec = importlib.util.spec_from_file_location("backend.agent.repair_route_shadow", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeEngine:
    """Records every consult (and the thread it ran on); answers REPAIR 0.7."""

    model_id = "fake-d1"

    def __init__(self, raises=False):
        self.calls, self.raises = [], raises

    def decide(self, consumer_id, options, frame, instruction=None):
        self.calls.append((consumer_id, list(options), dict(frame),
                           threading.current_thread().name))
        if self.raises:
            raise RuntimeError("engine down")
        from backend.agent import decision_engine as de

        return de.DecisionScore(
            consumer_id, "REPAIR", 0.7,
            (de.CandidateScore("REPAIR", -0.3, 0.7), de.CandidateScore("ESCALATE", -1.2, 0.3)), 4)


@pytest.fixture
def shadow(repair_node, monkeypatch):
    """The node of `repair_node` with the repair_route shadow wired to a fake engine and a
    list sink (the kernel's own `_shadow_row_sink` seam, as in production)."""
    import backend.agent as agent_pkg
    from backend.agent import decision_engine as de
    from backend.utils.durability_queue import lane

    rr = _rr_module()
    monkeypatch.setitem(sys.modules, "backend.agent.repair_route_shadow", rr)
    monkeypatch.setattr(agent_pkg, "repair_route_shadow", rr, raising=False)
    rr.reset()
    rows, eng = [], _FakeEngine()
    repair_node._shadow_row_sink = rows.append
    monkeypatch.setattr(rr, "ENGINE", eng)
    token = de.set_scope(turn_id="turn-rr", step_id=None, node_exec_id=None)

    def drain():
        assert lane("oracle_shadow").flush(10.0)
        return sorted(rows, key=lambda r: r["attempt"])

    repair_node.rr, repair_node.rows, repair_node.eng, repair_node.drain = rr, rows, eng, drain
    yield repair_node
    de._SCOPE.reset(token)
    rr.set_row_sink(None)
    rr.reset()


def _run(k):
    k.roles.clear()
    return k._der_run_node(k.item, "sess", "turn-1", [])


def test_a_failed_check_writes_one_repair_route_row_with_the_evidence_fields(shadow):
    k = shadow
    k.item.check = "result['k'] == 42"
    k.scripts += ["result = 1", "result = {'k': 42}"]
    _text, ok = _run(k)
    assert ok is True
    (row,) = k.drain()                                  # ONE failed check -> ONE row
    assert row["consumer_id"] == "repair_route" and row["job"] == "judge_repair"
    assert row["criteria_version"] == "repair_route/v1" and row["shadow"] is True
    assert row["chosen"] in ("REPAIR", "ESCALATE") and row["rule_choice"] == "REPAIR"
    assert [c["name"] for c in row["candidates"]] == ["REPAIR", "ESCALATE"]
    assert row["attempt"] == 1 and row["turn_id"] == "turn-1" and row["step_id"] == "s1"   # the node scope
    # the evidence the engine read: attempt, error type, the check's own message
    (cid, options, frame, _thread) = k.eng.calls[0]
    assert cid == "repair_route" and options == ["REPAIR", "ESCALATE"]
    assert frame["attempt"] == "1" and frame["error_type"] == "CheckFailed"
    assert frame["check_error"].startswith("TypeError")
    assert "attempt: 1" in row["state"] and "error_type: CheckFailed" in row["state"]
    assert row["input_key"]


def test_a_raising_body_is_the_error_type_and_the_row_carries_the_typed_failure_counts(shadow):
    k = shadow
    conn = SimpleNamespace(execute=lambda sql, params: SimpleNamespace(
        fetchall=lambda: [("BUG", 2), ("DEAD_END", 1)]))
    k._memory_interface = SimpleNamespace(_mycelium=SimpleNamespace(conn=conn))
    k.scripts += ["raise ValueError('boom')", "result = 42"]
    _run(k)
    (row,) = k.drain()
    frame = k.eng.calls[0][2]
    assert frame["error_type"] == "ValueError" and frame["check_error"] == "body raised"
    assert frame["failure_rows"] == "BUG=2 OBSTACLE=0 DEAD_END=1"
    assert "failure_rows: BUG=2 OBSTACLE=0 DEAD_END=1" in row["state"]


def test_unreadable_failure_rows_leave_the_field_out_and_are_counted(shadow):
    k = shadow

    def boom(sql, params):
        raise RuntimeError("locked")
    k._memory_interface = SimpleNamespace(
        _mycelium=SimpleNamespace(conn=SimpleNamespace(execute=boom)))
    k.scripts += ["result = 1", "result = 42"]
    _run(k)
    k.drain()
    assert "failure_rows" not in k.eng.calls[0][2]            # never a made-up 0
    assert k.rr.stats()["failure_rows_unavailable"] == 1


def test_the_row_is_labelled_REPAIR_when_the_next_attempt_passes_without_the_brain(shadow):
    k = shadow
    k.scripts += ["result = 1", "result = 42"]
    _run(k)
    (row,) = k.drain()
    assert k.roles.count("reasoning") == 0
    assert row["outside_label"] == "REPAIR" and row["label_source"] == "outcome"
    assert row["label_detail"] == "pass_without_brief" and "unlabelled" not in row


def test_rows_are_labelled_ESCALATE_when_a_brief_came_before_the_pass(shadow):
    k = shadow
    k.scripts += ["result = 1", "result = 2", "exec(skeleton)"]
    _text, ok = _run(k)
    assert ok is True and k.roles.count("reasoning") == 1
    r1, r2 = k.drain()
    assert (r1["attempt"], r2["attempt"]) == (1, 2)
    assert (r1["rule_choice"], r2["rule_choice"]) == ("REPAIR", "ESCALATE")   # the stated rule
    assert r1["outside_label"] == r2["outside_label"] == "ESCALATE"
    assert r1["label_detail"] == "pass_after_brief"


def test_a_node_that_never_passes_writes_its_rows_unlabelled(shadow):
    k = shadow
    k.scripts += [f"result = {i}" for i in range(10)]
    _text, ok = _run(k)
    assert ok is False
    rows = k.drain()
    assert len(rows) == 6                                       # one per failed check, max_calls
    assert all("outside_label" not in r and r["unlabelled"] == "no_pass_after" for r in rows)
    assert k.rr.stats()["unlabelled"] == 6


def test_a_step_without_a_check_asks_no_question(shadow):
    k = shadow
    k.item.check = ""
    k.scripts += ["result = 1"]
    _run(k)
    assert k.drain() == [] and k.eng.calls == []


def test_the_consult_runs_on_the_lane_never_on_the_nodes_thread(shadow):
    k = shadow
    k.scripts += ["result = 1", "result = 42"]
    _run(k)
    k.drain()
    assert k.eng.calls and all(c[3] != threading.current_thread().name for c in k.eng.calls)
    assert all(c[3].startswith("iris-") for c in k.eng.calls)       # an ordered lane's worker


def test_the_frame_never_carries_the_script_the_brief_or_the_skeleton(shadow):
    k = shadow
    k.scripts += ["result = 1", "result = 2", "exec(skeleton)"]
    _run(k)
    rows = k.drain()
    for text in [json.dumps(c[2]) for c in k.eng.calls] + [r["state"] for r in rows]:
        assert "result = " not in text and "skeleton" not in text and "set result" not in text


def test_nothing_the_node_does_changes_with_the_shadow_even_when_it_fails(shadow):
    """Same roles, same outcome as the T7.14 trace with the engine down AND the sink
    raising; the failures are COUNTED (errors / sink_failed), never raised."""
    k = shadow
    k.eng.raises = True
    k.scripts += ["result = 1", "result = 2", "exec(skeleton)"]
    _text, ok = _run(k)
    assert ok is True
    assert k.roles == ["tool_execution", "tool_execution", "reasoning", "tool_execution"]
    k.drain()
    assert k.rows == [] and k.rr.stats()["errors"] == 2          # no score -> no row, counted

    def bad_sink(row):
        raise RuntimeError("ledger down")
    k.eng.raises = False
    k._shadow_row_sink = bad_sink
    k.rr.reset()
    k.scripts[:] = ["result = 1", "result = 2", "exec(skeleton)"]
    k.roles.clear()
    k.rr.set_row_sink(None)
    _text, ok = _run(k)
    assert ok is True
    assert k.roles == ["tool_execution", "tool_execution", "reasoning", "tool_execution"]
    k.drain()
    assert k.rr.stats()["sink_failed"] == 2 and k.rr.stats()["labelled"] == 2


def test_a_raising_observer_never_changes_what_the_node_does(shadow, monkeypatch):
    k = shadow

    def boom(self, *a, **kw):
        raise RuntimeError("observer bug")
    monkeypatch.setattr(k.rr.RepairTracker, "failed", boom)
    monkeypatch.setattr(k.rr.RepairTracker, "passed", boom)
    k.scripts += ["result = 1", "result = 2", "exec(skeleton)"]
    _text, ok = _run(k)
    assert ok is True
    assert k.roles == ["tool_execution", "tool_execution", "reasoning", "tool_execution"]


def test_the_question_is_declared_with_two_fixed_labels_and_no_decision_site():
    from backend.agent import decision_engine as de

    assert "repair_route" in de.CONSUMERS and "repair_route" in de.NO_DECISION_SITE
    assert de.declared_type("repair_route") == "choice"
    assert set(de.declared_criteria("repair_route")) == {"REPAIR", "ESCALATE"}
    job = de.oracle_job("repair_route")
    assert job.name == "judge_repair" and job.fields == (
        "attempt", "error_type", "check_error", "failure_rows")
