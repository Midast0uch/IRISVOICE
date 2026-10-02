"""Contract: a repeated call AFTER a file change is new work, not a loop.

Derived from the live trace of eval task c04 (implement_from_tests,
2026-10-02, conv-622): run_command(pytest) -> edit_file -> run_command(pytest)
-> write_file -> run_command(pytest). The dispatcher keyed its repeat guard on
(tool, args) only, so the third test run came back "Duplicate call ... loop
detected" although the files had changed; 22 test runs and 36 writes were
blocked that way and the task failed 6/13.

The other half of the contract: an identical call with NO change in between is
still a repeat (cached on the second write, blocked on the third).
"""
from backend.agent.tool_decision import Decision, DecisionKind, ToolDecisionBox


class _Router:
    def generate(self, role, messages, **kw):
        return ("", "", [])


def _box():
    executed = []

    class _TB:
        async def execute_tool(self, name, params, **kw):
            executed.append(name)
            return {"success": True, "result": f"{name} ok"}

    box = ToolDecisionBox(
        router=_Router(),
        tool_bridge=_TB(),
        get_available_tools=lambda: [],
        validate_tool_call=lambda n, p: (True, None),
    )
    return box, executed


def _call(box, tool, params):
    return box.dispatch(
        Decision(kind=DecisionKind.TOOL, tool=tool, params=params), turn_id="t1"
    )


def test_test_run_after_each_change_executes():
    box, executed = _box()
    tests = {"command": "python -m pytest -q"}
    seq = [
        ("run_command", tests),
        ("edit_file", {"path": "a.py", "old": "x", "new": "y"}),
        ("run_command", tests),
        ("write_file", {"path": "a.py", "content": "z"}),
        ("run_command", tests),
        ("edit_file", {"path": "a.py", "old": "z", "new": "w"}),
        ("run_command", tests),
    ]
    for tool, params in seq:
        dr = _call(box, tool, params)
        assert dr.success, f"{tool} blocked after a file change: {dr.error}"
    assert executed.count("run_command") == 4


def test_same_write_after_other_change_executes():
    box, executed = _box()
    write = {"path": "a.py", "content": "v1"}
    _call(box, "write_file", write)
    _call(box, "edit_file", {"path": "a.py", "old": "v1", "new": "v2"})
    dr = _call(box, "write_file", write)
    assert dr.success
    assert executed.count("write_file") == 2, "second write served from cache, file left at v2"


def test_identical_calls_with_no_change_are_still_a_repeat():
    box, executed = _box()
    write = {"path": "a.py", "content": "v1"}
    assert _call(box, "write_file", write).success
    assert _call(box, "write_file", write).success  # cached retry
    assert executed.count("write_file") == 1
    third = _call(box, "write_file", write)
    assert not third.success and "loop detected" in (third.error or "")

    tests = {"command": "python -m pytest -q"}
    _call(box, "run_command", tests)
    _call(box, "run_command", tests)
    third = _call(box, "run_command", tests)
    assert not third.success and "loop detected" in (third.error or "")
