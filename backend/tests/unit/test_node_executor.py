"""Execution audit Phase 2: a DER node is a bounded Brain work loop.

The eval turn that motivated it (2026-09-29): the small tool model resolved
"Fix the off-by-one error in mathutils.py" to read_file six times. Here the
Brain calls tools itself and sees each result; the node ends when it answers
without a tool call; a failing last command makes the node fail.
"""

import json

from backend.agent.node_executor import NodeContext, run_node

TOOLS = [{"type": "function", "function": {"name": n, "parameters": {}}}
         for n in ("read_file", "edit_file", "run_command")]


def _call(name, args, i=0):
    return {"id": f"c{i}", "type": "function",
            "function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}}


def _ctx(script, results, **kw):
    """script: list of (text, tool_calls) replies; results: tool -> raw result."""
    seen = []
    replies = list(script)

    def gen(role, messages, **k):
        seen.append([dict(m) for m in messages])
        text, calls = replies.pop(0)
        return text, "", calls

    executed = []

    def execute(name, params):
        executed.append((name, params))
        r = results[name]
        if isinstance(r, Exception):
            raise r
        return r

    ctx = NodeContext(generate=gen, execute=execute, format_result=lambda n, r: json.dumps(r),
                      tools=TOOLS, workdir="C:/proj", **kw)
    return ctx, seen, executed


def test_read_edit_test_then_answer_is_a_successful_node():
    script = [
        ("", [_call("read_file", {"path": "m.py"})]),
        ("", [_call("edit_file", {"path": "m.py", "old": "end)", "new": "end + 1)"})]),
        ("", [_call("run_command", {"command": "pytest -q"})]),
        ("Fixed the range and the tests pass.", []),
    ]
    ctx, seen, executed = _ctx(script, {
        "read_file": {"success": True, "content": "range(start, end)"},
        "edit_file": {"success": True},
        "run_command": {"success": True, "returncode": 0, "stdout": "3 passed"},
    })
    r = run_node("Fix the off-by-one error in mathutils.py", ctx)
    assert r.success and r.summary == "Fixed the range and the tests pass."
    assert [c["tool"] for c in r.calls] == ["read_file", "edit_file", "run_command"]
    assert executed[1] == ("edit_file", {"path": "m.py", "old": "end)", "new": "end + 1)"})
    # the Brain saw the read result word for word before it edited
    assert any(m.get("role") == "tool" and "range(start, end)" in m["content"] for m in seen[1])


def test_observing_failing_tests_is_a_done_step_that_still_reports_the_failure():
    # coding eval c11/c14: "run the failing tests to see the errors" is met
    # once the failures are seen; the failure must still be visible downstream.
    script = [("", [_call("run_command", {"command": "pytest -q"})]),
              ("Saw 1 failure in test_area.\nSTATUS: done", [])]
    ctx, _, _ = _ctx(script, {"run_command": {"success": True, "returncode": 1, "stdout": "1 failed"}})
    r = run_node("run the failing tests to see the errors", ctx)
    assert r.success is True and r.last_command_failed is True
    assert r.summary == "Saw 1 failure in test_area."
    assert "exited non-zero" in r.as_step_result()


def test_status_failed_fails_the_node_with_its_reason():
    script = [("", [_call("run_command", {"command": "pytest -q"})]),
              ("I could not fix it.\nSTATUS: failed: 2 tests still fail", [])]
    ctx, _, _ = _ctx(script, {"run_command": {"success": True, "returncode": 1, "stdout": "2 failed"}})
    r = run_node("make the tests pass", ctx)
    assert r.success is False and r.error == "2 tests still fail"
    assert r.summary == "I could not fix it."


def test_bad_arguments_unknown_tools_and_exceptions_become_tool_results():
    script = [
        ("", [_call("edit_file", "{not json", 0), _call("delete_everything", {}, 1),
              _call("read_file", {"path": "x"}, 2)]),
        ("Could not read x.", []),
    ]
    ctx, seen, executed = _ctx(script, {"read_file": OSError("disk gone")})
    r = run_node("read x", ctx)
    tool_msgs = [m["content"] for m in seen[1] if m.get("role") == "tool"]
    assert "not valid JSON" in tool_msgs[0]
    assert "unknown tool" in tool_msgs[1]
    assert "OSError: disk gone" in tool_msgs[2]
    assert executed == [("read_file", {"path": "x"})]
    assert r.success is True and [c["ok"] for c in r.calls] == [False, False, False]


def test_spent_budget_asks_for_status_and_fails_the_node():
    script = [("Read m.py; the edit is still to do.", [])]
    ctx, seen, _ = _ctx(script, {}, budget_s=0)
    r = run_node("fix it", ctx)
    assert r.success is False and "budget" in r.error
    assert r.summary.startswith("Read m.py")


def test_every_valid_call_reaches_the_shadow_hook_and_a_broken_hook_is_harmless():
    script = [("", [_call("read_file", {"path": "m.py"}), _call("nope", {}, 1)]), ("ok", [])]
    ctx, _, executed = _ctx(script, {"read_file": {"success": True, "content": "x"}})
    seen_calls = []

    def hook(name, params):
        seen_calls.append((name, params))
        raise RuntimeError("ledger down")

    ctx.on_call = hook
    r = run_node("read m.py", ctx)
    assert seen_calls == [("read_file", {"path": "m.py"})]
    assert executed == [("read_file", {"path": "m.py"})] and r.success


def test_a_broken_brain_is_a_failed_node_not_a_crash():
    def boom(*a, **k):
        raise RuntimeError("Ollama returned 500")

    ctx = NodeContext(generate=boom, execute=lambda n, p: {}, format_result=lambda n, r: "",
                      tools=TOOLS)
    r = run_node("fix it", ctx)
    assert r.success is False and "Ollama returned 500" in r.error
