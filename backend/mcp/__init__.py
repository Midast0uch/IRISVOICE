"""
IRIS MCP (Model Context Protocol) Module
Client for MCP servers and built-in tool implementations
"""

from .client import MCPClient, get_mcp_client
from .server_manager import ServerManager, get_server_manager, ServerConfig
from .tools import ToolRegistry, get_tool_registry
from .builtin_servers import (
    BrowserServer,
    AppLauncherServer,
    SystemServer,
    FileManagerServer
)
from .gui_automation_server import GUIAutomationServer

__all__ = [
    "MCPClient",
    "get_mcp_client",
    "ServerManager",
    "get_server_manager",
    "ServerConfig",
    "ToolRegistry",
    "get_tool_registry",
    "BrowserServer",
    "AppLauncherServer",
    "SystemServer",
    "FileManagerServer",
    "GUIAutomationServer",
]
