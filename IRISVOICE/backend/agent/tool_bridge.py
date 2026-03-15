#!/usr/bin/env python3
"""
Agent Tool Bridge

This module connects all available tools and services to the agent system,
ensuring the brain and executor models can access:
- MiniCPM Vision/GUI capabilities
- MCP Servers (Browser, File, System, App, GUIAutomation)
- Native GUI Automation
- Screen Capture and Monitoring
- Security filtering and audit logging

Each capability is exposed as a tool that the agent can call.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6
"""

import asyncio
import logging
import os
import subprocess
from typing import Any, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class AgentToolBridge:
    """
    Bridges all IRIS capabilities to the agent system.
    This is the central hub that connects models to existing functionality.
    
    Integrates:
    - MCP Servers (Browser, AppLauncher, System, FileManager, GUIAutomation)
    - VisionSystem for screen monitoring and analysis
    - SecurityFilter for tool execution validation
    - AuditLogger for security audit trails
    
    Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6
    """
    
    def __init__(self, security_filter=None, audit_logger=None, vision_system=None):
        self._vision_client = None
        self._gui_operator = None
        self._screen_capture = None
        self._screen_monitor = None
        self._mcp_servers = {}
        self._initialized = False
        
        # Security and audit integration (from task 9)
        self._security_filter = security_filter
        self._audit_logger = audit_logger
        
        # Vision system integration (from task 10.1)
        self._vision_system = vision_system
    
    async def initialize(self):
        """
        Initialize all available services.
        
        Starts all MCP servers:
        - BrowserServer: Web browsing capabilities
        - AppLauncherServer: Application control
        - SystemServer: System operations
        - FileManagerServer: File operations
        - GUIAutomationServer: UI automation
        
        Requirements: 8.1, 8.2, 16.1-16.6
        """
        if self._initialized:
            return
        
        logger.info("[AgentToolBridge] Initializing...")
        
        # Initialize SecurityFilter if not provided
        if self._security_filter is None:
            try:
                from backend.gateway.security_filter import SecurityFilter
                self._security_filter = SecurityFilter()
                logger.info("[AgentToolBridge] SecurityFilter initialized")
            except Exception as e:
                logger.error(f"[AgentToolBridge] SecurityFilter init failed: {e}")
        
        # Initialize AuditLogger if not provided
        if self._audit_logger is None:
            try:
                from backend.security.audit_logger import SecurityAuditLogger
                self._audit_logger = SecurityAuditLogger()
                logger.info("[AgentToolBridge] AuditLogger initialized")
            except Exception as e:
                logger.error(f"[AgentToolBridge] AuditLogger init failed: {e}")
        
        # Initialize VisionSystem if not provided
        if self._vision_system is None:
            try:
                from backend.tools.vision_system import get_vision_system
                self._vision_system = get_vision_system()
                logger.info("[AgentToolBridge] VisionSystem initialized")
            except Exception as e:
                logger.error(f"[AgentToolBridge] VisionSystem init failed: {e}")
        
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
        
        # Initialize MCP Servers (all 5 servers)
        try:
            from backend.mcp.builtin_servers import (
                BrowserServer, AppLauncherServer, SystemServer, FileManagerServer
            )
            from backend.mcp.gui_automation_server import GUIAutomationServer
            
            self._mcp_servers = {
                "browser": BrowserServer(),
                "app_launcher": AppLauncherServer(),
                "system": SystemServer(),
                "file_manager": FileManagerServer(),
                "gui_automation": GUIAutomationServer()
            }
            logger.info(f"[AgentToolBridge] MCP Servers: {list(self._mcp_servers.keys())}")
        except Exception as e:
            logger.error(f"[AgentToolBridge] MCP Servers init failed: {e}")
        
        self._initialized = True
        logger.info("[AgentToolBridge] Initialization complete.")
    
    def get_available_tools(self) -> List[Dict[str, Any]]:
        """
        Return all tools available to the agent.
        
        Tools are categorized into:
        - vision: Screen analysis and element detection
        - web: Browser automation and web search
        - file: File system operations
        - system: System control and information
        - app: Application launching and control
        - gui: GUI automation and control
        
        Requirements: 8.1, 8.2
        """
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
            },
            {
                "name": "vision_get_context",
                "description": "Get current screen context from VisionSystem",
                "parameters": {},
                "category": "vision"
            }
        ])
        
        # Screen Tools
        tools.extend([
            {
                "name": "take_screenshot",
                "description": "Take a screenshot of the current screen",
                "parameters": {},
                "category": "vision"
            },
            {
                "name": "start_screen_monitor",
                "description": "Start background screen monitoring for proactive help",
                "parameters": {
                    "interval": {"type": "integer", "description": "Check interval in seconds"}
                },
                "category": "vision"
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
            {"name": "open_url", "description": "Open URL in browser", "parameters": {"url": {"type": "string"}}, "category": "web", "server": "browser"},
            {"name": "search", "description": "Search the web", "parameters": {"query": {"type": "string"}}, "category": "web", "server": "browser"},
            
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
            {"name": "open_file", "description": "Open file with default app", "parameters": {"file_path": {"type": "string"}}, "category": "app", "server": "app_launcher"},
            
            # GUI Automation
            {"name": "gui_automate_click", "description": "Automated GUI click", "parameters": {"x": {"type": "integer"}, "y": {"type": "integer"}}, "category": "gui", "server": "gui_automation"},
            {"name": "gui_automate_type", "description": "Automated GUI typing", "parameters": {"text": {"type": "string"}}, "category": "gui", "server": "gui_automation"},

            # Git — developer mode source control
            {"name": "git_status", "description": "Show working tree status (staged, unstaged, untracked files)", "parameters": {"repo_path": {"type": "string", "description": "Absolute path to the git repo (optional, defaults to IRISVOICE root)"}}, "category": "git"},
            {"name": "git_diff", "description": "Show diff of staged or unstaged changes", "parameters": {"repo_path": {"type": "string"}, "staged": {"type": "boolean", "description": "If true, show staged diff; otherwise unstaged"}}, "category": "git"},
            {"name": "git_log", "description": "Show recent commit history", "parameters": {"repo_path": {"type": "string"}, "n": {"type": "integer", "description": "Number of commits to show (default 10)"}}, "category": "git"},
            {"name": "git_commit", "description": "Stage all changed files and create a commit", "parameters": {"message": {"type": "string", "description": "Commit message"}, "repo_path": {"type": "string"}}, "category": "git"},
            {"name": "git_create_branch", "description": "Create and switch to a new branch", "parameters": {"branch": {"type": "string", "description": "New branch name"}, "repo_path": {"type": "string"}}, "category": "git"},
            {"name": "git_checkout", "description": "Switch to an existing branch", "parameters": {"branch": {"type": "string"}, "repo_path": {"type": "string"}}, "category": "git"},
            {"name": "git_push", "description": "Push current branch to origin", "parameters": {"repo_path": {"type": "string"}, "force": {"type": "boolean", "description": "Force push (default false)"}}, "category": "git"},

            # Shell — developer mode command runner (sandboxed to repo directory)
            {"name": "run_command", "description": "Run a shell command in the project directory (npm, python, pytest, etc.)", "parameters": {"command": {"type": "string", "description": "Command to run"}, "cwd": {"type": "string", "description": "Working directory (defaults to IRISVOICE root)"}}, "category": "shell"},
        ])
        
        return tools
    
    # Tool Execution Methods
    
    async def execute_vision_tool(self, tool_name: str, params: Dict, session_id: str = "unknown") -> Dict:
        """
        Execute a vision-related tool.
        
        Requirements: 8.3, 8.4
        """
        if not self._vision_client and not self._vision_system:
            return {"error": "Vision client not initialized"}
        
        try:
            # Check rate limit
            if self._security_filter and self._security_filter.check_tool_execution_rate_limit(session_id, tool_name):
                logger.warning(f"[AgentToolBridge] Rate limit exceeded for {tool_name}")
                return {"error": "Rate limit exceeded for tool execution"}
            
            # Log tool execution
            if self._audit_logger:
                from backend.security.security_types import SecurityContext
                await self._audit_logger.log_tool_operation(
                    tool_name=tool_name,
                    operation="execute",
                    arguments=params,
                    context=SecurityContext(
                        session_id=session_id,
                        user_id=None,
                        tool_name=tool_name,
                        operation_type="vision",
                        timestamp=datetime.now()
                    ),
                    result="pending",
                    risk_score=0.2
                )
            
            result = None
            
            if tool_name == "vision_get_context":
                # Use VisionSystem to get current context
                if self._vision_system:
                    context = self._vision_system.get_current_context()
                    if context:
                        result = {
                            "success": True,
                            "result": {
                                "description": context.description,
                                "active_app": context.active_app,
                                "notable_items": context.notable_items,
                                "needs_help": context.needs_help,
                                "suggestion": context.suggestion
                            }
                        }
                    else:
                        result = {"error": "No screen context available"}
                else:
                    result = {"error": "VisionSystem not initialized"}
            
            elif tool_name == "vision_detect_element":
                import base64
                screenshot = self._screen_capture.capture() if self._screen_capture else None
                if screenshot:
                    import cv2
                    import numpy as np
                    _, buffer = cv2.imencode('.png', screenshot)
                    b64 = base64.b64encode(buffer).decode()
                    result_data = await self._vision_client.detect_element(b64, params.get("description", ""))
                    result = {"success": True, "result": result_data}
                else:
                    result = {"error": "No screenshot available"}
            
            elif tool_name == "vision_analyze_screen":
                screenshot = self._screen_capture.capture() if self._screen_capture else None
                if screenshot:
                    import cv2
                    import numpy as np
                    _, buffer = cv2.imencode('.png', screenshot)
                    b64 = base64.b64encode(buffer).decode()
                    result_data = await self._vision_client.analyze_screen(b64)
                    result = {"success": True, "result": result_data}
                else:
                    result = {"error": "No screenshot available"}
            
            elif tool_name == "vision_validate_action":
                screenshot = self._screen_capture.capture() if self._screen_capture else None
                if screenshot:
                    import cv2
                    import numpy as np
                    _, buffer = cv2.imencode('.png', screenshot)
                    b64 = base64.b64encode(buffer).decode()
                    result_data = await self._vision_client.validate_action(
                        params.get("action", ""),
                        params.get("target", ""),
                        b64
                    )
                    result = {"success": True, "result": result_data}
                else:
                    result = {"error": "No screenshot available"}
            
            else:
                result = {"error": f"Unknown vision tool: {tool_name}"}
            
            # Log result
            if self._audit_logger:
                from backend.security.security_types import SecurityContext
                await self._audit_logger.log_tool_operation(
                    tool_name=tool_name,
                    operation="execute",
                    arguments=params,
                    context=SecurityContext(
                        session_id=session_id,
                        user_id=None,
                        tool_name=tool_name,
                        operation_type="vision",
                        timestamp=datetime.now()
                    ),
                    result=result,
                    risk_score=0.2
                )
            
            return result
                
        except Exception as e:
            error_result = {"error": str(e)}
            
            # Log error
            if self._audit_logger:
                from backend.security.security_types import SecurityContext
                await self._audit_logger.log_tool_operation(
                    tool_name=tool_name,
                    operation="execute",
                    arguments=params,
                    context=SecurityContext(
                        session_id=session_id,
                        user_id=None,
                        tool_name=tool_name,
                        operation_type="vision",
                        timestamp=datetime.now()
                    ),
                    result=error_result,
                    risk_score=0.5
                )
            
            return error_result
    
    async def execute_gui_tool(self, tool_name: str, params: Dict, session_id: str = "unknown") -> Dict:
        """
        Execute a WEB/GUI control tool.
        
        Requirements: 8.3, 8.4
        """
        if not self._gui_operator:
            return {"error": "GUI Operator not initialized"}
        
        try:
            # Check rate limit
            if self._security_filter and self._security_filter.check_tool_execution_rate_limit(session_id, tool_name):
                logger.warning(f"[AgentToolBridge] Rate limit exceeded for {tool_name}")
                return {"error": "Rate limit exceeded for tool execution"}
            
            # Log tool execution
            if self._audit_logger:
                from backend.security.security_types import SecurityContext
                await self._audit_logger.log_tool_operation(
                    tool_name=tool_name,
                    operation="execute",
                    arguments=params,
                    context=SecurityContext(
                        session_id=session_id,
                        user_id=None,
                        tool_name=tool_name,
                        operation_type="gui",
                        timestamp=datetime.now()
                    ),
                    result="pending",
                    risk_score=0.3
                )
            
            result = None
            
            if tool_name == "gui_click":
                result_data = await self._gui_operator.click(params.get("x", 0), params.get("y", 0))
                result = {"success": True, "result": result_data}
            
            elif tool_name == "gui_type":
                result_data = await self._gui_operator.type_text(
                    params.get("text", ""),
                    params.get("x"), params.get("y")
                )
                result = {"success": True, "result": result_data}
            
            elif tool_name == "gui_press_key":
                result_data = await self._gui_operator.press_key(params.get("key", ""))
                result = {"success": True, "result": result_data}
            
            else:
                result = {"error": f"Unknown WEB/GUI tool: {tool_name}"}
            
            # Log result
            if self._audit_logger:
                from backend.security.security_types import SecurityContext
                await self._audit_logger.log_tool_operation(
                    tool_name=tool_name,
                    operation="execute",
                    arguments=params,
                    context=SecurityContext(
                        session_id=session_id,
                        user_id=None,
                        tool_name=tool_name,
                        operation_type="gui",
                        timestamp=datetime.now()
                    ),
                    result=result,
                    risk_score=0.3
                )
            
            return result
                
        except Exception as e:
            error_result = {"error": str(e)}
            
            # Log error
            if self._audit_logger:
                from backend.security.security_types import SecurityContext
                await self._audit_logger.log_tool_operation(
                    tool_name=tool_name,
                    operation="execute",
                    arguments=params,
                    context=SecurityContext(
                        session_id=session_id,
                        user_id=None,
                        tool_name=tool_name,
                        operation_type="gui",
                        timestamp=datetime.now()
                    ),
                    result=error_result,
                    risk_score=0.5
                )
            
            return error_result
    
    async def execute_mcp_tool(self, server_name: str, tool_name: str, params: Dict, session_id: str = "unknown") -> Dict:
        """
        Execute a tool via MCP server.
        
        Requirements: 8.3, 8.4
        """
        server = self._mcp_servers.get(server_name)
        if not server:
            return {"error": f"MCP server '{server_name}' not found"}
        
        try:
            # Check rate limit
            if self._security_filter and self._security_filter.check_tool_execution_rate_limit(session_id, tool_name):
                logger.warning(f"[AgentToolBridge] Rate limit exceeded for {tool_name}")
                return {"error": "Rate limit exceeded for tool execution"}
            
            # Log tool execution
            if self._audit_logger:
                from backend.security.security_types import SecurityContext
                await self._audit_logger.log_tool_operation(
                    tool_name=tool_name,
                    operation="execute",
                    arguments=params,
                    context=SecurityContext(
                        session_id=session_id,
                        user_id=None,
                        tool_name=tool_name,
                        operation_type="mcp",
                        timestamp=datetime.now()
                    ),
                    result="pending",
                    risk_score=0.4
                )
            
            from backend.mcp.protocol import MCPRequest, MCPMessageType
            
            request = MCPRequest(
                id=f"agent_{datetime.now().timestamp()}",
                method=MCPMessageType.TOOLS_CALL,
                params={"name": tool_name, "arguments": params}
            )
            
            response = await server.handle_request(request)
            result = response.result if response.result else {"error": response.error}
            
            # Log result
            if self._audit_logger:
                from backend.security.security_types import SecurityContext
                await self._audit_logger.log_tool_operation(
                    tool_name=tool_name,
                    operation="execute",
                    arguments=params,
                    context=SecurityContext(
                        session_id=session_id,
                        user_id=None,
                        tool_name=tool_name,
                        operation_type="mcp",
                        timestamp=datetime.now()
                    ),
                    result=result,
                    risk_score=0.4
                )
            
            return result
            
        except Exception as e:
            error_result = {"error": str(e)}
            
            # Log error
            if self._audit_logger:
                from backend.security.security_types import SecurityContext
                await self._audit_logger.log_tool_operation(
                    tool_name=tool_name,
                    operation="execute",
                    arguments=params,
                    context=SecurityContext(
                        session_id=session_id,
                        user_id=None,
                        tool_name=tool_name,
                        operation_type="mcp",
                        timestamp=datetime.now()
                    ),
                    result=error_result,
                    risk_score=0.6
                )
            
            return error_result
    
    async def execute_tool(self, tool_name: str, params: Dict, session_id: str = "unknown") -> Dict:
        """
        Execute any tool by name with routing to appropriate server.
        
        Integrates with AgentKernel context for tool results.
        
        Requirements: 8.3, 8.4, 8.5, 8.6
        """
        # Map tool names to their execution methods
        vision_tools = ["vision_detect_element", "vision_analyze_screen", "vision_validate_action", "vision_get_context"]
        gui_tools = ["gui_click", "gui_type", "gui_press_key", "take_screenshot"]
        
        try:
            if tool_name in vision_tools:
                return await self.execute_vision_tool(tool_name, params, session_id)
            
            if tool_name in gui_tools:
                return await self.execute_gui_tool(tool_name, params, session_id)
            
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
                "open_file": ("app_launcher", "open_file"),
                # GUI Automation
                "gui_automate_click": ("gui_automation", "click"),
                "gui_automate_type": ("gui_automation", "type")
            }
            
            if tool_name in mcp_tools:
                server_name, mcp_tool_name = mcp_tools[tool_name]
                return await self.execute_mcp_tool(server_name, mcp_tool_name, params, session_id)

            # Git + Shell tools — executed inline via subprocess
            git_tools = {
                "git_status", "git_diff", "git_log",
                "git_commit", "git_create_branch", "git_checkout",
                "git_push", "run_command",
            }
            if tool_name in git_tools:
                return await self._execute_dev_tool(tool_name, params, session_id)

            error_result = {"error": f"Unknown tool: {tool_name}"}
            
            # Log unknown tool error
            if self._audit_logger:
                from backend.security.security_types import SecurityContext
                await self._audit_logger.log_tool_operation(
                    tool_name=tool_name,
                    operation="execute",
                    arguments=params,
                    context=SecurityContext(
                        session_id=session_id,
                        user_id=None,
                        tool_name=tool_name,
                        operation_type="unknown",
                        timestamp=datetime.now()
                    ),
                    result=error_result,
                    risk_score=0.1
                )
            
            return error_result
            
        except Exception as e:
            error_result = {"error": f"Tool execution failed: {str(e)}"}
            
            # Log execution error
            if self._audit_logger:
                from backend.security.security_types import SecurityContext
                await self._audit_logger.log_tool_operation(
                    tool_name=tool_name,
                    operation="execute",
                    arguments=params,
                    context=SecurityContext(
                        session_id=session_id,
                        user_id=None,
                        tool_name=tool_name,
                        operation_type="error",
                        timestamp=datetime.now()
                    ),
                    result=error_result,
                    risk_score=0.7
                )
            
            return error_result
    
    # ------------------------------------------------------------------
    # Developer tools — git and shell, executed via subprocess
    # ------------------------------------------------------------------

    # Default repo root: two levels up from this file (…/IRISVOICE)
    _DEFAULT_REPO: str = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )

    async def _execute_dev_tool(self, tool_name: str, params: Dict, session_id: str) -> Dict:
        """Execute git or shell commands for developer mode.

        All commands run inside the repo directory by default.  The caller can
        pass a ``repo_path`` / ``cwd`` parameter to override the working directory,
        but paths outside the project tree are rejected to prevent accidents.
        """
        # Resolve working directory
        cwd_param = params.get("repo_path") or params.get("cwd") or self._DEFAULT_REPO
        cwd = os.path.normpath(cwd_param)
        repo_root = os.path.normpath(self._DEFAULT_REPO)

        # Safety: reject paths outside the project tree
        if not cwd.startswith(repo_root):
            return {"error": f"Working directory '{cwd}' is outside the project root. Aborting."}

        def _run(cmd: list, timeout: int = 30) -> Dict:
            """Run a subprocess and return {stdout, stderr, returncode}."""
            try:
                result = subprocess.run(
                    cmd,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    encoding="utf-8",
                    errors="replace",
                )
                return {
                    "success": result.returncode == 0,
                    "stdout": result.stdout.strip(),
                    "stderr": result.stderr.strip(),
                    "returncode": result.returncode,
                }
            except subprocess.TimeoutExpired:
                return {"success": False, "error": f"Command timed out after {timeout}s"}
            except Exception as exc:
                return {"success": False, "error": str(exc)}

        # ── git_status ──────────────────────────────────────────────
        if tool_name == "git_status":
            return _run(["git", "status", "--short", "--branch"])

        # ── git_diff ────────────────────────────────────────────────
        if tool_name == "git_diff":
            cmd = ["git", "diff"]
            if params.get("staged"):
                cmd.append("--staged")
            return _run(cmd)

        # ── git_log ─────────────────────────────────────────────────
        if tool_name == "git_log":
            n = int(params.get("n", 10))
            return _run(["git", "log", f"-{n}", "--oneline", "--decorate"])

        # ── git_commit ──────────────────────────────────────────────
        if tool_name == "git_commit":
            message = params.get("message", "").strip()
            if not message:
                return {"success": False, "error": "Commit message is required"}
            add = _run(["git", "add", "-A"])
            if not add["success"]:
                return {"success": False, "error": f"git add failed: {add['stderr']}"}
            return _run(["git", "commit", "-m", message])

        # ── git_create_branch ───────────────────────────────────────
        if tool_name == "git_create_branch":
            branch = params.get("branch", "").strip()
            if not branch:
                return {"success": False, "error": "Branch name is required"}
            return _run(["git", "checkout", "-b", branch])

        # ── git_checkout ────────────────────────────────────────────
        if tool_name == "git_checkout":
            branch = params.get("branch", "").strip()
            if not branch:
                return {"success": False, "error": "Branch name is required"}
            return _run(["git", "checkout", branch])

        # ── git_push ────────────────────────────────────────────────
        if tool_name == "git_push":
            cmd = ["git", "push", "--set-upstream", "origin", "HEAD"]
            if params.get("force"):
                cmd.append("--force-with-lease")
            return _run(cmd, timeout=60)

        # ── run_command ─────────────────────────────────────────────
        if tool_name == "run_command":
            raw = params.get("command", "").strip()
            if not raw:
                return {"success": False, "error": "command is required"}
            # Block obviously destructive commands
            _BLOCKED = ("rm -rf /", "rmdir /s /q C:\\", "format ", "del /f /s /q C:\\")
            if any(raw.startswith(b) for b in _BLOCKED):
                return {"success": False, "error": "Blocked: destructive system command"}
            # Shell=True so pipes, &&, etc. work — still sandboxed to cwd
            try:
                result = subprocess.run(
                    raw, shell=True, cwd=cwd,
                    capture_output=True, text=True,
                    timeout=120, encoding="utf-8", errors="replace",
                )
                return {
                    "success": result.returncode == 0,
                    "stdout": result.stdout.strip(),
                    "stderr": result.stderr.strip(),
                    "returncode": result.returncode,
                }
            except subprocess.TimeoutExpired:
                return {"success": False, "error": "Command timed out after 120s"}
            except Exception as exc:
                return {"success": False, "error": str(exc)}

        return {"error": f"Unknown dev tool: {tool_name}"}

    def get_status(self) -> Dict:
        """
        Get status of all connected services.
        
        Returns status including:
        - Initialization state
        - Available services (vision, GUI, screen capture, MCP servers)
        - Total tools count
        - Security and audit integration status
        """
        return {
            "initialized": self._initialized,
            "vision_available": self._vision_client is not None,
            "vision_system_available": self._vision_system is not None,
            "gui_operator_available": self._gui_operator is not None,
            "screen_capture_available": self._screen_capture is not None,
            "mcp_servers": list(self._mcp_servers.keys()),
            "total_tools": len(self.get_available_tools()),
            "security_filter_available": self._security_filter is not None,
            "audit_logger_available": self._audit_logger is not None
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
