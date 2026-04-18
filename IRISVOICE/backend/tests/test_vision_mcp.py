"""
Vision MCP integration tests — LFM2.5-VL via MCP tools in AgentToolBridge.

Requirements tested:
  - VisionMCPServer registers 5 vision.* tools with correct schemas
  - Tool calls return graceful error strings (never raise) when vision server is down
  - AgentToolBridge._mcp_servers contains "vision" key after initialize()
  - execute_tool("get_screen_context") returns a string (not raises)
  - LFMVLProvider and screenshot_to_bytes are importable

No llama-server required for this file.
For end-to-end tests with real inference: backend/tests/test_vision_integration.py

Run: python -m pytest backend/tests/test_vision_mcp.py -v
"""

import pytest
import asyncio


# ── Import checks ─────────────────────────────────────────────────────────────

def test_lfm_vl_provider_importable():
    from backend.tools.lfm_vl_provider import LFMVLProvider, screenshot_to_bytes
    assert LFMVLProvider
    assert callable(screenshot_to_bytes)


def test_vision_mcp_server_importable():
    from backend.tools.vision_mcp_server import VisionMCPServer
    assert VisionMCPServer


def test_vision_mcp_server_is_builtin_server():
    from backend.tools.vision_mcp_server import VisionMCPServer
    from backend.mcp.builtin_servers import BuiltinServer
    assert issubclass(VisionMCPServer, BuiltinServer)


# ── Tool schema validation ────────────────────────────────────────────────────

def test_vision_mcp_server_has_5_tools():
    from backend.tools.vision_mcp_server import VisionMCPServer
    server = VisionMCPServer()
    tools = server._tools
    assert len(tools) == 5


def test_vision_tools_have_correct_names():
    from backend.tools.vision_mcp_server import VisionMCPServer
    server = VisionMCPServer()
    names = {t.name for t in server._tools}
    assert names == {
        "vision.analyze_screen",
        "vision.find_ui_element",
        "vision.read_text",
        "vision.suggest_next_action",
        "vision.describe_live_frame",
    }


def test_vision_tools_have_descriptions():
    from backend.tools.vision_mcp_server import VisionMCPServer
    server = VisionMCPServer()
    for tool in server._tools:
        assert tool.description, f"Tool {tool.name} missing description"


def test_vision_tools_have_input_schema():
    from backend.tools.vision_mcp_server import VisionMCPServer
    server = VisionMCPServer()
    for tool in server._tools:
        assert tool.input_schema is not None, f"Tool {tool.name} missing input_schema"
        assert tool.input_schema.get("type") == "object"


# ── Graceful error on server-down ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_analyze_screen_returns_string_when_server_down():
    """No llama-server running — must return error string, never raise."""
    from backend.tools.vision_mcp_server import VisionMCPServer
    server = VisionMCPServer()
    result = await server.execute_tool("vision.analyze_screen", {"question": "What is on screen?"})
    # Result must be an MCP content dict
    assert isinstance(result, dict)
    assert "content" in result
    text = result["content"][0]["text"]
    assert isinstance(text, str)
    assert len(text) > 0


@pytest.mark.asyncio
async def test_describe_live_frame_returns_string_when_server_down():
    from backend.tools.vision_mcp_server import VisionMCPServer
    server = VisionMCPServer()
    result = await server.execute_tool("vision.describe_live_frame", {})
    assert isinstance(result, dict)
    text = result["content"][0]["text"]
    assert isinstance(text, str)


@pytest.mark.asyncio
async def test_find_ui_element_returns_string_when_server_down():
    from backend.tools.vision_mcp_server import VisionMCPServer
    server = VisionMCPServer()
    result = await server.execute_tool(
        "vision.find_ui_element", {"element_description": "submit button"}
    )
    assert isinstance(result, dict)
    text = result["content"][0]["text"]
    assert isinstance(text, str)


@pytest.mark.asyncio
async def test_unknown_tool_returns_error_string():
    from backend.tools.vision_mcp_server import VisionMCPServer
    server = VisionMCPServer()
    result = await server.execute_tool("vision.nonexistent", {})
    text = result["content"][0]["text"]
    assert "Unknown" in text or "nonexistent" in text.lower() or "error" in text.lower()


# ── AgentToolBridge integration ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_tool_bridge_has_vision_server():
    """Vision must be wired into the agent kernel's MCP dispatch."""
    from backend.agent.tool_bridge import AgentToolBridge
    bridge = AgentToolBridge()
    await bridge.initialize()
    assert "vision" in bridge._mcp_servers, (
        "VisionMCPServer not found in _mcp_servers. "
        "Check tool_bridge.py initialize() for VisionMCPServer registration."
    )


@pytest.mark.asyncio
async def test_vision_get_context_returns_dict_without_hard_error():
    """Agent kernel's vision_get_context tool must always return a dict (even when server is down)."""
    from backend.agent.tool_bridge import AgentToolBridge
    bridge = AgentToolBridge()
    await bridge.initialize()
    result = await bridge.execute_vision_tool("vision_get_context", {})
    assert isinstance(result, dict), (
        f"vision_get_context returned {type(result)} — expected dict. "
        f"Got: {repr(result)}"
    )
    # Must have either 'success' or 'error' key — never raises
    assert "success" in result or "error" in result


# ── Provider config ───────────────────────────────────────────────────────────

def test_lfm_vl_config_defaults():
    from backend.tools.lfm_vl_provider import LFMVLConfig
    cfg = LFMVLConfig()
    assert cfg.base_url == "http://localhost:8081/v1"
    assert cfg.temperature == pytest.approx(0.1)
    assert cfg.min_p == pytest.approx(0.15)
    assert cfg.repetition_penalty == pytest.approx(1.05)


def test_lfm_vl_provider_health_check_false_when_server_down():
    """health_check() must return False (not raise) when llama-server is not running."""
    from backend.tools.lfm_vl_provider import LFMVLProvider
    provider = LFMVLProvider()
    result = provider.health_check()
    # Server is not running in CI — must be False without raising
    assert result is False


def test_lfm_vl_provider_analyze_returns_error_string_when_server_down():
    """analyze_screen() must return an error string (not raise) when server is down."""
    from backend.tools.lfm_vl_provider import LFMVLProvider
    provider = LFMVLProvider()
    result = provider.analyze_screen(b"fake_image_bytes", "What is on screen?")
    assert isinstance(result, str)
    assert len(result) > 0
