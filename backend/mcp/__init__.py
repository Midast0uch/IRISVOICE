"""
IRIS MCP (Model Context Protocol) Module
Client for MCP servers and built-in tool implementations
"""

from .client import MCPClient, get_mcp_client
from .server_manager import ServerManager, get_server_manager
from .tools import ToolRegistry, get_tool_registry
from .builtin_servers import (
    BrowserServer,
    AppLauncherServer,
    SystemServer,
    FileManagerServer
)

__all__ = [
    "MCPClient",
    "get_mcp_client",
    "ServerManager",
    "get_server_manager",
    "ToolRegistry",
    "get_tool_registry",
    "BrowserServer",
    "AppLauncherServer",
    "SystemServer",
    "FileManagerServer",
]
