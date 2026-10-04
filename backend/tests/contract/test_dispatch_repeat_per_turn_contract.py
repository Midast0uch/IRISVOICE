"""Contract: the dispatcher's loop guard lives inside ONE turn (live 2026-10-04).

Before: the repeat memory belonged to the conversation's decision box, so the
next user request that opened the same page got "Duplicate call to
'browser_open' with identical args (2x) - loop detected" (4 of 6 consecutive
live turns). Browser tools also act on a page that changes between identical
calls; run_node's own detector (repeated call / unchanged result) stops a real
browser loop.

Kept: a third identical call to an ordinary tool inside one turn is still a loop.
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

    box = ToolDecisionBox(router=_Router(), tool_bridge=_TB(), get_available_tools=lambda: [],
                          validate_tool_call=lambda n, p: (True, None))
    return box, executed


def _call(box, tool, params, turn):
    return box.dispatch(Decision(kind=DecisionKind.TOOL, tool=tool, params=params), turn_id=turn)


def test_a_new_turn_is_not_a_loop_of_the_last_one():
    box, executed = _box()
    p = {"app": "notes"}
    for turn in ("t1", "t2", "t3"):
        assert _call(box, "launch_app", p, turn).success
        assert _call(box, "launch_app", p, turn).success  # one silent repeat allowed
    assert executed.count("launch_app") >= 3  # each turn's first call ran


def test_a_third_identical_call_in_one_turn_is_still_a_loop():
    box, _ = _box()
    p = {"app": "notes"}
    _call(box, "launch_app", p, "t1")
    _call(box, "launch_app", p, "t1")
    dr = _call(box, "launch_app", p, "t1")
    assert not dr.success and "loop detected" in (dr.error or "")


def test_browser_open_of_the_same_page_is_never_a_dispatcher_loop():
    box, executed = _box()
    p = {"url": "https://en.wikipedia.org"}
    for _ in range(4):
        assert _call(box, "browser_open", p, "t1").success
    assert executed.count("browser_open") == 4
