"""CLM-11 Round 3 / T7.12: the check. The harness (not the model) hands a step's check
expression to run_python; the worker evaluates it after a clean run in the same
namespace; a pass closes the node with ONE model call; a second failure fires the
escalation hook once. No model call judges the check, and the run_python schema has
no `check` parameter.

Modules under test: the workbench package (WORKBENCH_PKG / WORKBENCH_PKG_PATH), the
bridge (WB_BRIDGE_FILE) and the node loop (WB_EXECUTOR_FILE) can each be pointed at a
deliberately broken copy; that is how the failure demonstrations run.
"""
import asyncio
import importlib
import importlib.util
import inspect
import json
import os
import sys
from types import SimpleNamespace

import pytest

from backend.tests.contract import _wb_common as common


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
executor = _load("WB_EXECUTOR_FILE", "backend.agent.node_executor")
client_mod = common.mod("client")
protocol = common.mod("protocol")


@pytest.fixture
def wb():
    workdir = common.make_workdir()
    c = client_mod.WorkbenchClient(common.PYTHON, workdir)
    c.start()
    try:
        yield c
    finally:
        c.close()
        common.drop(workdir)


@pytest.fixture
def run_python(wb, monkeypatch):
    """The REAL _run_python_tool against a real worker (only the manager is stubbed)."""
    from backend.agent.workbench import manager

    seen = {"checks": []}
    real_exec = wb.exec

    def spy(code, timeout_s=60, check=None, on_call=None):
        seen["checks"].append(check)
        return real_exec(code, timeout_s, check, on_call)

    wb.exec = spy
    stub = SimpleNamespace(workbench_for=lambda conv, cwd: wb, touch=lambda conv: None)
    monkeypatch.setattr(manager, "get_manager", lambda: stub)
    br = SimpleNamespace(_active_conversation_id={})

    def call(params):
        return asyncio.run(bridge_mod._run_python_tool(br, params, "s-check", "."))

    call.seen = seen
    return call


# --- worker ------------------------------------------------------------------
def test_v1_exec_frame_without_check_is_valid():
    frame = protocol.decode(b'{"v":1,"op":"exec","id":1,"code":"x = 1","timeout_s":60}\n')
    assert "check" not in frame


def test_no_check_means_no_check_key_in_the_reply(wb):
    rep = wb.exec("x = 1")
    assert rep["ok"] and "check" not in rep


def test_the_check_runs_in_the_namespace_after_a_clean_body(wb):
    assert wb.exec("n = 3", check="n == 3")["check"] == {"ok": True, "error": None}
    assert wb.exec("n = 4", check="n == 3")["check"] == {"ok": False, "error": None}


def test_a_raising_check_is_a_short_failed_result(wb):
    rep = wb.exec("n = 3", check="missing_name > 1")
    assert rep["ok"] is True                       # the body ran; only the check failed
    assert rep["check"]["ok"] is False
    assert rep["check"]["error"].startswith("NameError: ") and len(rep["check"]["error"]) <= 200


def test_a_raising_body_skips_the_check(wb):
    # the check would be True; it must not run (and so cannot rescue a raised body)
    rep = wb.exec("raise ValueError('boom')", check="True")
    assert rep["ok"] is False
    assert rep["check"] == {"ok": False, "error": "body raised"}


def test_a_check_cannot_hang_the_worker(wb):
    rep = wb.exec("pass", timeout_s=1, check="[1 for _ in iter(int, 1)]")   # never ends
    assert rep["check"] == {"ok": False, "error": "check timed out"}      # the same watchdog
    assert wb.exec("1 + 1")["value"] == "2"        # and the worker is still alive


# --- the bridge ----------------------------------------------------------------
def test_run_python_reports_check_ok_and_one_digest_line(run_python):
    ok = run_python({"code": "n = 3", "purpose": "set n", "check": "n == 3"})
    assert ok["check_ok"] is True and "check_error" not in ok
    assert ok["text"].splitlines()[-1] == "check: passed"
    bad = run_python({"code": "n = 4", "purpose": "set n", "check": "n == 3"})
    assert bad["check_ok"] is False
    assert bad["text"].splitlines()[-1].startswith("check: failed - ")
    assert sum(1 for ln in bad["text"].splitlines() if ln.startswith("check:")) == 1


def test_run_python_without_a_check_has_no_check_fields(run_python):
    out = run_python({"code": "n = 3", "purpose": "set n"})
    assert "check_ok" not in out and "check_error" not in out and "check:" not in out["text"]
    assert run_python.seen["checks"] == [None]


def test_the_check_is_stripped_and_capped_at_2000_chars(run_python):
    run_python({"code": "n = 3", "check": "  True  # " + "x" * 5000})
    sent = run_python.seen["checks"][0]
    assert len(sent) == 2000 and sent.startswith("True")


def test_the_run_python_schema_has_no_check_parameter():
    src = inspect.getsource(importlib.import_module("backend.agent.tool_bridge"))
    start = src.index('{"name": "run_python", "description"')
    block = src[start:src.index('"category": "shell"}', start)]
    assert '"code"' in block and '"check"' not in block      # the harness injects it


# --- the node loop --------------------------------------------------------------
def _call(i, code, purpose="fill the outputs"):
    return {"id": f"c{i}", "type": "function", "function": {
        "name": "run_python", "arguments": json.dumps({"code": code, "purpose": purpose})}}


def _node(run_python, script, check):
    """run_node over the real bridge and worker; `script` = the model's answers in order."""
    seen = {"gen": 0, "messages": [], "escalations": []}

    def gen(role, messages, tools=None, **kw):
        seen["messages"].append(json.dumps(messages))
        i = seen["gen"]
        seen["gen"] += 1
        return script[min(i, len(script) - 1)]

    def hook(attempt, code, digest):
        seen["escalations"].append((attempt, code))
        return "REPAIR BRIEF: build the dict first"

    ctx = executor.NodeContext(
        generate=gen, execute=lambda n, p: run_python(p),
        format_result=lambda n, r: r.get("text", ""),
        tools=[{"type": "function", "function": {"name": "run_python", "parameters": {}}}],
        check=check, on_check_failed=hook, max_calls=6)
    return ctx, seen


def test_a_passing_check_closes_the_node_with_one_model_call(run_python):
    ctx, seen = _node(run_python, [("", "", [_call(1, "total = 5")])], "total == 5")
    r = executor.run_node("compute the total", ctx)
    assert r.success is True
    assert seen["gen"] == 1                         # no second call, none to judge the check
    assert len(r.calls) == 1 and r.calls[0]["tool"] == "run_python"


def test_a_check_failing_twice_escalates_once_and_the_note_reaches_the_model(run_python):
    ctx, seen = _node(run_python, [
        ("", "", [_call(1, "total = 4")]),
        ("", "", [_call(2, "total = 3")]),
        ("Could not fix it.\nSTATUS: failed: check", "", []),
    ], "total == 5")
    r = executor.run_node("compute the total", ctx)
    assert seen["escalations"] == [(2, "total = 3")]
    assert "REPAIR BRIEF: build the dict first" in seen["messages"][2]       # the next message
    assert "REPAIR BRIEF" not in seen["messages"][1]                          # not before attempt 2
    assert r.success is False


def test_no_check_closes_by_status_as_before(run_python):
    ctx, seen = _node(run_python, [
        ("", "", [_call(1, "total = 5")]),
        ("Computed it.\nSTATUS: done", "", []),
    ], "")
    r = executor.run_node("compute the total", ctx)
    assert seen["gen"] == 2 and r.success is True and seen["escalations"] == []


def test_a_run_python_step_has_a_target_from_its_purpose():
    assert executor._target({"code": "x = 1", "purpose": "count the ERROR lines"}) == "count the ERROR lines"
    assert len(executor._target({"code": "x", "purpose": "p " * 100})) <= 80
    assert executor._target({"path": "a.py"}) == "a.py"
