"""Unit tests: ToolDecisionBox resolve / dispatch (REQ-3, REQ-4, REQ-7).

Uses pure lambda mocks â€” no external mocking library.
Verifies TOOL/REASON/FAIL on faked router outputs and RC1 validation.

Spec: specs/der-tool-resolution-blackbox/
"""

from __future__ import annotations

from backend.agent.tool_decision import (
    Decision,
    DecisionKind,
    DispatchResult,
    ToolDecisionBox,
)


# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_AVAILABLE = [
    {"name": "search_web", "description": "Search the web"},
    {"name": "get_weather", "description": "Get weather for a city"},
    {"name": "send_email", "description": "Send an email"},
    {"name": "speak", "description": "Speak text aloud"},
]


def _noop_validate(name: str, params: dict) -> tuple[bool, str | None]:
    """Accept all tools except ``bad_tool``."""
    if name == "bad_tool":
        return False, "tool is banned in tests"
    return True, None


def _always_ok_validate(name: str, params: dict) -> tuple[bool, str | None]:
    """Accept every tool unconditionally."""
    return True, None


def _make_box(
    router_gen=None,
    tools=None,
    validate=None,
    infer=None,
    memory=None,
) -> ToolDecisionBox:
    """Build a ToolDecisionBox with sensible defaults and overrides."""
    return ToolDecisionBox(
        router=_FakeRouter(router_gen),
        tool_bridge=None,
        get_available_tools=lambda: tools or _AVAILABLE,
        validate_tool_call=validate or _noop_validate,
        infer_fn=infer or (lambda prompt, **kw: ""),
        memory_lookup_fn=memory or (lambda _g: None),
    )


class _FakeRouter:
    """Minimal router stub that returns a fixed (text, thinking, tool_calls)."""

    def __init__(self, gen_result=None):
        # Default: model says "no tool needed" (REASON)
        self._gen = gen_result or ("reasoning", "", [])

    def generate(self, role, messages, **kw):
        return self._gen

    def health_check_provider(self, role="reasoning"):
        return {"ok": True, "provider": "test", "model": "test"}


# â”€â”€ resolve: TOOL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestResolveTool:
    def test_llm_returns_tool_via_json(self):
        """LLM returns a JSON with kind='tool' and valid tool name â†’ TOOL."""
        text = '{"kind": "tool", "tool": "search_web", "params": {"q": "test"}, "rationale": "need info"}'
        box = _make_box(router_gen=(text, "", []))
        decision = box.resolve(step={"description": "search for X"})
        assert decision.kind == DecisionKind.TOOL
        assert decision.tool == "search_web"
        assert decision.params == {"q": "test"}
        assert decision.source == "llm"

    def test_llm_returns_tool_via_native_call(self):
        """Provider returns a native tool_call dict â†’ TOOL."""
        tool_calls = [{"function": {"name": "get_weather", "arguments": '{"city": "Paris"}'}}]
        box = _make_box(router_gen=("", "", tool_calls))
        decision = box.resolve(step={"description": "weather"})
        assert decision.kind == DecisionKind.TOOL
        assert decision.tool == "get_weather"
        assert decision.params == {"city": "Paris"}

    def test_native_call_with_anthropic_format(self):
        """Anthropic-style tool_use (name+input) â†’ TOOL."""
        tool_calls = [{"name": "search_web", "input": {"q": "hello"}}]
        box = _make_box(router_gen=("", "", tool_calls))
        decision = box.resolve(step={"description": "search"})
        assert decision.kind == DecisionKind.TOOL
        assert decision.tool == "search_web"
        assert decision.params == {"q": "hello"}

    def test_rc1_validation_fails_tool(self):
        """LLM picks a tool that RC1 rejects â†’ FAIL, not TOOL."""
        text = '{"kind": "tool", "tool": "bad_tool", "params": {}, "rationale": ""}'
        box = _make_box(router_gen=(text, "", []), validate=_noop_validate)
        decision = box.resolve(step={"description": "try banned tool"})
        assert decision.kind == DecisionKind.FAIL
        assert "bad_tool" in (decision.error or "")


# â”€â”€ resolve: REASON â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestResolveReason:
    def test_llm_returns_reasoning(self):
        """LLM returns kind='reasoning' with no tool â†’ REASON."""
        text = '{"kind": "reasoning", "tool": null, "rationale": "no tool needed"}'
        box = _make_box(router_gen=(text, "", []))
        decision = box.resolve(step={"description": "think"})
        assert decision.kind == DecisionKind.REASON
        assert decision.source == "llm"

    def test_llm_returns_done(self):
        """LLM returns kind='done' â†’ also REASON."""
        text = '{"kind": "done", "rationale": "task complete"}'
        box = _make_box(router_gen=(text, "", []))
        decision = box.resolve(step={"description": "done"})
        assert decision.kind == DecisionKind.REASON
        assert decision.source == "llm"


# â”€â”€ resolve: FAIL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestResolveFail:
    def test_llm_returns_empty_text(self):
        """infer returns '' (dead model) â†’ consult memory; memory empty â†’ FAIL."""
        box = _make_box(router_gen=("", "", []), memory=lambda _g: None)
        decision = box.resolve(step={"description": "test"})
        assert decision.kind == DecisionKind.FAIL
        assert decision.source == "fail"

    def test_memory_saves_from_fail(self):
        """infer fails but memory suggests a valid tool â†’ TOOL(source=memory)."""
        box = _make_box(
            router_gen=("", "", []),
            memory=lambda _g: {"tool": "search_web", "params": {"q": "saved"}, "rationale": "memory"},
        )
        decision = box.resolve(step={"description": "rescue me"})
        assert decision.kind == DecisionKind.TOOL
        assert decision.tool == "search_web"
        assert decision.source == "memory"

    def test_invalid_memory_suggestion_fails(self):
        """memory suggests a tool that RC1 rejects â†’ FAIL."""
        box = _make_box(
            router_gen=("", "", []),
            memory=lambda _g: {"tool": "bad_tool", "params": {}, "rationale": "bad"},
            validate=_noop_validate,
        )
        decision = box.resolve(step={"description": "bad"})
        assert decision.kind == DecisionKind.FAIL

    def test_llm_returns_invalid_tool_name(self):
        """LLM returns a tool not in registry â†’ FAIL."""
        text = '{"kind": "tool", "tool": "nonexistent_tool", "params": {}}'
        box = _make_box(router_gen=(text, "", []))
        decision = box.resolve(step={"description": "fake"})
        assert decision.kind == DecisionKind.FAIL  # tool not in _AVAILABLE

    def test_unparseable_json(self):
        """LLM returns non-JSON â†’ FAIL."""
        text = "I think we should search the web"
        box = _make_box(router_gen=(text, "", []), memory=lambda _g: None)
        decision = box.resolve(step={"description": "think aloud"})
        assert decision.kind == DecisionKind.FAIL


# â”€â”€ dispatch â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestDispatch:
    def test_dispatch_tool_success(self):
        """TOOL dispatch calls tool_bridge and returns result."""
        box = _make_box(
            router_gen=('{"kind": "tool", "tool": "search_web", "params": {"q": "x"}}', "", []),
            validate=_always_ok_validate,
        )
        # Need a real tool_bridge for dispatch â€” set one
        actual_results = []

        class _FakeTB:
            async def execute_tool(self, name, params, **kw):
                actual_results.append((name, params))
                return {"success": True, "result": "found"}

        box._tool_bridge = _FakeTB()

        decision = box.resolve(step={"description": "search"})
        assert decision.kind == DecisionKind.TOOL
        dr = box.dispatch(decision)
        assert dr.success is True
        assert dr.result == "found"
        assert len(actual_results) == 1
        assert actual_results[0] == ("search_web", {"q": "x"})

    def test_dispatch_reason(self):
        """REASON dispatch calls infer_fn and returns text."""

        class _BoxWithInfer:
            tool_box = None  # noqa

            def infer(self, prompt, **kw):
                return "42 is the answer"

        box = _make_box(
            router_gen=('{"kind": "reasoning", "rationale": "think"}', "", []),
            validate=_always_ok_validate,
            infer=_BoxWithInfer().infer,
        )
        decision = box.resolve(step={"description": "think"})
        assert decision.kind == DecisionKind.REASON
        dr = box.dispatch(decision, reasoning_prompt="What is the answer?")
        assert dr.success is True
        assert dr.result == "42 is the answer"

    def test_dispatch_fail_raises(self):
        """FAIL dispatch raises ValueError (caller must route to recovery)."""
        decision = Decision(kind=DecisionKind.FAIL, source="fail", error="test")
        box = _make_box()
        import pytest

        with pytest.raises(ValueError, match="FAIL"):
            box.dispatch(decision)

    def test_dispatch_tool_failure(self):
        """TOOL dispatch returning success=False propagates as DispatchResult."""
        class _FailingTB:
            async def execute_tool(self, name, params, **kw):
                return {"success": False, "error": "API down"}

        box = _make_box(
            router_gen=('{"kind": "tool", "tool": "get_weather", "params": {"city": "NYC"}}', "", []),
            validate=_always_ok_validate,
        )
        box._tool_bridge = _FailingTB()
        decision = box.resolve(step={"description": "weather"})
        assert decision.kind == DecisionKind.TOOL
        dr = box.dispatch(decision)
        assert dr.success is False

    def test_dispatch_preserves_content_envelope(self):
        """REQ-1: a tool envelope WITHOUT a 'result' key survives dispatch whole.

        The crawler returns {success, content, sources, har_path, trust} â€” no
        'result' field. The old boundary (`result.get("result")`) reduced it to
        None, which starved DER verification and document capture. The full
        envelope must reach both _format_tool_result and _capture_tool_result.
        """
        class _CrawlTB:
            async def execute_tool(self, name, params, **kw):
                return {
                    "success": True,
                    "content": "# Results\n\n" + ("z" * 120),
                    "sources": [{"url": "https://a.com", "title": "A"}],
                    "har_path": "/tmp/x.har",
                    "trust": "untrusted",
                }

        box = _make_box(
            router_gen=('{"kind": "tool", "tool": "search_web", "params": {"query": "q"}}', "", []),
            validate=_always_ok_validate,
        )
        box._tool_bridge = _CrawlTB()
        decision = box.resolve(step={"description": "search the web"})
        assert decision.kind == DecisionKind.TOOL
        dr = box.dispatch(decision)
        assert dr.success is True
        # The FULL envelope is preserved (not just a 'result' key).
        assert isinstance(dr.result, dict)
        assert dr.result.get("content", "").startswith("# Results")
        assert dr.result["sources"][0]["url"] == "https://a.com"
        assert dr.result["har_path"] == "/tmp/x.har"

    def test_dispatch_preserves_error_envelope(self):
        """REQ-1 AC3: an explicit failure envelope keeps error + error_type."""
        class _FailTB:
            async def execute_tool(self, name, params, **kw):
                return {"success": False, "error": "empty_result", "error_type": "empty_result"}

        box = _make_box(
            router_gen=('{"kind": "tool", "tool": "search_web", "params": {"query": "q"}}', "", []),
            validate=_always_ok_validate,
        )
        box._tool_bridge = _FailTB()
        decision = box.resolve(step={"description": "search the web"})
        dr = box.dispatch(decision)
        assert dr.success is False
        assert dr.error == "empty_result"
        assert dr.error_type == "empty_result"
