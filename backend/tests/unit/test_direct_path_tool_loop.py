"""Regression (execution audit B14 + session key, 2026-09-29): the direct chat
path's tool loop.

1. After 3 rounds the old loop returned with the model's next tool calls
   dropped in silence. Now the bound is larger and, when it is hit with calls
   pending, one final tool-less call makes the model answer.
2. Tools ran under session_id=conversation_id, so the project workdir, the
   session shell and permission routing (all keyed by the WebSocket session)
   were never found. They now run under the turn's session.
Both tests fail on the old code.
"""

import json
from unittest.mock import patch

from backend.agent.agent_kernel import AgentKernel


class _AlwaysToolRouter:
    """Asks for a tool on every call that offers tools; answers otherwise."""

    def __init__(self):
        self.calls = []
        self.last_usage = None

    def generate(self, role, messages, tools=None, **kw):
        self.calls.append(tools)
        if tools:
            call = {"id": f"t{len(self.calls)}", "function": {
                "name": "read_file", "arguments": json.dumps({"path": "a.py"})}}
            return "", "", [call]
        return "final answer from what I have", "", []


class _RecordingBridge:
    def __init__(self):
        self.sessions = []

    async def execute_tool(self, tool_name, params, session_id=None, **kw):
        self.sessions.append(session_id)
        return {"success": True, "content": "x = 1"}


def _kernel():
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "conv-9"
    k.session_id = "stale-session"
    k._turn_session_id = "ws-session-42"
    k._config_mode = "auto"
    k._router = _AlwaysToolRouter()
    k._tool_bridge = _RecordingBridge()
    return k


def _run(k):
    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]
    with patch.object(AgentKernel, "_assemble_direct_context", return_value=[{"role": "user", "content": "go"}]), \
         patch.object(AgentKernel, "_sanitize_messages", side_effect=lambda m: m), \
         patch.object(AgentKernel, "_get_openai_tools", return_value=tools), \
         patch.object(AgentKernel, "_accrue_tokens", return_value=None), \
         patch.object(AgentKernel, "_get_tool_box", side_effect=RuntimeError("no box")):
        return k._respond_direct("go", [])


def test_bound_reached_ends_with_a_tool_less_answer():
    k = _kernel()
    reply = _run(k)
    assert reply == "final answer from what I have"
    assert len(k._tool_bridge.sessions) > 3  # more than the old 3 rounds ran
    assert k._router.calls[-1] is None  # the last call offered no tools


def test_tools_run_under_the_turn_session():
    k = _kernel()
    _run(k)
    assert set(k._tool_bridge.sessions) == {"ws-session-42"}
