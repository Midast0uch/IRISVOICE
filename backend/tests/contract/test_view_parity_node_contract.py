"""CT-1 for the DER node path and synthesis (specs/clm-memory T1.3): view parity.

Sibling of ``test_view_parity_contract.py`` (the direct path). While no edit has
happened, the list the model receives through the view is the list the old
code sent - same order, same dict shapes, same bytes - at EVERY model call.

The node loop (``node_executor.run_node``) keeps its own ``messages`` list and
sends ``view.render()``; on a view failure it sends ``messages`` itself. That
fallback IS the old code's input, so it is the oracle here: each scenario runs
twice, once through the view and once with the view forced to fail, and the
captured inputs must be equal at every call. A reordered or lossy render fails
these tests (the fallback path does not use render).
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List

import pytest

from backend.agent import context_view as cv
from backend.agent import node_executor as ne
from backend.agent.context_view import (
    ASSISTANT_TOOL_CALLS,
    HARNESS_NOTE,
    SCREENSHOT,
    STEP_GOAL,
    SYNTHESIS_REQUEST,
    SYSTEM,
    TOOL_RESULT,
    ContextView,
)


def _tool(name: str) -> Dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": name,
                                             "parameters": {"type": "object", "properties": {}}}}


def _call(i: int, name: str, **args: Any) -> Dict[str, Any]:
    return {"id": f"c{i}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


_TOOLS = [_tool(n) for n in ("read_file", "edit_file", "run_command", "search", "browser_observe")]


def _shot(name: str, params: dict) -> dict:
    return {"success": True, "marked_screenshot": {"b64": "QUJD" + str(params)}, "marks": []}


SCENARIOS = {
    "multi_call": dict(
        goal="Fix calc.py",
        script=[("", [_call(1, "read_file", path="calc.py")]),
                ("", [_call(2, "edit_file", path="calc.py", old="a", new="b")]),
                ("", [_call(3, "run_command", command="pytest")]),
                ("Fixed.\nSTATUS: done", [])]),
    "long_result_clip": dict(
        goal="Search", script=[("", [_call(1, "search", query="q")]), ("ok\nSTATUS: done", [])],
        fmt=lambda n, r: "R" * 20_000),
    "screenshot_replacement": dict(
        goal="Look at the page",
        script=[("", [_call(1, "browser_observe", url="a")]),
                ("", [_call(2, "browser_observe", url="b")]),
                ("", [_call(3, "browser_observe", url="c")]),
                ("Seen.\nSTATUS: done", [])],
        exec_fn=_shot, sees=lambda role: True),
    "call_limit_close": dict(
        goal="Explore",
        script=[("", [_call(1, "read_file", path="a.py")]),
                ("", [_call(2, "read_file", path="b.py")]),
                ("Read two.\nSTATUS: done", [])],
        max_calls=2),
    "prior_results_and_memory": dict(
        goal="Use the port", script=[("Set.\nSTATUS: done", [])],
        prior_results=[{"step": 1, "description": "read cfg", "result": "port=1"}],
        memory_facts="- [the user stated] the port is 8080"),
}


def _run(spec: Dict[str, Any], *, break_view: bool, monkeypatch) -> List[List[Dict[str, Any]]]:
    spec = dict(spec)
    goal, script = spec.pop("goal"), list(spec.pop("script"))
    exec_fn, fmt = spec.pop("exec_fn", None), spec.pop("fmt", None)
    seen: List[List[Dict[str, Any]]] = []

    def generate(role, messages, tools=None, **kw):
        seen.append(copy.deepcopy(messages))
        text, calls = script.pop(0)
        return text, "", copy.deepcopy(calls)

    if break_view:
        def _boom(self, *a, **k):
            raise RuntimeError("forced view failure")
        monkeypatch.setattr(ContextView, "admit_live", _boom)
    ctx = ne.NodeContext(
        generate=generate,
        execute=exec_fn or (lambda name, params: {"success": True, "out": name}),
        format_result=fmt or (lambda name, raw: json.dumps(raw, sort_keys=True)),
        tools=_TOOLS, task="Fix the bug and run the tests", workdir="", conv_id="ct1-node",
        **spec,
    )
    ne.run_node(goal, ctx)
    monkeypatch.undo()
    return seen


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_node_input_through_the_view_equals_the_old_list_at_every_call(name, monkeypatch):
    through_view = _run(SCENARIOS[name], break_view=False, monkeypatch=monkeypatch)
    old_list = _run(SCENARIOS[name], break_view=True, monkeypatch=monkeypatch)
    assert len(through_view) == len(old_list) >= 1
    assert through_view == old_list
    assert [json.dumps(m, sort_keys=True) for m in through_view] == [
        json.dumps(m, sort_keys=True) for m in old_list]


def test_the_view_sees_the_in_place_screenshot_replacement():
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "STEP: look"},
        {"role": "user", "content": [{"type": "text", "text": "shot"},
                                     {"type": "image_url", "image_url": {"url": "data:x"}}]},
    ]
    view = ContextView()
    for kind, m in zip((SYSTEM, STEP_GOAL, SCREENSHOT), messages):
        view.admit_live(kind, m)
    ne._drop_old_screenshots(messages)  # the loop edits its own dicts in place
    assert view.render() == messages
    assert view.render()[2]["content"] == ne._OLD_SCREENSHOT


def test_admit_live_renders_fresh_dicts_and_keeps_kinds():
    tool_calls = [_call(1, "read_file", path="a")]
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "STEP: read"},
        {"role": "assistant", "content": None, "tool_calls": tool_calls},
        {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": "body"},
        {"role": "user", "content": "Stop here."},
    ]
    kinds = (SYSTEM, STEP_GOAL, ASSISTANT_TOOL_CALLS, TOOL_RESULT, HARNESS_NOTE)
    view = ContextView()
    for kind, m in zip(kinds, messages):
        view.admit_live(kind, m)
    out = view.render()
    assert out == messages
    assert all(a is not b for a, b in zip(out, messages))  # a caller edit cannot reach the loop
    assert out[2]["tool_calls"] is tool_calls  # nested values shared, as in the old list
    assert tuple(b.kind for b in view.blocks) == kinds


def test_synthesis_input_through_the_view_equals_the_old_one_message_list():
    from backend.agent.kernel.der.report import _synthesis_messages

    prompt = "User request: compare — café\n\nTool execution results:\nStep 1: ok"
    assert _synthesis_messages(prompt, "ct1-syn") == [{"role": "user", "content": prompt}]
    view = ContextView()
    view.admit(SYNTHESIS_REQUEST, [{"role": "user", "content": prompt}])
    assert json.dumps(view.render(), sort_keys=True) == json.dumps(
        [{"role": "user", "content": prompt}], sort_keys=True)


def test_a_failing_synthesis_view_falls_back_and_counts(monkeypatch):
    from backend.agent.kernel.der.report import _synthesis_messages

    def _boom(self, *a, **k):
        raise RuntimeError("forced view failure")
    monkeypatch.setattr(ContextView, "admit", _boom)
    before = cv.view_fallback_count()
    assert _synthesis_messages("p", "ct1-syn") == [{"role": "user", "content": "p"}]
    assert cv.view_fallback_count() == before + 1
