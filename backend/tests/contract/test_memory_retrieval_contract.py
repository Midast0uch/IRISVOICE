"""Contract tests: memory/document retrieval behavior (REQ-7).

Spec: specs/long-horizon-der-execution/
- Repeated read-only document access must not be treated as a duplicate
  side-effect (the dispatcher exempts idempotent read tools).
- Missing memory interface must degrade safely (no AttributeError poisoning a
  step) — recall_memory returns an honest empty result.
"""

from __future__ import annotations

import asyncio

from backend.agent.tool_decision import (
    Decision,
    DecisionKind,
    ToolDecisionBox,
)


def _make_read_box():
    """ToolDecisionBox whose fake bridge returns a fixed doc payload for every
    get_rendered_documents call — used to prove repeated reads are NOT rejected
    as duplicate side effects."""
    calls = []

    class _ReadTB:
        async def execute_tool(self, name, params, **kw):
            calls.append(name)
            return {
                "success": True,
                "content": "rendered documents payload",
                "sources": [{"url": "https://a.com", "title": "A"}],
            }

    box = ToolDecisionBox(
        router=None,
        tool_bridge=None,
        get_available_tools=lambda: [
            {"name": "get_rendered_documents", "description": "read docs"},
        ],
        validate_tool_call=lambda name, params: (True, None),
        infer_fn=lambda prompt, **kw: "",
        memory_lookup_fn=lambda _g: None,
    )
    box._tool_bridge = _ReadTB()
    box._last_call = {}
    return box, calls


def test_repeated_document_reads_not_duplicate():
    """REQ-7: repeated read-only get_rendered_documents calls must succeed —
    the duplicate-call repeat guard exempts idempotent read tools."""
    box, calls = _make_read_box()
    for _ in range(3):
        dr = box.dispatch(
            Decision(kind=DecisionKind.TOOL, tool="get_rendered_documents", params={})
        )
        assert dr.success is True, f"repeat read failed: {dr.error}"
    assert len(calls) == 3  # all three dispatched; none rejected as duplicate


def test_recall_memory_degrades_without_memory_interface():
    """REQ-7: with no memory interface wired, recall_memory returns a degraded
    success (empty results), never an AttributeError."""
    from backend.agent.tool_bridge import AgentToolBridge

    bridge = AgentToolBridge.__new__(AgentToolBridge)  # no _memory_interface
    result = asyncio.run(
        bridge.execute_tool("recall_memory", {"query": "python"}, "sess-1")
    )
    assert isinstance(result, dict)
    assert result.get("success") is True, f"degraded recall failed: {result}"
    assert result.get("results") == []
