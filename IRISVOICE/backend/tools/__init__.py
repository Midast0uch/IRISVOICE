"""
IRIS Backend Tools Module

This module contains MCP tool integration components:
- Tool bridge
- MCP client
- Server manager
- Security filter
- Audit logger
"""

__all__ = [
    'get_server_manager',
    'get_tool_registry',
    'ServerConfig',
    'BrowserServer',
    'AppLauncherServer',
    'SystemServer',
    'FileManagerServer',
    'GUIAutomationServer'
]

# Re-export MCP components from their original locations
from backend.mcp import (
    get_server_manager,
    get_tool_registry,
    ServerConfig,
    BrowserServer,
    AppLauncherServer,
    SystemServer,
    FileManagerServer,
    GUIAutomationServer
)
