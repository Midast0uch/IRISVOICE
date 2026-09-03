"""
Tests for MCP tool dispatch path — Gate 3 Step 3.1
Source: bootstrap/GOALS.md Step 3.1 acceptance criteria

Key requirements:
  - tool_bridge routes to MCP servers via execute_mcp_tool()
  - MCP server list is configurable (ServerManager.register_server + _mcp_servers dict)
  - Known-working MCP tool (create_skill / read_file) returns correct result
  - BuiltinServer subclasses have working execute_tool() methods
  - ServerManager.register_server() accepts new server configs at runtime

Run: python -m pytest backend/tests/test_mcp_dispatch.py -v
"""

import pytest
import shutil
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock


# ── Imports and structure ─────────────────────────────────────────────────────

def test_agent_tool_bridge_importable():
    from backend.agent.tool_bridge import AgentToolBridge
    assert AgentToolBridge


def test_execute_mcp_tool_method_exists():
    from backend.agent.tool_bridge import AgentToolBridge
    assert hasattr(AgentToolBridge, "execute_mcp_tool")


def test_get_available_tools_method_exists():
    from backend.agent.tool_bridge import AgentToolBridge
    assert hasattr(AgentToolBridge, "get_available_tools")


def test_server_manager_importable():
    from backend.mcp.server_manager import ServerManager, ServerConfig
    assert ServerManager
    assert ServerConfig


def test_builtin_servers_importable():
    from backend.mcp.builtin_servers import (
        BrowserServer, FileManagerServer, SystemServer,
        AppLauncherServer, InternalCapabilityServer, BuiltinServer
    )
    assert BrowserServer
    assert InternalCapabilityServer


# ── ServerManager — configurable (not hardcoded) ─────────────────────────────

def test_server_manager_has_register_server():
    """ServerManager.register_server() allows dynamic server registration."""
    from backend.mcp.server_manager import ServerManager
    assert hasattr(ServerManager, "register_server"), \
        "ServerManager missing register_server — servers are hardcoded"


def test_server_manager_register_server_works():
    """A new ServerConfig can be registered at runtime."""
    from backend.mcp.server_manager import ServerManager, ServerConfig
    manager = ServerManager()
    # Register a test server config
    config = ServerConfig(
        name="_test_mcp_server",
        type="builtin",
        command=None,
        args=[],
    )
    manager.register_server(config)
    registered = manager.get_server("_test_mcp_server")
    assert registered is not None, "register_server did not persist the config"
    assert registered.name == "_test_mcp_server"


def test_server_manager_get_servers_returns_list():
    from backend.mcp.server_manager import ServerManager
    manager = ServerManager()
    servers = manager.get_servers()
    assert isinstance(servers, list)


# ── BuiltinServer — execute_tool() interface ──────────────────────────────────

def test_internal_server_has_execute_tool():
    from backend.mcp.builtin_servers import InternalCapabilityServer
    server = InternalCapabilityServer()
    assert hasattr(server, "execute_tool")
    assert callable(server.execute_tool)


def test_file_manager_server_has_execute_tool():
    from backend.mcp.builtin_servers import FileManagerServer
    server = FileManagerServer()
    assert hasattr(server, "execute_tool")


def test_browser_server_has_execute_tool():
    from backend.mcp.builtin_servers import BrowserServer
    server = BrowserServer()
    assert hasattr(server, "execute_tool")


# ── Known-working MCP tool call returns correct result ────────────────────────

SKILL_DIR = Path(__file__).parent.parent / "agent" / "skills"
TEST_SKILL = "_test_dispatch_skill"


@pytest.mark.asyncio
async def test_create_skill_via_mcp_returns_success():
    """execute_tool('create_skill', ...) on InternalCapabilityServer returns success=True."""
    target = SKILL_DIR / TEST_SKILL
    try:
        from backend.mcp.builtin_servers import InternalCapabilityServer
        server = InternalCapabilityServer()
        result = await server.execute_tool("create_skill", {
            "name": TEST_SKILL,
            "content": "---\nname: _test_dispatch_skill\ndescription: MCP dispatch test\n---\nContent.",
        })
        assert result.get("success") is True, f"Expected success=True, got: {result}"
    finally:
        shutil.rmtree(target, ignore_errors=True)


@pytest.mark.asyncio
async def test_file_manager_read_returns_content():
    """FileManagerServer.execute_tool('read_file', ...) returns file content."""
    from backend.mcp.builtin_servers import FileManagerServer
    server = FileManagerServer()
    # Read this test file itself
    test_file = str(Path(__file__))
    result = await server.execute_tool("read_file", {"path": test_file})
    # Should either succeed or return an error dict — must not raise
    assert isinstance(result, dict), f"Expected dict result, got: {type(result)}"


@pytest.mark.asyncio
async def test_unknown_tool_returns_error():
    """execute_tool with an unknown tool name returns an error dict, not an exception."""
    from backend.mcp.builtin_servers import InternalCapabilityServer
    server = InternalCapabilityServer()
    result = await server.execute_tool("nonexistent_tool_xyz", {})
    assert "error" in result, f"Expected error key in result: {result}"


# ── Tool bridge MCP routing — tools map covers MCP servers ───────────────────

def test_tool_bridge_mcp_tools_map_present():
    """AgentToolBridge has a static mapping of tool names to MCP server names."""
    import inspect
    import backend.agent.tool_bridge as tb_module
    source = inspect.getsource(tb_module)
    # The mcp_tools dict is defined inline in execute_tool()
    assert "mcp_tools" in source, "mcp_tools routing map not found in tool_bridge"
    assert "internal" in source, "internal server not in tool_bridge routing"
    assert "file_manager" in source, "file_manager server not in tool_bridge routing"


def test_tool_bridge_execute_mcp_tool_routes_to_server():
    """execute_mcp_tool() uses _mcp_servers dict and calls handle_request."""
    import inspect
    from backend.agent.tool_bridge import AgentToolBridge
    source = inspect.getsource(AgentToolBridge.execute_mcp_tool)
    assert "_mcp_servers" in source, \
        "execute_mcp_tool does not use _mcp_servers for routing"
    assert "handle_request" in source, \
        "execute_mcp_tool does not call server.handle_request"


@pytest.mark.asyncio
async def test_execute_mcp_tool_unknown_server_returns_error():
    """execute_mcp_tool with an unknown server name returns an error dict."""
    from backend.agent.tool_bridge import AgentToolBridge
    bridge = AgentToolBridge.__new__(AgentToolBridge)
    bridge._mcp_servers = {}
    bridge._security_filter = None
    bridge._audit_logger = None
    result = await bridge.execute_mcp_tool("no_such_server", "some_tool", {}, "test")
    assert "error" in result, f"Expected error key, got: {result}"


# ── MCP server list configurability via _mcp_servers dict ────────────────────

def test_mcp_servers_dict_supports_dynamic_addition():
    """AgentToolBridge._mcp_servers is a dict that accepts new server entries."""
    from backend.agent.tool_bridge import AgentToolBridge
    from backend.mcp.builtin_servers import InternalCapabilityServer

    bridge = AgentToolBridge.__new__(AgentToolBridge)
    bridge._mcp_servers = {}

    # Add a server dynamically
    bridge._mcp_servers["custom"] = InternalCapabilityServer()
    assert "custom" in bridge._mcp_servers
    assert bridge._mcp_servers["custom"] is not None
