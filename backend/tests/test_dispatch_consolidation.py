"""Tests for dispatch consolidation (Phase 5.3 / research D3).

Verifies:
  - AgentToolBridge._execute_tool_with_resilience routes dispatch through
    retry_with_backoff (resilience in one place).
  - ToolExecutor.execute delegates to AgentToolBridge.execute_tool and converts
    the bridge's dict result into an ExecutionResult.
  - ToolExecutor falls back to its own local handlers when the bridge reports an
    "Unknown tool" (safe cutover for legacy skill tools).
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent.tool_bridge import AgentToolBridge
from backend.agent.tool_executor import ToolExecutor


@pytest.fixture(autouse=True)
def _isolate_globals():
    """ToolExecutor and AgentToolBridge are process-wide singletons, and
    ToolExecutor.__init__ registers built-in tool schemas into the global
    InputValidator. Reset all three around each test so this module doesn't
    leak state into others (e.g. test_input_validation.py, which runs later
    alphabetically and reuses the same ToolExecutor singleton)."""
    ToolExecutor._instance = None
    try:
        import backend.agent.tool_bridge as _tb
        _tb._agent_tool_bridge = None
    except Exception:
        pass
    try:
        from backend.core.input_validator import reset_input_validator
        reset_input_validator()
    except Exception:
        pass
    yield
    ToolExecutor._instance = None
    try:
        import backend.agent.tool_bridge as _tb
        _tb._agent_tool_bridge = None
    except Exception:
        pass
    try:
        from backend.core.input_validator import reset_input_validator
        reset_input_validator()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_execute_tool_with_resilience_wraps_dispatch():
    calls = []

    async def fake_retry(fn, label=None, max_retries=3, base_delay=0.5):
        calls.append(label)
        return await fn()

    with patch("backend.agent.resilience.retry_with_backoff", fake_retry):
        bridge = AgentToolBridge()
        result = await bridge._execute_tool_with_resilience("nonexistent_tool", {}, "sess", "")
    assert isinstance(result, dict)
    assert result.get("error", "").startswith("Unknown tool")
    assert calls == ["tool:nonexistent_tool"]


@pytest.mark.asyncio
async def test_tool_executor_delegates_to_bridge():
    executor = ToolExecutor()
    fake_bridge = MagicMock()
    fake_bridge.execute_tool = AsyncMock(
        return_value={"success": True, "output": "bridged"}
    )
    with patch("backend.agent.tool_bridge.get_agent_tool_bridge", return_value=fake_bridge):
        result = await executor.execute("some_tool", {"x": 1})
    assert result.success is True
    assert result.output == {"success": True, "output": "bridged"}
    fake_bridge.execute_tool.assert_called_once()


@pytest.mark.asyncio
async def test_tool_executor_falls_back_on_unknown_tool():
    executor = ToolExecutor()
    # Make validation permissive and register a local handler so the fallback
    # path can actually execute.
    executor.validate_parameters = MagicMock(return_value=(True, None, {"x": 1}))
    local_tool = MagicMock()
    local_tool.async_handler = AsyncMock(return_value={"done": True})
    executor._tools["local_tool"] = local_tool

    fake_bridge = MagicMock()
    fake_bridge.execute_tool = AsyncMock(
        return_value={"error": "Unknown tool: local_tool"}
    )
    with patch("backend.agent.tool_bridge.get_agent_tool_bridge", return_value=fake_bridge):
        result = await executor.execute("local_tool", {"x": 1})
    assert result.success is True
    assert result.output == {"done": True}
    # Bridge was asked first, then we fell back locally.
    fake_bridge.execute_tool.assert_called_once()
    local_tool.async_handler.assert_called_once()
