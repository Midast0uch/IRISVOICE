"""Contract (item-3 guard, 2026-09-24): a tool argument that still holds a
template placeholder must never reach a tool.

Evidence: the repository root carried two junk folders, `${workspaceDir}` and
`{workspaceDir}`, each holding only a `.mcm` store. So a tool received the
literal text `${workspaceDir}` as a path, and the MCM SDK created its database
there. No backend file defines that name, so the placeholder was never expanded
before dispatch.

`AgentToolBridge.execute_tool` is the single choke point ("EVERY tool result
passes through here"), so the refusal lives there. The check is one string scan,
bounded in depth and count, and it never raises.
"""

from __future__ import annotations

import asyncio
import json

from backend.agent.tool_bridge import AgentToolBridge, _unexpanded_placeholder


class TestPlaceholderDetection:
    def test_finds_a_dollar_placeholder(self):
        assert (
            _unexpanded_placeholder({"path": "${workspaceDir}/notes.txt"})
            == "${workspaceDir}"
        )

    def test_finds_one_nested_deep(self):
        assert _unexpanded_placeholder({"a": {"b": ["${X}"]}}) == "${X}"

    def test_finds_one_in_a_key(self):
        assert _unexpanded_placeholder({"${HOME}": "x"}) == "${HOME}"

    def test_clean_params_pass(self):
        for params in (
            {"path": "C:/dev/IRISVOICE/notes.txt"},
            {"query": "compare OLED versus LCD"},
            {"body": '{"kind": "tool"}'},
            {"value": "{not_a_dollar_template}"},
            {},
            {"n": 3},
        ):
            assert _unexpanded_placeholder(params) is None, params

    def test_never_raises_on_odd_input(self):
        class _Weird:
            pass

        for value in (None, 3, object(), _Weird(), {"k": _Weird()}, [1, "a", {"b": 2}]):
            _unexpanded_placeholder(value)


class TestExecuteToolRefuses:
    def _bridge(self, calls):
        b = AgentToolBridge.__new__(AgentToolBridge)

        async def _stub(tool_name, params, session_id="unknown",
                        plan_title="", _skip_resilience=False,
                        decision_meta=None):
            calls.append((tool_name, params))
            return {"success": True}

        b._execute_tool_dispatch = _stub
        return b

    def test_a_placeholder_never_reaches_the_tool(self):
        calls = []
        b = self._bridge(calls)
        res = asyncio.run(
            b.execute_tool("list_directory", {"path": "${workspaceDir}"}, session_id="s")
        )
        assert calls == [], "the tool must not be dispatched with a placeholder"
        assert res.get("success") is False
        assert "${workspaceDir}" in json.dumps(res, default=str)

    def test_clean_params_still_dispatch(self):
        calls = []
        b = self._bridge(calls)
        res = asyncio.run(
            b.execute_tool("list_directory", {"path": "C:/dev/IRISVOICE"}, session_id="s")
        )
        assert calls == [("list_directory", {"path": "C:/dev/IRISVOICE"})]
        assert res.get("success") is True
