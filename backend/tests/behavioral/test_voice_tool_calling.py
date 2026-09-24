"""
Tests for voice-path ReAct tool calling (Issue E follow-up).

Root cause verified in backend logs: the voice direct-response path
(`_respond_direct`) never passed tools to the LLM and ran no tool-call loop,
so the agent could not web-search via voice even with the web toggle ON.

These tests verify the fix without loading a model:
  - When web tools are available, the agent executes tool calls (e.g. search)
    and feeds results back for a final answer.
  - The tool-call loop is bounded (no runaway).
  - When the model answers directly, no tools are executed.
  - When the internet flag is OFF, search/crawler_query are NOT offered to the LLM.

Run: python -m pytest backend/tests/test_voice_tool_calling.py -v
"""
from unittest.mock import MagicMock

from backend.agent.agent_kernel import (
    AgentKernel,
    set_global_internet_access,
    get_global_internet_access,
)


class _FakeRouter:
    """Role-router stand-in (2026-09-22 audit note): `_respond_direct` has
    generated through `self._router.generate(role, ...)` since the
    2026-09-03 model-selection-authority commit; this fixture's old
    `_dispatch_api` seam is never consulted anymore. This adapter forwards the
    router call onto the same fake dispatch functions — the test ASSERTIONS
    (tool loop, bounding, tool gating) are unchanged."""

    def __init__(self, dispatch):
        self._dispatch = dispatch
        self.last_usage = None

    def generate(self, role, messages, tools=None, max_tokens=None,
                 temperature=None, chunk_callback=None, reasoning_callback=None,
                 **_kw):
        return self._dispatch(
            messages, max_tokens, temperature,
            chunk_callback=chunk_callback,
            reasoning_callback=reasoning_callback, tools=tools,
        )


class _FakeToolBridge:
    def __init__(self):
        self.calls = []

    async def execute_tool(self, tool_name, params, session_id="unknown"):
        self.calls.append((tool_name, params, session_id))
        if tool_name == "search":
            return {
                "success": True,
                "content": "RESULT_MARKER: the latest news is X",
                "summary": "news",
            }
        return {"success": True, "content": "ok"}


def _make_kernel():
    kernel = AgentKernel.__new__(AgentKernel)
    kernel._config_mode = "SINGLE_API"
    # 2026-09-22 audit note: `_selected_reasoning_model` is a READ-ONLY
    # property since the 2026-09-03 model-selection-authority commit; it
    # resolves through `_model_for_role("reasoning")`. Stubbing the resolver
    # is the test seam now — assigning the property raises AttributeError.
    kernel._model_for_role = lambda role: "test-model"
    # `_model_provider` is read-only too (same commit). The old fixture value
    # "test" was already an unknown provider for every consumer of it — with
    # no `_router` the property now reports "uninitialized", which is the
    # identical code path (unknown -> default). Nothing to assign.
    # `_router` is assigned per-test via _FakeRouter below — the router is
    # the generation seam since 2026-09-03 (role-based `router.generate`).
    kernel._router = None
    kernel.session_id = "test-session"
    kernel.conversation_id = "test-conv"
    kernel._pending_thinking = ""
    kernel._tool_bridge = _FakeToolBridge()
    kernel._is_openai_compat = lambda: False
    kernel._is_api_provider = lambda: False
    kernel._assemble_direct_context = lambda text, context: [
        {"role": "user", "content": text}
    ]
    kernel._sanitize_messages = lambda msgs: msgs
    def _tools(_=None):
        if not get_global_internet_access():
            return []
        return [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Web search",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        ]

    kernel._get_openai_tools = _tools
    return kernel


def test_voice_tool_calling_executes_search_when_tools_present():
    set_global_internet_access(True)
    kernel = _make_kernel()
    state = {"n": 0, "tools_first": None}

    def fake_dispatch(
        messages, max_tokens, temperature, reasoning_effort="balanced",
        chunk_callback=None, reasoning_callback=None, tools=None,
    ):
        state["n"] += 1
        if state["n"] == 1:
            state["tools_first"] = tools
            return (
                "Let me search.",
                "",
                [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "search", "arguments": '{"query": "latest news"}'},
                }],
            )
        return ("Here is the answer using RESULT_MARKER.", "", [])

    kernel._router = _FakeRouter(fake_dispatch)

    result = kernel._respond_direct("what is the latest news?", [])

    assert "RESULT_MARKER" in result, "final answer should incorporate tool result"
    assert kernel._tool_bridge.calls, "execute_tool should have been called"
    assert kernel._tool_bridge.calls[0][0] == "search"
    assert state["tools_first"] is not None
    assert any(t["function"]["name"] == "search" for t in state["tools_first"])
    assert state["n"] == 2


def test_voice_tool_loop_bounded_at_max_rounds():
    set_global_internet_access(True)
    kernel = _make_kernel()
    state = {"n": 0}

    def fake_dispatch_always_tool(
        messages, max_tokens, temperature, reasoning_effort="balanced",
        chunk_callback=None, reasoning_callback=None, tools=None,
    ):
        state["n"] += 1
        # Always requests a tool → must terminate at MAX_TOOL_ROUNDS (3)
        return (
            "",
            "",
            [{
                "id": f"call_{state['n']}",
                "type": "function",
                "function": {"name": "search", "arguments": '{"query": "x"}'},
            }],
        )

    kernel._router = _FakeRouter(fake_dispatch_always_tool)
    result = kernel._respond_direct("loop me", [])

    # Bounded: initial call + up to 3 tool rounds = 4 dispatch calls max
    assert state["n"] <= 4, f"tool loop not bounded: {state['n']} calls"
    assert len(kernel._tool_bridge.calls) <= 3


def test_voice_no_tool_calls_when_model_answers_directly():
    set_global_internet_access(True)
    kernel = _make_kernel()
    state = {"n": 0}

    def fake_dispatch_direct(
        messages, max_tokens, temperature, reasoning_effort="balanced",
        chunk_callback=None, reasoning_callback=None, tools=None,
    ):
        state["n"] += 1
        return ("A direct answer with no tools.", "", [])

    kernel._router = _FakeRouter(fake_dispatch_direct)
    result = kernel._respond_direct("hello", [])

    assert result == "A direct answer with no tools."
    assert state["n"] == 1
    assert kernel._tool_bridge.calls == []


def test_voice_web_tools_excluded_when_internet_off():
    set_global_internet_access(False)
    kernel = _make_kernel()
    state = {"tools": None}

    def fake_dispatch(
        messages, max_tokens, temperature, reasoning_effort="balanced",
        chunk_callback=None, reasoning_callback=None, tools=None,
    ):
        state["tools"] = tools
        return ("No web for me.", "", [])

    kernel._router = _FakeRouter(fake_dispatch)
    kernel._respond_direct("anything", [])

    assert state["tools"] is not None
    assert not any(
        t["function"]["name"] in ("search", "crawler_query") for t in state["tools"]
    ), "web tools must be excluded when internet access is OFF"
    set_global_internet_access(True)
