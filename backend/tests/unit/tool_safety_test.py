"""Unit tests: tool safety hardening (REQ-10, REQ-11, REQ-12).

Tests error-envelope classification, idempotency no-double-execute, per-tool
retry budget + dedup, and split-scoped identity (graft not penalized).

Spec: specs/der-tool-resolution-blackbox/
"""

from __future__ import annotations

from backend.agent.tool_decision import (
    Decision,
    DecisionKind,
    DispatchResult,
    ToolDecisionBox,
    _classify_error,
    _make_idempotency_key,
    _is_write_tool,
)


# â”€â”€ Error classification (REQ-10) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestErrorClassification:
    def test_transient_timeout(self):
        assert _classify_error("request timed out after 30s") == "transient"

    def test_transient_5xx(self):
        assert _classify_error("500 internal server error") == "transient"

    def test_transient_connection_reset(self):
        assert _classify_error("Connection reset by peer") == "transient"

    def test_rate_limit(self):
        assert _classify_error("429 too many requests") == "rate_limit"

    def test_rate_limit_message(self):
        assert _classify_error("Rate limit exceeded, retry later") == "rate_limit"

    def test_not_found(self):
        assert _classify_error("404 resource not found") == "not_found"

    def test_permission_denied(self):
        assert _classify_error("403 forbidden") == "permission"

    def test_validation_error(self):
        assert _classify_error("400 bad request: missing field") == "validation"

    def test_partial_success(self):
        result = {"succeeded": ["a"], "failed": ["b"]}
        assert _classify_error("some failed", result) == "partial_success"

    def test_permanent_fallback(self):
        assert _classify_error("unknown cryptic error") == "permanent"

    def test_none_error_is_permanent(self):
        assert _classify_error(None) == "permanent"


# â”€â”€ Idempotency (REQ-11) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestIdempotencyKey:
    def test_deterministic_same_inputs(self):
        k1 = _make_idempotency_key("turn1", "search_web", {"q": "hello"})
        k2 = _make_idempotency_key("turn1", "search_web", {"q": "hello"})
        assert k1 == k2  # same inputs â†’ same key

    def test_different_inputs_different_keys(self):
        k1 = _make_idempotency_key("turn1", "search_web", {"q": "hello"})
        k2 = _make_idempotency_key("turn1", "search_web", {"q": "world"})
        assert k1 != k2  # different params â†’ different key

    def test_different_turn_different_key(self):
        k1 = _make_idempotency_key("turn1", "search_web", {"q": "hello"})
        k2 = _make_idempotency_key("turn2", "search_web", {"q": "hello"})
        assert k1 != k2  # different turn â†’ different key

    def test_key_length(self):
        k = _make_idempotency_key("t1", "tool", {"a": 1})
        assert len(k) == 16  # hex digest truncated to 16 chars


class TestIsWriteTool:
    def test_create_is_write(self):
        assert _is_write_tool("create_order") is True

    def test_delete_is_write(self):
        assert _is_write_tool("delete_record") is True

    def test_send_is_write(self):
        assert _is_write_tool("send_email") is True

    def test_get_is_not_write(self):
        assert _is_write_tool("get_order") is False

    def test_search_is_not_write(self):
        assert _is_write_tool("search_web") is False


class TestIdempotencyCacheBehavioral:
    """Tests idempotency through a ToolDecisionBox with a fake tool_bridge."""

    def test_duplicate_dispatch_returns_cached_result(self):
        calls = []

        class _CountTB:
            async def execute_tool(self, name, params, **kw):
                calls.append((name, params))
                return {"success": True, "result": "done", "tool_used": name}

        box = ToolDecisionBox(
            router=_DummyRouter(),
            tool_bridge=_CountTB(),
            get_available_tools=lambda: [{"name": "send_email", "description": "send"}],
            validate_tool_call=lambda n, p: (True, None),
        )

        # First call â€” executes, caches
        dr1 = box.dispatch(
            Decision(kind=DecisionKind.TOOL, tool="send_email", params={"to": "a@b.c"}),
            turn_id="t1",
        )
        assert dr1.success is True
        assert len(calls) == 1

        # Second call with same params â€” cache hit, no execute
        dr2 = box.dispatch(
            Decision(kind=DecisionKind.TOOL, tool="send_email", params={"to": "a@b.c"}),
            turn_id="t1",
        )
        assert dr2.success is True
        assert len(calls) == 1  # still 1 â†’ second was cached

    def test_different_params_different_cache(self):
        calls = []

        class _CountTB:
            async def execute_tool(self, name, params, **kw):
                calls.append((name, params))
                return {"success": True, "result": "ok"}

        box = ToolDecisionBox(
            router=_DummyRouter(),
            tool_bridge=_CountTB(),
            get_available_tools=lambda: [{"name": "send_email", "description": "send"}],
            validate_tool_call=lambda n, p: (True, None),
        )

        box.dispatch(
            Decision(kind=DecisionKind.TOOL, tool="send_email", params={"to": "a@b.c"}),
            turn_id="t1",
        )
        box.dispatch(
            Decision(kind=DecisionKind.TOOL, tool="send_email", params={"to": "x@y.z"}),
            turn_id="t1",
        )
        assert len(calls) == 2  # different params â†’ different cache entries


class _DummyRouter:
    def generate(self, role, messages, **kw):
        return ("reasoning", "", [])
    def health_check_provider(self, role="reasoning"):
        return {"ok": True, "provider": "test", "model": "test"}


# â”€â”€ Per-tool budget + dedup (REQ-12) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestPerToolBudget:
    def test_exceeded_budget_blocks_tool(self):
        fails = [-1]

        class _FailingTB:
            async def execute_tool(self, name, params, **kw):
                fails[0] += 1
                return {"success": False, "error": "transient blip"}

        box = ToolDecisionBox(
            router=_DummyRouter(),
            tool_bridge=_FailingTB(),
            get_available_tools=lambda: [{"name": "search_web", "description": "s"}],
            validate_tool_call=lambda n, p: (True, None),
        )
        dec = Decision(kind=DecisionKind.TOOL, tool="search_web", params={"q": "x"})

        # Fail 3 times â†’ budget exceeded on 4th
        for i in range(3):
            dr = box.dispatch(dec)
            assert dr.success is False, f"call {i+1} should fail"
        dr4 = box.dispatch(dec)
        assert dr4.success is False
        assert "exceeded" in (dr4.error or "").lower()

    def test_success_resets_budget(self):
        count = {"n": 0}

        class _AlternatingTB:
            async def execute_tool(self, name, params, **kw):
                count["n"] += 1
                if count["n"] == 1:
                    return {"success": False, "error": "fail"}
                return {"success": True, "result": "ok"}

        box = ToolDecisionBox(
            router=_DummyRouter(),
            tool_bridge=_AlternatingTB(),
            get_available_tools=lambda: [{"name": "search_web", "description": "s"}],
            validate_tool_call=lambda n, p: (True, None),
        )
        dec = Decision(kind=DecisionKind.TOOL, tool="search_web", params={})

        dr1 = box.dispatch(dec)
        assert dr1.success is False  # fail

        dr2 = box.dispatch(dec)
        assert dr2.success is True  # success â†’ resets counter

        # Third call with different params (not a duplicate, test budget reset)
        dr3 = box.dispatch(
            Decision(kind=DecisionKind.TOOL, tool="search_web", params={"diff": "yes"})
        )
        assert dr3.success is True  # budget was reset by dr2

    def test_duplicate_call_detected(self):
        class _OkTB:
            async def execute_tool(self, name, params, **kw):
                return {"success": True, "result": "ok"}

        box = ToolDecisionBox(
            router=_DummyRouter(),
            tool_bridge=_OkTB(),
            get_available_tools=lambda: [{"name": "search_web", "description": "s"}],
            validate_tool_call=lambda n, p: (True, None),
        )
        dec = Decision(kind=DecisionKind.TOOL, tool="search_web", params={"q": "same"})

        dr1 = box.dispatch(dec, turn_id="t1")
        assert dr1.success is True  # first call works

        dr2 = box.dispatch(dec, turn_id="t1")
        assert dr2.success is True  # second is idempotent retry (allowed once)

        dr3 = box.dispatch(dec, turn_id="t1")
        assert dr3.success is False  # third â†’ duplicate detected
        assert "duplicate" in (dr3.error or "").lower()

    def test_different_after_reset(self):
        """reset_failure_counters clears dedup state so retry is allowed."""
        class _RetryTB:
            async def execute_tool(self, name, params, **kw):
                return {"success": True, "result": "ok"}

        box = ToolDecisionBox(
            router=_DummyRouter(),
            tool_bridge=_RetryTB(),
            get_available_tools=lambda: [{"name": "search_web", "description": "s"}],
            validate_tool_call=lambda n, p: (True, None),
        )
        dec = Decision(kind=DecisionKind.TOOL, tool="search_web", params={"q": "same"})

        dr1 = box.dispatch(dec, turn_id="t1")
        assert dr1.success is True
        dr2 = box.dispatch(dec, turn_id="t1")
        assert dr2.success is True  # idempotent repeat allowed once

        # After reset, same call is allowed again (simulates split)
        box.reset_failure_counters()
        dr3 = box.dispatch(dec, turn_id="t1")
        assert dr3.success is True  # reset clears dedup state
