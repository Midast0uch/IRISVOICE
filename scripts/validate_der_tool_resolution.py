#!/usr/bin/env python3
"""validate_der_tool_resolution.py — standing CDD harness (REQ-1..13).

Replays recorded trajectories through the ToolDecisionBox and asserts
contract + behavioral properties.  Designed to grow: add new trajectories
to ``TRAJECTORIES`` and the harness exercises them on every run.

Usage:
    python scripts/validate_der_tool_resolution.py

Returns exit code 0 on all-pass, 1 on failure.
"""

from __future__ import annotations

import sys
import time as _time
from typing import Any, Dict, Optional

# Ensure backend is importable
sys.path.insert(0, ".")  # noqa: PTH109

from backend.agent.tool_decision import (
    Decision,
    DecisionKind,
    DispatchResult,
    ToolDecisionBox,
    _classify_error,
    _make_idempotency_key,
)


# ── Helpers ────────────────────────────────────────────────────────────────


class _HealthyRouter:
    """Router that returns a fixed (text, thinking, tool_calls)."""

    def __init__(self, gen_result=None):
        self._gen = gen_result or ('{"kind": "reasoning", "rationale": "ok"}', "", [])

    def generate(self, role, messages, **kw):
        return self._gen

    def health_check_provider(self, role="reasoning"):
        return {"ok": True, "provider": "test", "model": "test"}


class _DeadRouter:
    def generate(self, role, messages, **kw):
        raise RuntimeError("model unavailable")

    def health_check_provider(self, role="reasoning"):
        return {"ok": True, "provider": "test", "model": "test"}


class _HealthyTB:
    def execute_tool(self, name, params, **kw):
        return {"success": True, "result": f"{name} executed"}


class _FailingTB:
    def execute_tool(self, name, params, **kw):
        return {"success": False, "error": "500 internal error"}


def _make_box(router=None, bridge=None, validate=None, memory=None) -> ToolDecisionBox:
    return ToolDecisionBox(
        router=router or _HealthyRouter(),
        tool_bridge=bridge or _HealthyTB(),
        get_available_tools=lambda: [
            {"name": "search_web", "description": "Search the web"},
            {"name": "send_email", "description": "Send email"},
            {"name": "get_weather", "description": "Get weather"},
        ],
        validate_tool_call=validate or (lambda n, p: (True, None)),
        infer_fn=lambda prompt, **kw: "direct reasoning result",
        memory_lookup_fn=memory or (lambda _g: None),
    )


# ── Trajectories ───────────────────────────────────────────────────────────


_PARAMS: Dict[str, Any] = {}


def _trajectory_dead_model():
    """TC-1: dead model → FAIL (no silent reason, REQ-4)."""
    box = _make_box(router=_DeadRouter())
    decision = box.resolve(step={"description": "search for X"})
    assert decision.kind == DecisionKind.FAIL, (
        f"TC-1 expected FAIL, got {decision.kind}"
    )
    assert decision.source == "fail"
    assert decision.error is not None
    return "TC-1 dead model → FAIL ✅"


def _trajectory_web_search():
    """TC-2: valid model + web goal → TOOL (search_web)."""
    result_text = '{"kind": "tool", "tool": "search_web", "params": {"q": "test"}, "rationale": "search"}'
    box = _make_box(router=_HealthyRouter(gen_result=(result_text, "", [])))
    decision = box.resolve(step={"description": "search web for X"})
    assert decision.kind == DecisionKind.TOOL, (
        f"TC-2 expected TOOL, got {decision.kind}"
    )
    assert decision.tool == "search_web"
    assert decision.source == "llm"
    dr = box.dispatch(decision)
    assert dr.success is True
    return "TC-2 web search → TOOL + dispatch ok ✅"


def _trajectory_invalid_tool():
    """TC-3: model returns tool not in registry → FAIL (REQ-4 AC3)."""
    result_text = '{"kind": "tool", "tool": "nonexistent", "params": {}, "rationale": "fake"}'
    box = _make_box(router=_HealthyRouter(gen_result=(result_text, "", [])))
    decision = box.resolve(step={"description": "fake tool"})
    assert decision.kind == DecisionKind.FAIL, (
        f"TC-3 expected FAIL, got {decision.kind}"
    )
    assert "nonexistent" in (decision.error or "")
    return "TC-3 invalid tool → FAIL ✅"


def _trajectory_memory_rescue():
    """TC-4: dead model + memory suggestion → TOOL(source=memory) (REQ-4)."""
    box = _make_box(
        router=_DeadRouter(),
        memory=lambda _g: {
            "tool": "search_web", "params": {"q": "salvage"},
            "rationale": "memory pre-filter",
        },
    )
    decision = box.resolve(step={"description": "search"})
    assert decision.kind == DecisionKind.TOOL, (
        f"TC-4 expected TOOL, got {decision.kind}"
    )
    assert decision.source == "memory"
    return "TC-4 memory rescue → TOOL(source=memory) ✅"


def _trajectory_reason_step():
    """TC-5: model says reason → REASON (no tool)."""
    result_text = '{"kind": "reasoning", "rationale": "think about it"}'
    router = _HealthyRouter(gen_result=(result_text, "", []))
    box = _make_box(router=router)
    decision = box.resolve(step={"description": "think"})
    assert decision.kind == DecisionKind.REASON, (
        f"TC-5 expected REASON, got {decision.kind}"
    )
    # dispatch is optional for REASON (DER loop does _run_step_direct)
    return "TC-5 reason step → REASON ✅"


def _trajectory_idempotency():
    """TC-6: idempotency prevents double-execute on write tool."""
    call_count = [0]
    box = ToolDecisionBox(
        router=_HealthyRouter(gen_result=('{"kind": "reasoning"}', "", [])),
        tool_bridge=_CountingTB(call_count),
        get_available_tools=lambda: [{"name": "send_email", "description": "send"}],
        validate_tool_call=lambda n, p: (True, None),
    )
    dec = Decision(kind=DecisionKind.TOOL, tool="send_email", params={"to": "a@b"})
    dr1 = box.dispatch(dec, turn_id="t1")
    assert dr1.success is True, f"TC-6 first call failed: {dr1.error}"
    dr2 = box.dispatch(dec, turn_id="t1")
    assert dr2.success is True, f"TC-6 second call failed: {dr2.error}"
    assert call_count[0] == 1, f"TC-6 expected 1 execute, got {call_count[0]}"
    return "TC-6 idempotency prevents double-execute ✅"


class _CountingTB:
    def __init__(self, counter: list):
        self._counter = counter
    def execute_tool(self, name, params, **kw):
        self._counter[0] += 1
        return {"success": True, "result": "ok"}


def _trajectory_budget_block():
    """TC-7: per-tool budget blocks after N consecutive failures."""
    fails = [-1]
    box = ToolDecisionBox(
        router=_HealthyRouter(gen_result=('{"kind": "reasoning"}', "", [])),
        tool_bridge=_FailingTB(),
        get_available_tools=lambda: [{"name": "send_email", "description": "s"}],
        validate_tool_call=lambda n, p: (True, None),
    )
    dec = Decision(kind=DecisionKind.TOOL, tool="send_email", params={})
    for _ in range(3):
        dr = box.dispatch(dec)
        assert dr.success is False, "budget: fail expected"
    dr4 = box.dispatch(dec)
    assert "exceeded" in (dr4.error or "").lower()
    return "TC-7 per-tool budget blocks ✅"


def _trajectory_duplicate_detection():
    """TC-8: third consecutive identical call after two successes is a loop."""
    box = ToolDecisionBox(
        router=_HealthyRouter(gen_result=('{"kind": "reasoning"}', "", [])),
        tool_bridge=_HealthyTB(),
        get_available_tools=lambda: [{"name": "send_email", "description": "s"}],
        validate_tool_call=lambda n, p: (True, None),
    )
    dec = Decision(kind=DecisionKind.TOOL, tool="send_email", params={"to": "x"})
    # Call 1: first execution, succeeds
    dr1 = box.dispatch(dec, turn_id="t1")
    assert dr1.success is True
    # Call 2: same args, allowed (idempotent retry)
    dr2 = box.dispatch(dec, turn_id="t1")
    assert dr2.success is True, "second call is idempotent retry"
    # Call 3: same args AGAIN → loop detected
    dr3 = box.dispatch(dec, turn_id="t1")
    assert dr3.success is False, "third call should be blocked as duplicate"
    assert "duplicate" in (dr3.error or "").lower()
    return "TC-8 duplicate call (3rd identical) detected ✅"


# ── Run ────────────────────────────────────────────────────────────────────


def main():
    trajectories = [
        _trajectory_dead_model,
        _trajectory_web_search,
        _trajectory_invalid_tool,
        _trajectory_memory_rescue,
        _trajectory_reason_step,
        _trajectory_idempotency,
        _trajectory_budget_block,
        _trajectory_duplicate_detection,
    ]

    passed = 0
    failed = 0
    print("=" * 60)
    print("  validate_der_tool_resolution.py  —  standing CDD harness")
    print("=" * 60)
    for trajectory in trajectories:
        name = trajectory.__name__.replace("_trajectory_", "TC: ")
        try:
            msg = trajectory()
            print(f"  ✅  {msg}")
            passed += 1
        except Exception as exc:
            print(f"  ❌  {name}  FAILED: {exc}")
            failed += 1

    print()
    print(f"  {passed} passed, {failed} failed")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
