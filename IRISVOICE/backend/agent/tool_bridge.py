#!/usr/bin/env python3
"""
Agent Tool Bridge

This module connects all available tools and services to the agent system,
ensuring the brain and executor models can access:
- MiniCPM Vision/GUI capabilities
- MCP Servers (Browser, File, System, App)
- Native GUI Automation
- Screen Capture and Monitoring

Each capability is exposed as a tool that the agent can call.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class AgentToolBridge:
    """
    Bridges all IRIS capabilities to the agent system.
    This is the central hub that connects models to existing functionality.
    """
    
    def __init__(self):
        self._vision_client = None
        self._gui_operator = None
        self._screen_capture = None
        self._screen_monitor = None
        self._mcp_servers = {}
        self._initialized = False
    
    async def initialize(self):
        """Initialize all available services."""
        if self._initialized:
            return
        
        logger.info("[AgentToolBridge] Initializing...")
        
        # Initialize Vision (MiniCPM via Ollama)
        try:
            from backend.automation import VisionModelClient
            self._vision_client = VisionModelClient()
            result = await self._vision_client.initialize()
            logger.info(f"[AgentToolBridge] Vision: {result}")
        except Exception as e:
            logger.error(f"[AgentToolBridge] Vision init failed: {e}")
        
        # Initialize GUI Operator (Native automation)
        try:
            from backend.automation import NativeGUIOperator
            self._gui_operator = NativeGUIOperator()
            logger.info("[AgentToolBridge] GUI Operator: Ready")
        except Exception as e:
            logger.error(f"[AgentToolBridge] GUI Operator init failed: {e}")
        
        # Initialize Screen Capture
        try:
            from backend.vision import ScreenCapture
            self._screen_capture = ScreenCapture()
            logger.info("[AgentToolBridge] Screen Capture: Ready")
        except Exception as e:
            logger.error(f"[AgentToolBridge] Screen Capture init failed: {e}")
        
        # Initialize MCP Servers
        try:
            from backend.mcp.builtin_servers import (
                BrowserServer, AppLauncherServer, SystemServer, FileManagerServer
            )
            self._mcp_servers = {
                "browser": BrowserServer(),
                "app_launcher": AppLauncherServer(),
                "system": SystemServer(),
                "file_manager": FileManagerServer()
            }
            logger.info(f"[AgentToolBridge] MCP Servers: {list(self._mcp_servers.keys())}")
        except Exception as e:
            logger.error(f"[AgentToolBridge] MCP Servers init failed: {e}")
        
        self._initialized = True
        logger.info("[AgentToolBridge] Initialization complete.")
    
    def get_available_tools(self) -> List[Dict[str, Any]]:
        """Return all tools available to the agent."""
        tools = []
        
        # Vision Tools
        tools.extend([
            {
                "name": "vision_detect_element",
                "description": "Detect a GUI element in a screenshot by description",
                "parameters": {
                    "description": {"type": "string", "description": "Element to find"}
                },
                "category": "vision"
            },
            {
                "name": "vision_analyze_screen",
                "description": "Analyze the current screen and describe what's visible",
                "parameters": {},
                "category": "vision"
            },
            {
                "name": "vision_validate_action",
                "description": "Validate if an action can be performed on an element",
                "parameters": {
                    "action": {"type": "string", "description": "Action (click, type, etc.)"},
                    "target": {"type": "string", "description": "Element description"}
                },
                "category": "vision"
            }
        ])
        
        # Screen Tools
        tools.extend([
            {
                "name": "take_screenshot",
                "description": "Take a screenshot of the current screen",
                "parameters": {},
                "category": "screen"
            },
            {
                "name": "start_screen_monitor",
                "description": "Start background screen monitoring for proactive help",
                "parameters": {
                    "interval": {"type": "integer", "description": "Check interval in seconds"}
                },
                "category": "screen"
            }
        ])
        
        # WEB / GUI Control Tools
        tools.extend([
            {
                "name": "gui_click",
                "description": "Click at coordinates or on an element",
                "parameters": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"}
                },
                "category": "web"
            },
            {
                "name": "gui_type",
                "description": "Type text at current position or coordinates",
                "parameters": {
                    "text": {"type": "string"},
                    "x": {"type": "integer", "optional": True},
                    "y": {"type": "integer", "optional": True}
                },
                "category": "web"
            },
            {
                "name": "gui_press_key",
                "description": "Press a keyboard key",
                "parameters": {
                    "key": {"type": "string", "description": "Key name (ctrl, enter, etc.)"}
                },
                "category": "web"
            }
        ])
        
        # MCP Tools (from builtin servers)
        tools.extend([
            # Browser
            {"name": "open_url", "description": "Open URL in browser", "parameters": {"url": {"type": "string"}}, "category": "browser", "server": "browser"},
            {"name": "search", "description": "Search the web", "parameters": {"query": {"type": "string"}}, "category": "browser", "server": "browser"},
            
            # File Management
            {"name": "read_file", "description": "Read file contents", "parameters": {"path": {"type": "string"}}, "category": "file", "server": "file_manager"},
            {"name": "write_file", "description": "Write to file", "parameters": {"path": {"type": "string"}, "content": {"type": "string"}}, "category": "file", "server": "file_manager"},
            {"name": "list_directory", "description": "List directory", "parameters": {"path": {"type": "string"}}, "category": "file", "server": "file_manager"},
            {"name": "create_directory", "description": "Create directory", "parameters": {"path": {"type": "string"}}, "category": "file", "server": "file_manager"},
            {"name": "delete_file", "description": "Delete file/directory", "parameters": {"path": {"type": "string"}}, "category": "file", "server": "file_manager"},
            
            # System
            {"name": "get_system_info", "description": "Get system information", "parameters": {}, "category": "system", "server": "system"},
            {"name": "lock_screen", "description": "Lock the screen", "parameters": {}, "category": "system", "server": "system"},
            {"name": "shutdown", "description": "Shutdown system", "parameters": {"delay": {"type": "integer", "optional": True}}, "category": "system", "server": "system"},
            {"name": "restart", "description": "Restart system", "parameters": {"delay": {"type": "integer", "optional": True}}, "category": "system", "server": "system"},
            
            # App Launcher
            {"name": "launch_app", "description": "Launch an application", "parameters": {"app_name": {"type": "string"}}, "category": "app", "server": "app_launcher"},
            {"name": "open_file", "description": "Open file with default app", "parameters": {"file_path": {"type": "string"}}, "category": "app", "server": "app_launcher"}
        ])
        
        return tools
    
    # Tool Execution Methods
    
    async def execute_vision_tool(self, tool_name: str, params: Dict) -> Dict:
        """Execute a vision-related tool."""
        if not self._vision_client:
            return {"error": "Vision client not initialized"}
        
        try:
            if tool_name == "vision_detect_element":
                import base64
                screenshot = self._screen_capture.capture() if self._screen_capture else None
                if screenshot:
                    import cv2
                    import numpy as np
                    _, buffer = cv2.imencode('.png', screenshot)
                    b64 = base64.b64encode(buffer).decode()
                    result = await self._vision_client.detect_element(b64, params.get("description", ""))
                    return {"success": True, "result": result}
                return {"error": "No screenshot available"}
            
            elif tool_name == "vision_analyze_screen":
                screenshot = self._screen_capture.capture() if self._screen_capture else None
                if screenshot:
                    import cv2
                    import numpy as np
                    _, buffer = cv2.imencode('.png', screenshot)
                    b64 = base64.b64encode(buffer).decode()
                    result = await self._vision_client.analyze_screen(b64)
                    return {"success": True, "result": result}
                return {"error": "No screenshot available"}
            
            elif tool_name == "vision_validate_action":
                screenshot = self._screen_capture.capture() if self._screen_capture else None
                if screenshot:
                    import cv2
                    import numpy as np
                    _, buffer = cv2.imencode('.png', screenshot)
                    b64 = base64.b64encode(buffer).decode()
                    result = await self._vision_client.validate_action(
                        params.get("action", ""),
                        params.get("target", ""),
                        b64
                    )
                    return {"success": True, "result": result}
                return {"error": "No screenshot available"}
                
        except Exception as e:
            return {"error": str(e)}
        
        return {"error": f"Unknown vision tool: {tool_name}"}
    
    async def execute_gui_tool(self, tool_name: str, params: Dict) -> Dict:
        """Execute a WEB/GUI control tool."""
        if not self._gui_operator:
            return {"error": "GUI Operator not initialized"}
        
        try:
            if tool_name == "gui_click":
                result = await self._gui_operator.click(params.get("x", 0), params.get("y", 0))
                return {"success": True, "result": result}
            
            elif tool_name == "gui_type":
                result = await self._gui_operator.type_text(
                    params.get("text", ""),
                    params.get("x"), params.get("y")
                )
                return {"success": True, "result": result}
            
            elif tool_name == "gui_press_key":
                result = await self._gui_operator.press_key(params.get("key", ""))
                return {"success": True, "result": result}
                
        except Exception as e:
            return {"error": str(e)}
        
        return {"error": f"Unknown WEB/GUI tool: {tool_name}"}
    
    async def execute_mcp_tool(self, server_name: str, tool_name: str, params: Dict) -> Dict:
        """Execute a tool via MCP server."""
        server = self._mcp_servers.get(server_name)
        if not server:
            return {"error": f"MCP server '{server_name}' not found"}
        
        try:
            from backend.mcp.protocol import MCPRequest, MCPMessageType
            
            request = MCPRequest(
                id=f"agent_{datetime.now().timestamp()}",
                method=MCPMessageType.TOOLS_CALL,
                params={"name": tool_name, "arguments": params}
            )
            
            response = await server.handle_request(request)
            return response.result if response.result else {"error": response.error}
            
        except Exception as e:
            return {"error": str(e)}
    
    async def execute_tool(self, tool_name: str, params: Dict) -> Dict:
        """Execute any tool by name."""
        # Map tool names to their execution methods
        vision_tools = ["vision_detect_element", "vision_analyze_screen", "vision_validate_action"]
        gui_tools = ["gui_click", "gui_type", "gui_press_key", "take_screenshot"]
        
        if tool_name in vision_tools:
            return await self.execute_vision_tool(tool_name, params)
        
        if tool_name in gui_tools:
            return await self.execute_gui_tool(tool_name, params)
        
        # MCP Tools
        mcp_tools = {
            # Browser
            "open_url": ("browser", "open_url"),
            "search": ("browser", "search"),
            # File
            "read_file": ("file_manager", "read_file"),
            "write_file": ("file_manager", "write_file"),
            "list_directory": ("file_manager", "list_directory"),
            "create_directory": ("file_manager", "create_directory"),
            "delete_file": ("file_manager", "delete_file"),
            # System
            "get_system_info": ("system", "get_system_info"),
            "lock_screen": ("system", "lock"),
            "shutdown": ("system", "shutdown"),
            "restart": ("system", "restart"),
            # App
            "launch_app": ("app_launcher", "launch_app"),
            "open_file": ("app_launcher", "open_file")
        }
        
        if tool_name in mcp_tools:
            server_name, mcp_tool_name = mcp_tools[tool_name]
            return await self.execute_mcp_tool(server_name, mcp_tool_name, params)
        
        return {"error": f"Unknown tool: {tool_name}"}
    
    def get_status(self) -> Dict:
        """Get status of all connected services."""
        return {
            "initialized": self._initialized,
            "vision_available": self._vision_client is not None,
            "gui_operator_available": self._gui_operator is not None,
            "screen_capture_available": self._screen_capture is not None,
            "mcp_servers": list(self._mcp_servers.keys()),
            "total_tools": len(self.get_available_tools())
        }


# Singleton
_agent_tool_bridge: Optional[AgentToolBridge] = None


def get_agent_tool_bridge() -> AgentToolBridge:
    """Get the singleton AgentToolBridge instance."""
    global _agent_tool_bridge
    if _agent_tool_bridge is None:
        _agent_tool_bridge = AgentToolBridge()
    return _agent_tool_bridge


async def initialize_agent_tools():
    """Initialize all agent tools and services."""
    bridge = get_agent_tool_bridge()
    await bridge.initialize()
    return bridge
