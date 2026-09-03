"""
Unit tests for the crawler's structured error envelope (REQ-10 AC1 / Part A).

The crawler used to return a bare error string, so the black box's
_classify_error heuristic decided the class. These tests pin the explicit
error_type the crawler now emits, and that the box's dispatch() prefers an
explicit envelope over the heuristic.
"""
import pytest

from backend.agent.tool_bridge import _crawler_error_type
from backend.agent.tool_decision import ToolDecisionBox, Decision, DecisionKind


def test_crawler_error_type_mapping():
    assert _crawler_error_type("no candidate urls") == "permanent"
    assert _crawler_error_type("no sources found for query") == "permanent"
    assert _crawler_error_type("rate limit exceeded") == "rate_limit"
    assert _crawler_error_type("HTTP 429 too many requests") == "rate_limit"
    assert _crawler_error_type("connection reset by peer") == "transient"
    assert _crawler_error_type("request timed out") == "transient"
    assert _crawler_error_type("page not found 404") == "not_found"
    assert _crawler_error_type("") == "permanent"
    assert _crawler_error_type("some weird failure") == "permanent"


def test_box_dispatch_prefers_explicit_error_type():
    """Part A: when a tool returns an explicit error_type, dispatch uses it
    instead of re-classifying via the heuristic."""
    from unittest.mock import MagicMock, AsyncMock

    fake_bridge = MagicMock()
    fake_bridge.execute_tool = AsyncMock(return_value={
        "success": False,
        "error": "no candidate urls",
        "error_type": "permanent",  # explicit envelope from the crawler
    })
    box = ToolDecisionBox(
        router=MagicMock(),
        tool_bridge=fake_bridge,
        get_available_tools=MagicMock(return_value=[]),
        validate_tool_call=MagicMock(return_value=(True, "")),
    )
    decision = Decision(kind=DecisionKind.TOOL, tool="crawler_query", params={"query": "x"})
    result = box.dispatch(decision, session_id="s1", conversation_id="c1")
    assert result.success is False
    # Explicit envelope wins over the heuristic (which would also say permanent
    # here, but the point is the box reads error_type from the tool result).
    assert result.error_type == "permanent"
