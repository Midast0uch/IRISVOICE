"""CLM-11 Round 2 / T7.9: callbacks (protocol v2). Inside a script, `tools.<name>(**args)`
writes a `call` frame, blocks for the parent's `result` frame, and returns the value or
raises ToolError. The parent answers through the node's OWN dispatch path (the kernel's
`_execute` closure), not a second dispatcher.

Part 1 runs a real worker through the client. Part 2 drives the REAL
`AgentKernel._der_run_node` (code mode) and the real `_run_python_tool` with a stand-in
router and tool box; a script makes callbacks, the stand-in box records what reached it.

The workbench package (WORKBENCH_PKG / WORKBENCH_PKG_PATH) and the node module
(WB_NODE_FILE) can be pointed at a deliberately broken copy for the failure demonstrations.
"""
import ast
import asyncio
import importlib
import importlib.util
import json
import os
import statistics
import sys
import threading
import time
import types
from types import SimpleNamespace

import pytest

from backend.tests.contract import _wb_common as common

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


def _recorder(fail=None):
    """A handler that records its calls; `fail` = tool names that are denied."""
    calls = []

    def handler(tool, args):
        calls.append((tool, args))
        if tool in (fail or ()):
            return False, None, f"{tool} denied"
        return True, {"success": True, "tool": tool, "args": args}, None
    handler.calls = calls
    return handler


# --- protocol ----------------------------------------------------------------
def test_protocol_is_v2_and_decodes_call_and_result_frames():
    assert protocol.PROTOCOL_VERSION == 2
    call = protocol.decode(
        b'{"v":2,"ev":"call","id":4,"seq":1,"tool":"read_file","args":{"path":"a"}}\n')
    assert call["tool"] == "read_file"
    res = protocol.decode(b'{"v":2,"op":"result","id":4,"seq":1,"ok":true,"value":{},"error":null}\n')
    assert res["ok"] is True
    with pytest.raises(protocol.ProtocolError):
        protocol.decode(b'{"v":2,"ev":"call","id":4,"seq":1,"tool":"x"}\n')       # args missing
    assert protocol.decode(b'{"v":1,"op":"hello"}\n')["op"] == "hello"            # v1 stays valid


# --- worker + client -----------------------------------------------------------
def test_a_callback_reaches_the_handler_and_returns_its_value(wb):
    h = _recorder()
    rep = wb.exec("r = tools.read_file(path='a.py', n=2)\nr['tool']", on_call=h)
    assert rep["ok"] and rep["value"] == "'read_file'"
    assert h.calls == [("read_file", {"path": "a.py", "n": 2})]


def test_a_denied_tool_raises_toolerror_and_later_lines_do_not_run(wb):
    h = _recorder(fail=("edit_file",))
    rep = wb.exec("tools.edit_file(path='a.py')\nafter = 1", on_call=h)
    assert rep["ok"] is False and rep["error"]["type"] == "ToolError"
    assert "edit_file denied" in rep["error"]["message"]
    assert wb.inspect("'after' in globals()")["text"] == "False"        # line 2 never ran


def test_a_script_can_catch_toolerror_and_go_on(wb):
    h = _recorder(fail=("edit_file",))
    rep = wb.exec("try:\n    tools.edit_file(path='a')\nexcept ToolError as e:\n    msg = str(e)\n"
                  "tools.read_file(path='b')\nmsg", on_call=h)
    assert rep["ok"] and "edit_file denied" in rep["value"]
    assert [t for t, _ in h.calls] == ["edit_file", "read_file"]


def test_without_a_handler_a_tool_call_is_a_toolerror(wb):
    rep = wb.exec("tools.read_file(path='a')")
    assert rep["ok"] is False and rep["error"]["type"] == "ToolError"
    assert "not available" in rep["error"]["message"]


def test_the_budget_error_keeps_the_namespace_and_resets_per_exec(wb):
    h = _recorder()
    rep = wb.exec(
        "n = 0\nmsg = ''\ntry:\n    for i in range(40):\n        tools.noop()\n        n += 1\n"
        "except ToolError as e:\n    msg = str(e)\nn", on_call=h)
    assert rep["ok"] and rep["value"] == "24" and len(h.calls) == 24
    assert wb.inspect("msg")["text"].startswith("callback budget")
    rep2 = wb.exec("tools.noop()\nn", on_call=h)                        # a new exec: a fresh budget
    assert rep2["ok"] and rep2["value"] == "24" and len(h.calls) == 25  # `n` survived


def test_a_call_frame_of_a_stale_exec_is_ignored(wb):
    seen = []

    def handler(tool, args):
        seen.append(tool)
        if tool == "first":      # a frame of another exec lands in the queue meanwhile
            wb._q.put(protocol.encode({"v": 2, "ev": "call", "id": 99999, "seq": 1,
                                       "tool": "evil", "args": {}}))
        return True, {}, None

    before = wb.counts["stale_frames"]
    rep = wb.exec("tools.first()\ntools.second()\n'done'", on_call=handler)
    assert rep["ok"] and rep["value"] == "'done'"
    assert seen == ["first", "second"] and wb.counts["stale_frames"] == before + 1


def test_the_exec_deadline_and_the_watchdog_pause_while_a_callback_runs(wb):
    def slow(tool, args):
        time.sleep(4.5)           # > timeout_s + the 3 s kill grace: its time is the tool's, not the script's
        return True, {}, None

    # the script works a little after the callback: the client checks its deadline then
    rep = wb.exec("import time\ntools.slow()\ntime.sleep(0.4)\n'finished'", timeout_s=1, on_call=slow)
    assert rep["ok"] and rep["value"] == "'finished'"


def test_the_worker_clock_still_runs_after_a_callback(wb):
    rep = wb.exec("tools.noop()\nwhile True:\n    pass", timeout_s=1, on_call=_recorder())
    assert rep["ok"] is False and "timeout_s" in rep["error"]["message"]


def test_oversize_result_is_refused_not_sent(wb, monkeypatch):
    monkeypatch.setattr(client_mod, "RESULT_FRAME_MAX", 1000)
    rep = wb.exec("tools.big()", on_call=lambda t, a: (True, {"x": "y" * 5000}, None))
    assert rep["ok"] is False and "too large" in rep["error"]["message"]


def test_callback_round_trip_overhead_is_under_5_ms(wb, capsys):
    # 5 execs x 10 calls = 50 round trips (the budget is 24 per exec), timed in the script
    h = _recorder()
    ts = []
    for _ in range(5):
        rep = wb.exec(
            "import time, json\nts = []\nfor _ in range(10):\n    t = time.perf_counter()\n"
            "    tools.noop()\n    ts.append((time.perf_counter() - t) * 1000)\njson.dumps(ts)",
            on_call=h)
        assert rep["ok"], rep["error"]
        ts += json.loads(ast.literal_eval(rep["value"]))
    assert len(ts) == 50 and len(h.calls) == 50
    median_ms = statistics.median(ts)
    with capsys.disabled():
        print(f"\n[callbacks] median no-op round trip over 50 calls: {median_ms:.3f} ms")
    assert median_ms < 5.0


# --- the node: the callback goes through the node's own dispatch path -------------
def _node_module():
    path = os.environ.get("WB_NODE_FILE")
    if not path:
        return importlib.import_module("backend.agent.kernel.der.node")
    spec = importlib.util.spec_from_file_location("_broken_wb_node", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _tool(name, req=(), opt=()):
    props = {k: {"type": "string"} for k in (*req, *opt)}
    return {"type": "function", "function": {"name": name, "description": name, "parameters": {
        "type": "object", "properties": props, "required": list(req)}}}


_TOOLS = [_tool("read_file", ("path",)), _tool("edit_file", ("path", "old", "new")),
          _tool("run_command", ("command",)), _tool("grep_files", ("pattern",)),
          _tool("glob_files", ("pattern",)), _tool("list_directory", ("path",)),
          _tool("run_python", ("code",))]


def _run_call(i, code):
    return {"id": f"c{i}", "type": "function", "function": {
        "name": "run_python", "arguments": json.dumps({"code": code, "purpose": f"step {i}"})}}


@pytest.fixture
def code_node(monkeypatch):
    """A stub kernel whose REAL _der_run_node runs a code-mode node over a real worker."""
    from backend.agent.agent_kernel import AgentKernel
    from backend.agent import tool_bridge
    from backend.agent.workbench import manager

    monkeypatch.setenv("IRIS_WORKBENCH", "1")
    workdir = common.make_workdir()
    c = client_mod.WorkbenchClient(common.PYTHON, workdir)
    c.start()
    stub = SimpleNamespace(workbench_for=lambda conv, cwd: c, touch=lambda conv: None)
    monkeypatch.setattr(manager, "get_manager", lambda: stub)

    gen_calls, dispatched, systems = [], [], []
    scripts = []
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "conv-wb-cb"
    k._tool_bridge = None
    k._der_turn_id = "turn-1"
    k._der_turn_active = True
    k._der_stop_requested = False
    k._der_card_hold = {"lock": threading.Lock(), "calls": 0, "released": False,
                        "turn": "turn-1", "queue": None, "plan": None}
    br = SimpleNamespace(_active_conversation_id={"sess": "conv-wb-cb"})

    class _Router:
        last_usage = None

        def generate(self, role, messages, **kw):
            gen_calls.append(role)
            systems.append(json.dumps(messages[0]))
            if len(gen_calls) <= len(scripts):
                return "", "", [_run_call(len(gen_calls), scripts[len(gen_calls) - 1])]
            return "Done.\nSTATUS: done", "", []

        def resolve(self, role):
            return SimpleNamespace(id="same-model")

    class _Box:
        def dispatch(self, decision, **kw):
            dispatched.append(decision.tool)
            if decision.tool == "run_python":
                raw = asyncio.run(tool_bridge._run_python_tool(br, decision.params, "sess", "."))
            else:
                raw = {"success": True, "content": f"{decision.tool} ok"}
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
    item = SimpleNamespace(description="Read the files and count the lines", objective_anchor="",
                           expected_output="", parent_description="", review_feedback="",
                           step_id="s1", check="", node_calls=[], node_call_log=[])
    k.item, k.scripts, k.gen_calls, k.dispatched, k.systems = item, scripts, gen_calls, dispatched, systems
    try:
        yield k
    finally:
        c.close()
        common.drop(workdir)


def test_a_callback_goes_through_the_node_dispatch_and_is_logged_via_run_python(code_node):
    k = code_node
    k.scripts += ["r = tools.read_file(path='a.py')\nr['content']"]
    _text, ok = k._der_run_node(k.item, "sess", "turn-1", [])
    assert ok
    assert k.dispatched == ["run_python", "read_file"]            # read_file reached box.dispatch
    log = k.item.node_call_log
    assert [c["tool"] for c in log] == ["run_python", "read_file"]
    assert log[1]["via"] == "run_python" and log[1]["args"] == {"path": "a.py"}
    assert "via" not in log[0]
    assert k.item.node_calls == [("run_python", True), ("read_file", True)]


def test_a_tool_outside_the_node_menu_is_not_available_and_stops_the_script(code_node):
    k = code_node
    k.scripts += ["tools.nonexistent_tool(x=1)\nafter = 1"]
    k._der_run_node(k.item, "sess", "turn-1", [])
    assert "nonexistent_tool" not in k.dispatched                 # never reached the box
    out = k.item.node_call_log[0]["out"]
    assert "ToolError" in out and "not available" in out and "after" not in k.dispatched


def test_a_script_cannot_nest_run_python(code_node):
    k = code_node
    k.scripts += ["tools.run_python(code='1')"]
    k._der_run_node(k.item, "sess", "turn-1", [])
    assert k.dispatched == ["run_python"] and "not available" in k.item.node_call_log[0]["out"]


def test_a_failed_tool_raises_inside_the_script_and_is_logged_failed(code_node):
    k = code_node
    box = k._get_tool_box()
    k._get_tool_box = lambda: SimpleNamespace(
        dispatch=lambda d, **kw: (box.dispatch(d, **kw) if d.tool == "run_python" else
                                  SimpleNamespace(result={"success": False, "error": "no such file"}, error="")),
        record_shadow_tool_choice=lambda **kw: None, record_tool_call=lambda *a, **kw: None)
    k.scripts += ["tools.read_file(path='gone.py')\nafter = 1"]
    k._der_run_node(k.item, "sess", "turn-1", [])
    log = k.item.node_call_log
    assert log[1]["tool"] == "read_file" and log[1]["ok"] is False and log[1]["via"] == "run_python"
    assert "ToolError" in log[0]["out"] and "no such file" in log[0]["out"]


def test_the_registration_is_cleared_when_the_node_ends(code_node):
    from backend.agent import tool_bridge

    k = code_node
    k.scripts += ["tools.read_file(path='a')"]
    k._der_run_node(k.item, "sess", "turn-1", [])
    assert "conv-wb-cb" not in tool_bridge._wb_dispatch


def test_the_code_prompt_lists_at_most_five_tool_signatures(code_node):
    # STATED CHANGE (Round 4 D6, 2026-11-16): the tools note and its signatures appear only
    # when the brief names a tool Python cannot replace (read_file is replaced by open()),
    # so the item names edit_file and the test pins that tool's line.
    k = code_node
    k.item.tools = ["edit_file"]
    k.scripts += ["1"]
    k._der_run_node(k.item, "sess", "turn-1", [])
    system = k.systems[0]
    assert "tools.edit_file(" in system and "ToolError" in system
    assert system.count("tools.") - system.count("tools.<name>") <= 5 + 1   # 5 signatures


# --- THE TASK CARD: a code node's calls count toward the card ----------------------
def test_code_node_run_python_calls_and_callbacks_count_toward_the_card(code_node):
    """N=2 run_python calls + M=2 callbacks -> the hold's `calls` rises by N+M = 4.
    Before: the code ctx had on_result=None (0 counted) - a turn of code nodes never
    earned its card in personal mode. A callback counts once, through the same counter."""
    k = code_node
    k.scripts += ["tools.read_file(path='a.py')", "tools.read_file(path='b.py')"]
    _text, ok = k._der_run_node(k.item, "sess", "turn-1", [])
    assert ok and k.dispatched == ["run_python", "read_file", "run_python", "read_file"]
    assert k._der_card_hold["calls"] == 4
