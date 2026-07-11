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


# Tools that reach OUTSIDE the app sandbox — they launch the user's real
# browser/apps, open files with the default application, lock the screen, or
# drive the GUI/screen.  These are gated by the app-wide desktop-control flag
# (agent_kernel.get_desktop_control_enabled); the agent can only use them when
# the user has explicitly granted desktop-control permission.  Web search
# (search / crawler_query) is NOT here — that is gated by the internet-access
# flag and stays fully in-app (headless crawl), never touching the desktop.
DESKTOP_CONTROL_TOOLS = frozenset({
    "open_url",          # launches the OS default browser
    "launch_app",        # launches an application
    "open_file",         # opens a file with its default app
    "lock_screen",       # locks the user's session
    "shutdown",          # shuts down the machine
    "restart",           # restarts the machine
    "gui_click",         # clicks at screen coordinates
    "gui_type",          # types at the current/coordinates
    "gui_press_key",     # presses a keyboard key
    "gui_automate_click",  # GUI automation click
    "gui_automate_type",   # GUI automation type
    "take_screenshot",   # captures the screen
    "start_screen_monitor",  # background screen monitoring
})


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
        self._gui_operator = None
        self._screen_capture = None
        self._screen_monitor = None
        self._mcp_servers = {}
        self._initialized = False

        # Security and audit integration (from task 9)
        self._security_filter = security_filter
        self._audit_logger = audit_logger

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
                logger.error(
                    f"[AgentToolBridge] SecurityFilter init failed: {e}")

        # Initialize AuditLogger if not provided
        if self._audit_logger is None:
            try:
                from backend.security.audit_logger import SecurityAuditLogger
                self._audit_logger = SecurityAuditLogger()
                logger.info("[AgentToolBridge] AuditLogger initialized")
            except Exception as e:
                logger.error(f"[AgentToolBridge] AuditLogger init failed: {e}")

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
                BrowserServer, AppLauncherServer, SystemServer, FileManagerServer,
                InternalCapabilityServer
            )
            from backend.mcp.gui_automation_server import GUIAutomationServer
            from backend.mcp.github_server import GitHubServer

            from backend.tools.vision_mcp_server import VisionMCPServer
            self._mcp_servers = {
                "browser": BrowserServer(),
                "app_launcher": AppLauncherServer(),
                "system": SystemServer(),
                "file_manager": FileManagerServer(),
                "gui_automation": GUIAutomationServer(),
                "internal": InternalCapabilityServer(),
                "vision": VisionMCPServer(),
                "github": GitHubServer(),
            }
            logger.info(
                f"[AgentToolBridge] MCP Servers: {list(self._mcp_servers.keys())}")

            # Option B: wire VisionGuidedOperator after both servers are ready
            # Kernel gates tasks; VisionGuidedOperator executes them fast
            try:
                from backend.agent.vision_guided_operator import VisionGuidedOperator
                self._vision_guided_operator = VisionGuidedOperator(
                    vision_server=self._mcp_servers.get("vision"),
                )
                # Wire native operator lazily — initialized on first use
                gui_server = self._mcp_servers.get("gui_automation")
                if gui_server and hasattr(gui_server, "set_vision_guided_operator"):
                    gui_server.set_vision_guided_operator(self._vision_guided_operator)
                logger.info("[AgentToolBridge] VisionGuidedOperator wired (Option B)")
            except Exception as ve:
                logger.warning(f"[AgentToolBridge] VisionGuidedOperator init skipped: {ve}")
                self._vision_guided_operator = None

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
            # Internal Capabilities
            {"name": "create_skill", "description": "Create a new learned skill", "parameters": {"name": {
                "type": "string"}, "content": {"type": "string"}}, "category": "system", "server": "internal"},

            # Browser
            {"name": "open_url", "description": "Open URL in browser", "parameters": {
                "url": {"type": "string"}}, "category": "web", "server": "browser"},

            # File Management
            {"name": "read_file", "description": "Read file contents", "parameters": {
                "path": {"type": "string"}}, "category": "file", "server": "file_manager"},
            {"name": "write_file", "description": "Write to file", "parameters": {"path": {
                "type": "string"}, "content": {"type": "string"}}, "category": "file", "server": "file_manager"},
            {"name": "list_directory", "description": "List directory", "parameters": {
                "path": {"type": "string"}}, "category": "file", "server": "file_manager"},
            {"name": "create_directory", "description": "Create directory", "parameters": {
                "path": {"type": "string"}}, "category": "file", "server": "file_manager"},
            {"name": "delete_file", "description": "Delete file/directory", "parameters": {
                "path": {"type": "string"}}, "category": "file", "server": "file_manager"},

            # System
            {"name": "get_system_info", "description": "Get system information",
                "parameters": {}, "category": "system", "server": "system"},
            {"name": "lock_screen", "description": "Lock the screen",
                "parameters": {}, "category": "system", "server": "system"},
            {"name": "shutdown", "description": "Shutdown system", "parameters": {"delay": {
                "type": "integer", "optional": True}}, "category": "system", "server": "system"},
            {"name": "restart", "description": "Restart system", "parameters": {"delay": {
                "type": "integer", "optional": True}}, "category": "system", "server": "system"},

            # App Launcher
            {"name": "launch_app", "description": "Launch an application", "parameters": {
                "app_name": {"type": "string"}}, "category": "app", "server": "app_launcher"},
            {"name": "open_file", "description": "Open file with default app", "parameters": {
                "file_path": {"type": "string"}}, "category": "app", "server": "app_launcher"},

            # GitHub (PAT-based)
            {"name": "github_get_user", "description": "Get authenticated GitHub user info",
                "parameters": {}, "category": "github", "server": "github"},
            {"name": "github_list_repos", "description": "List user's GitHub repositories",
                "parameters": {}, "category": "github", "server": "github"},
            {"name": "github_get_repo_branches", "description": "List branches for a GitHub repo",
                "parameters": {"repo_full_name": {"type": "string"}}, "category": "github", "server": "github"},
            {"name": "github_generate_ssh_key", "description": "Generate SSH key for GitHub",
                "parameters": {"name": {"type": "string"}, "key_type": {"type": "string"}}, "category": "github", "server": "github"},
            {"name": "github_list_ssh_keys", "description": "List generated SSH keys",
                "parameters": {}, "category": "github", "server": "github"},
            {"name": "github_delete_ssh_key", "description": "Delete a generated SSH key",
                "parameters": {"name": {"type": "string"}}, "category": "github", "server": "github"},
            {"name": "github_connect_pat", "description": "Connect to GitHub with a PAT",
                "parameters": {"token": {"type": "string"}}, "category": "github", "server": "github"},

            # GUI Automation
            {"name": "gui_automate_click", "description": "Automated GUI click", "parameters": {"x": {
                "type": "integer"}, "y": {"type": "integer"}}, "category": "gui", "server": "gui_automation"},
            {"name": "gui_automate_type", "description": "Automated GUI typing", "parameters": {
                "text": {"type": "string"}}, "category": "gui", "server": "gui_automation"},

            # Git — developer mode source control
            {"name": "git_status", "description": "Show working tree status (staged, unstaged, untracked files)", "parameters": {"repo_path": {
                "type": "string", "description": "Absolute path to the git repo (optional, defaults to IRISVOICE root)"}}, "category": "git"},
            {"name": "git_diff", "description": "Show diff of staged or unstaged changes", "parameters": {"repo_path": {"type": "string"},
                                                                                                          "staged": {"type": "boolean", "description": "If true, show staged diff; otherwise unstaged"}}, "category": "git"},
            {"name": "git_log", "description": "Show recent commit history", "parameters": {"repo_path": {"type": "string"}, "n": {
                "type": "integer", "description": "Number of commits to show (default 10)"}}, "category": "git"},
            {"name": "git_commit", "description": "Stage all changed files and create a commit", "parameters": {"message": {
                "type": "string", "description": "Commit message"}, "repo_path": {"type": "string"}}, "category": "git"},
            {"name": "git_create_branch", "description": "Create and switch to a new branch", "parameters": {"branch": {
                "type": "string", "description": "New branch name"}, "repo_path": {"type": "string"}}, "category": "git"},
            {"name": "git_checkout", "description": "Switch to an existing branch", "parameters": {
                "branch": {"type": "string"}, "repo_path": {"type": "string"}}, "category": "git"},
            {"name": "git_push", "description": "Push current branch to origin", "parameters": {"repo_path": {
                "type": "string"}, "force": {"type": "boolean", "description": "Force push (default false)"}}, "category": "git"},

            # Shell — developer mode command runner (sandboxed to repo directory)
            {"name": "run_command", "description": "Run a shell command in the project directory (npm, python, pytest, etc.)", "parameters": {"command": {
                "type": "string", "description": "Command to run"}, "cwd": {"type": "string", "description": "Working directory (defaults to IRISVOICE root)"}}, "category": "shell"},

            # Memory
            {
                "name": "recall_memory",
                "description": (
                    "Search long-term episodic memory for relevant past context, "
                    "solutions, or patterns. Use when you need prior knowledge for the current sub-task."
                ),
                "parameters": {"query": {"type": "string", "description": "What to search for"}},
                "category": "memory",
                "server": "internal",
            },

            # AutoResearch — general-purpose improvement loop
            {
                "name": "run_research",
                "description": (
                    "Run the AutoResearch improvement loop on anything — skills, behaviours, explanations, "
                    "processes, response styles, or any topic you want to get better at. "
                    "Use action='run_now' with topic+content to immediately research and improve any text or concept. "
                    "Use action='start' to begin the background timer loop (auto-picks the lowest-confidence stored item each cycle), "
                    "action='stop' to halt it, or action='status' to see recent results. "
                    "Examples: improve how IRIS handles Python debugging, improve a response template, improve a workflow."
                ),
                "parameters": {
                    "action": {"type": "string", "enum": ["run_now", "start", "stop", "status"], "description": "What to do"},
                    "topic": {"type": "string", "description": "What to improve — a short label like 'Python debugging' or 'response formatting'. Used with run_now."},
                    "content": {"type": "string", "description": "The current version of the text/concept to improve. If omitted, picks the lowest-confidence item from memory. Used with run_now."},
                    "test_prompts": {"type": "array", "items": {"type": "string"}, "description": "Optional: custom test prompts to benchmark variants against (only used with run_now)"},
                    "interval": {"type": "number", "description": "Optional: loop interval in seconds when using action=start (default 1800)"},
                },
                "category": "research",
            },
            {
                "name": "ask_user_question",
                "description": "Ask the user a question mid-task. Requires user input.",
                "parameters": {
                    "text": {"type": "string", "description": "The question to ask"},
                    "options": {"type": "array", "items": {"type": "string"}, "description": "Optional: multiple-choice options"},
                    "allow_other": {"type": "boolean", "description": "Allow free-form input (default: true)"}
                },
                "category": "system",
            },
            {
                "name": "speak",
                "description": (
                    "Speak text aloud via TTS. You may proactively call this at ANY time and for ANY "
                    "reason — to raise a concern, flag a risk, give feedback, ask for attention, or share "
                    "a status update — not only at the end of a task. Use it whenever the user should HEAR "
                    "something without reading. Fire-and-forget: returns immediately and never blocks. "
                    "Text is capped at 500 chars. The same spoken words are also delivered to any connected "
                    "external channels (e.g. Telegram) so the user hears you there too."
                ),
                "parameters": {
                    "text": {"type": "string", "description": "The text to speak (max 500 characters)"},
                    "priority": {"type": "string", "enum": ["normal", "high", "low"], "description": "Speech priority (default: normal)"},
                    "interrupt": {"type": "boolean", "description": "If true and priority is high, interrupt current TTS to speak immediately (default: false)"},
                },
                "category": "system",
            },
        ])

        # [13.3] Filter developer-only tools in personal mode
        from backend.capabilities import CapabilitySet
        blocked = CapabilitySet.allowed_tools()
        if blocked:
            tools = [t for t in tools if t.get("name") not in blocked]

        # ── Internet-access gate (plan Issue E) ─────────────────────────────
        # Web search / crawl tools are granted ONLY when the app-wide internet
        # access flag is ON (flipped by the UI web-mode toggle via
        # iris_gateway.set_web_mode). When OFF, the agent has zero internet
        # tools — it cannot reach the web at all.
        from backend.agent.agent_kernel import get_global_internet_access
        if get_global_internet_access():
            tools.extend([
                {
                    "name": "search",
                    "description": "Search the web for a quick factual answer. Returns fetched page content as markdown.",
                    "parameters": {"query": {"type": "string"}},
                    "category": "web",
                    "server": "browser",
                },
                {
                    "name": "crawler_query",
                    "description": (
                        "Deep web research crawl for a topic. Plans source URLs from the query, "
                        "crawls them with Crawl4AI, and returns a structured summary PLUS the full "
                        "extracted page content (field 'content') with source links. Put 'content' "
                        "in your 'show' field and 'summary' in 'speak'. Use for 'research', "
                        "'everything about', or 'deep dive' requests — NOT for a quick factual "
                        "lookup (use 'search' for that)."
                    ),
                    "parameters": {
                        "query": {"type": "string", "description": "The research topic or question to investigate"}
                    },
                    "category": "web",
                },
            ])

        # ── Desktop-control gate ─────────────────────────────────────────────
        # Tools that reach outside the app sandbox (launch the real browser/apps,
        # open files, drive the GUI/screen) are ONLY exposed when the user has
        # explicitly granted desktop-control permission.  OFF by default.
        from backend.agent.agent_kernel import get_desktop_control_enabled
        if not get_desktop_control_enabled():
            tools = [t for t in tools if t.get("name") not in DESKTOP_CONTROL_TOOLS]

        return tools

    # Tool Execution Methods

    async def execute_vision_tool(self, tool_name: str, params: Dict, session_id: str = "unknown") -> Dict:
        """
        Execute a vision-related tool.

        Requirements: 8.3, 8.4
        """
        if "vision" not in self._mcp_servers:
            return {"error": "Vision MCP server not initialized"}

        try:
            # Check rate limit
            if self._security_filter and self._security_filter.check_tool_execution_rate_limit(session_id, tool_name):
                logger.warning(
                    f"[AgentToolBridge] Rate limit exceeded for {tool_name}")
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
                # Route through VisionMCPServer (LFM2.5-VL)
                vision_server = self._mcp_servers.get("vision")
                if vision_server:
                    mcp_result = await vision_server.execute_tool(
                        "vision.describe_live_frame", {}
                    )
                    text = mcp_result.get("content", [{}])[0].get("text", "Vision unavailable")
                    result = {"success": True, "result": {"description": text}}
                else:
                    result = {"error": "Vision MCP server not available"}

            elif tool_name == "vision_detect_element":
                vision_server = self._mcp_servers.get("vision")
                if vision_server:
                    mcp_result = await vision_server.execute_tool(
                        "vision.find_ui_element",
                        {"element_description": params.get("description", "")}
                    )
                    text = mcp_result.get("content", [{}])[0].get("text", "Vision unavailable")
                    result = {"success": True, "result": text}
                else:
                    result = {"error": "Vision MCP server not available"}

            elif tool_name == "vision_analyze_screen":
                vision_server = self._mcp_servers.get("vision")
                if vision_server:
                    mcp_result = await vision_server.execute_tool(
                        "vision.analyze_screen",
                        {"question": params.get("question", "")}
                    )
                    text = mcp_result.get("content", [{}])[0].get("text", "Vision unavailable")
                    result = {"success": True, "result": text}
                else:
                    result = {"error": "Vision MCP server not available"}

            elif tool_name == "vision_validate_action":
                # Suggest action via vision tool (replaces deprecated validate_action)
                vision_server = self._mcp_servers.get("vision")
                if vision_server:
                    goal = f"{params.get('action', '')} {params.get('target', '')}".strip()
                    mcp_result = await vision_server.execute_tool(
                        "vision.suggest_next_action", {"goal": goal}
                    )
                    text = mcp_result.get("content", [{}])[0].get("text", "Vision unavailable")
                    result = {"success": True, "result": text}
                else:
                    result = {"error": "Vision MCP server not available"}

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
                logger.warning(
                    f"[AgentToolBridge] Rate limit exceeded for {tool_name}")
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
                logger.warning(
                    f"[AgentToolBridge] Rate limit exceeded for {tool_name}")
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
            result = response.result if response.result else {
                "error": response.error}

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

    async def _handle_ask_user_question(self, params: Dict, session_id: str) -> Dict:
        """Handle the ask_user_question tool — ask user, wait for answer.

        Expected params:
          text: The question to ask (required)
          options: List of multiple-choice options (optional)
          allow_other: Whether to allow free-form input (optional, default True)

        Returns the user's answer or {"timeout": True} on timeout.
        """
        try:
            from backend.agent.tools.ask_user_tool import get_ask_user_tool

            tool = get_ask_user_tool()
            text = params.get("text", "")
            if not text:
                return {"success": False, "error": "Question text is required"}

            question = tool.ask(
                text=text,
                options=params.get("options"),
                allow_other=params.get("allow_other", True),
                turn_id=session_id,
            )

            # Wait for answer (this blocks until user responds or timeout)
            resolved = tool.wait_for_answer(question)

            if resolved.status == "answered":
                return {
                    "success": True,
                    "answer": resolved.answer,
                    "question_id": resolved.question_id,
                }
            elif resolved.status == "timed_out":
                return {
                    "success": False,
                    "timeout": True,
                    "error": "User did not respond in time",
                    "question_id": resolved.question_id,
                }
            return {"success": False, "error": "Unknown question status"}

        except Exception as exc:
            logger.warning("[ToolBridge] ask_user_question failed: %s", exc)
            return {"success": False, "error": str(exc)}

    def _handle_speak(self, params: Dict, session_id: str) -> Dict:
        """Handle the speak tool — fire-and-forget TTS speech.

        The speak tool never blocks: it emits an utterance event and returns
        immediately.  Speech is best-effort (TTS may be unavailable).
        """
        try:
            from backend.agent.tools.speak_tool import get_speak_tool

            tool = get_speak_tool()
            text = params.get("text", "")
            priority = params.get("priority", "normal")
            interrupt = bool(params.get("interrupt", False))
            result = tool.speak(text=text, priority=priority, interrupt=interrupt)
            logger.info(
                "[ToolBridge] speak: status=%s text=%s",
                result.get("status"),
                str(text)[:40],
            )
            return result
        except Exception as exc:
            logger.warning("[ToolBridge] speak failed: %s", exc)
            return {"status": "error", "reason": str(exc)}

    async def execute_tool(self, tool_name: str, params: Dict, session_id: str = "unknown", plan_title: str = "") -> Dict:
        """
        Execute any tool by name with routing to appropriate server.

        Integrates with AgentKernel context for tool results.  ``plan_title``
        (set by the DER planner) is threaded into memory events so tool executions
        are recallable by plan context in the Immortus thread.

        Requirements: 8.3, 8.4, 8.5, 8.6
        """
        # [13.3] Runtime capability gate
        from backend.capabilities import CapabilitySet
        if not CapabilitySet.is_tool_allowed(tool_name):
            logger.warning(
                "[13.3] Tool '%s' blocked in '%s' mode", tool_name, CapabilitySet.get_mode()
            )
            return {
                "error": f"Tool '{tool_name}' is not available in {CapabilitySet.get_mode()} mode",
                "success": False,
            }

        # ── Internet-access gate (plan Issue E) ──────────────────────────────
        # Defense-in-depth: even if a web tool is somehow invoked while internet
        # access is OFF, reject it here. The UI web-mode toggle flips the global
        # flag via iris_gateway.set_web_mode.
        if tool_name in ("search", "crawler_query"):
            from backend.agent.agent_kernel import get_global_internet_access
            if not get_global_internet_access():
                logger.warning(
                    "[InternetGate] Tool '%s' blocked — internet access disabled", tool_name
                )
                return {
                    "success": False,
                    "error": (
                        f"Internet access is disabled (web mode off). "
                        f"Tool '{tool_name}' is unavailable."
                    ),
                }

        # ── Desktop-control gate (defense-in-depth) ─────────────────────────
        # Even if a desktop-control tool is somehow invoked while desktop control
        # is OFF, reject it here. The UI desktop_control card flips the flag via
        # iris_gateway.set_desktop_control_enabled; it is OFF by default.
        if tool_name in DESKTOP_CONTROL_TOOLS:
            from backend.agent.agent_kernel import get_desktop_control_enabled
            if not get_desktop_control_enabled():
                logger.warning(
                    "[DesktopGate] Tool '%s' blocked — desktop control disabled", tool_name
                )
                return {
                    "success": False,
                    "error": (
                        f"Desktop control is disabled. Tool '{tool_name}' "
                        f"requires explicit desktop-control permission."
                    ),
                }

        # ── Phase 4: Permission check ──────────────────────────────────────
        try:
            from backend.agent.permissions import (
                classify_tool,
                get_permission_action,
                get_permission_system,
                PermissionTier,
            )

            tier = classify_tool(tool_name, params)
            level = CapabilitySet.get_mode()
            action = get_permission_action(tier, level)

            if action.value in ("require_approval", "require_confirmation"):
                perm_system = get_permission_system()
                req = perm_system.request_permission(
                    tool_name=tool_name,
                    tier=tier,
                    params=params,
                    description=(
                        f"Execute '{tool_name}' with {len(params)} params"
                    ),
                    level=level,
                )

                if req.status == "pending":
                    # Wait for user response (async)
                    resolved = await perm_system.get_response_async(req)
                    if resolved.status == "denied":
                        return {
                            "success": False,
                            "error": f"Permission denied for tool '{tool_name}'",
                            "permission_response": "denied",
                        }
                    if resolved.status == "timed_out":
                        return {
                            "success": False,
                            "error": f"Permission timed out for tool '{tool_name}'",
                            "permission_response": "timed_out",
                        }
                    # approved — continue
        except Exception:
            logger.warning("[Permissions] Permission check failed — allowing tool to proceed", exc_info=True)

        # ── Live task progress (generic, ALL tools) ──────────────────────────
        # Emit a task:progress so the frontend ContextPill + plan card show what
        # the agent is doing for ANY tool. A task can start as a simple widget
        # action and evolve into a web search, so this must not be crawler-
        # specific. The crawler adds finer per-page granularity via its own
        # task:progress emissions (update_step=True) during the crawl.
        if tool_name not in ("speak", "ask_user_question"):
            try:
                from backend.agent.event_bus import get_event_bus, IRISStreamEvent

                _label = self._tool_action_label(tool_name, params)
                get_event_bus().emit(
                    IRISStreamEvent.TASK_PROGRESS,
                    data={"description": _label, "action": _label, "plan_title": plan_title},
                    session_id=session_id,
                )
            except Exception:
                pass  # never block tool execution on an event emit failure

        # Map tool names to their execution methods
        vision_tools = ["vision_detect_element", "vision_analyze_screen",
                        "vision_validate_action", "vision_get_context"]
        gui_tools = ["gui_click", "gui_type",
                     "gui_press_key", "take_screenshot"]

        try:
            # Internal tools (handled here)
            internal_tools = ["ask_user_question", "speak"]

            if tool_name in internal_tools:
                if tool_name == "ask_user_question":
                    return await self._handle_ask_user_question(params, session_id)
                if tool_name == "speak":
                    return self._handle_speak(params, session_id)

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
                "gui_automate_type": ("gui_automation", "type"),
                # GitHub
                "github_get_user": ("github", "github_get_user"),
                "github_list_repos": ("github", "github_list_repos"),
                "github_get_repo_branches": ("github", "github_get_repo_branches"),
                "github_generate_ssh_key": ("github", "github_generate_ssh_key"),
                "github_list_ssh_keys": ("github", "github_list_ssh_keys"),
                "github_delete_ssh_key": ("github", "github_delete_ssh_key"),
                "github_connect_pat": ("github", "github_connect_pat"),
                # Internal (handled below with post-broadcast)
            }

            # ── In-app web search (replaces desktop-browser launch) ──────────
            # The old BrowserServer.search called webbrowser.open() and popped the
            # user's REAL desktop browser.  Web search is now fully in-app: the
            # headless Crawl4AI engine fetches the results and returns markdown.
            # Gated by the internet-access flag (see InternetGate above).  Routed
            # here BEFORE the MCP dispatch so it never reaches BrowserServer.
            if tool_name == "search":
                result = await self._execute_web_search(params, session_id)
                self._record_tool_event(
                    session_id, tool_name,
                    "success" if result.get("success") else "failure", params, result,
                    plan_title=plan_title,
                )
                return result

            if tool_name in mcp_tools:
                server_name, mcp_tool_name = mcp_tools[tool_name]
                result = await self.execute_mcp_tool(server_name, mcp_tool_name, params, session_id)

                # After agent creates a skill, broadcast to the frontend so UI updates immediately.
                # MUST use run_coroutine_threadsafe — this runs in a background thread, not the event loop.
                # ensure_future() would raise RuntimeError here and be swallowed silently.
                if tool_name == "create_skill" and result.get("success"):
                    try:
                        from backend.iris_gateway import get_iris_gateway
                        import asyncio as _asyncio
                        gw = get_iris_gateway()
                        loop = gw._main_loop
                        if gw._ws_manager and loop and loop.is_running():
                            _asyncio.run_coroutine_threadsafe(
                                gw._ws_manager.broadcast_to_session(session_id, {
                                    "type": "skills_reloaded",
                                    "payload": {"source": "agent_create_skill"}
                                }),
                                loop
                            )
                            logger.info(f"[ToolBridge] Broadcast skills_reloaded for session {session_id}")
                    except Exception as _e:
                        logger.warning(f"[ToolBridge] skills_reloaded broadcast failed: {_e}")

                self._record_tool_event(session_id, tool_name, "success", params, result, plan_title=plan_title)
                return result

            # Git + Shell tools — executed inline via subprocess
            git_tools = {
                "git_status", "git_diff", "git_log",
                "git_commit", "git_create_branch", "git_checkout",
                "git_push", "run_command",
            }
            if tool_name in git_tools:
                result = await self._execute_dev_tool(tool_name, params, session_id)
                self._record_tool_event(session_id, tool_name, "success" if result.get("success") else "failure", params, result, plan_title=plan_title)
                return result

            if tool_name == "recall_memory":
                query = params.get("query", "")
                _retrieval_limit = 5
                _retrieval_score = 0.40
                try:
                    from backend.gateway.iris_ffi import ffi_calculate_eml
                    _eml, _ex, _ey = ffi_calculate_eml(session_id)
                    if _eml < 1.00 and _ey >= 0.70:
                        _retrieval_limit = 3
                        _retrieval_score = 0.65
                except Exception:
                    pass
                results = []
                if self._memory_interface and hasattr(self._memory_interface, "episodic"):
                    results = self._memory_interface.episodic.retrieve_similar(
                        task=query, limit=_retrieval_limit, min_score=_retrieval_score
                    ) or []
                return {"success": True, "results": results}

            if tool_name == "run_research":
                result = await self._execute_research_tool(params, session_id)
                self._record_tool_event(session_id, tool_name, "success" if result.get("success") else "failure", params, result, plan_title=plan_title)
                return result

            if tool_name == "crawler_query":
                result = await self._execute_crawler_query(params, session_id)
                self._record_tool_event(session_id, tool_name, "success" if result.get("success") else "failure", params, result, plan_title=plan_title)
                return result

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

            self._record_tool_event(session_id, tool_name, "failure", params, error_result, plan_title=plan_title)
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

            # FFI auto-record: tool execution failure
            self._record_tool_event(session_id, tool_name, "failure", params, error_result, plan_title=plan_title)

            return error_result

    def _record_tool_event(
        self, session_id: str, tool_name: str, outcome: str,
        params: Dict, result: Dict, plan_title: str = ""
    ) -> None:
        """
        Record a tool execution event via the C++ core FFI bridge.
        Fire-and-forget: never blocks the tool execution path.
        ``plan_title`` (set by the DER planner) is threaded into the event
        payload so tool executions are recallable by plan context.
        """
        try:
            from backend.gateway.iris_ffi import ffi_ingest_event
            payload = json.dumps({
                "tool": tool_name,
                "params": params,
                "result": result,
                "plan_title": plan_title,
            })
            ffi_ingest_event(
                session_id=session_id,
                domain="SYSTEM",
                event_type="tool_execution",
                actor="agent_tool_bridge",
                outcome=outcome,
                summary=f"Tool {tool_name} executed: {outcome}",
                payload_json=payload
            )
        except Exception:
            pass  # Never block tool execution on recording failure

    def _tool_action_label(self, tool_name: str, params: Dict) -> str:
        """Human-readable one-line label for a tool, used for live task progress.

        Kept concise so it fits the ContextPill. Covers every tool the agent
        can call — a task may begin as a simple widget action and evolve into
        a web search, so the label must be generic, not crawler-specific.
        """
        p = params or {}

        def _base(key: str) -> str:
            _p = p.get(key) or p.get("file_path") or p.get("path") or "file"
            return os.path.basename(str(_p)) if _p else "file"

        if tool_name in ("crawler_query", "search", "web_search"):
            return f"Searching the web: {str(p.get('query', ''))[:60]}"
        if tool_name in ("write_file", "edit_file", "create_file"):
            return f"Editing {_base('path')}"
        if tool_name == "read_file":
            return f"Reading {_base('path')}"
        if tool_name in ("open_url", "browser_navigate"):
            return f"Opening {str(p.get('url', ''))[:60]}"
        if tool_name in ("run_command", "execute_command", "shell", "dev_cli"):
            return f"Running: {str(p.get('command', p.get('query', '')))[:60]}"
        if tool_name in ("list_directory", "create_directory"):
            return f"Browsing {_base('path')}"
        if tool_name.startswith("github_"):
            return f"GitHub: {tool_name[7:]}"
        if tool_name.startswith("gui_") or tool_name.startswith("vision_"):
            return f"Controlling UI: {tool_name}"
        return f"Using {tool_name}"

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
        cwd_param = params.get("repo_path") or params.get(
            "cwd") or self._DEFAULT_REPO
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
            _BLOCKED = ("rm -rf /", "rmdir /s /q C:\\",
                        "format ", "del /f /s /q C:\\")
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

    async def _execute_research_tool(self, params: Dict, session_id: str) -> Dict:
        """Handle the run_research agent tool — delegates to AutoResearchRunner."""
        action = params.get("action", "status")
        try:
            from backend.agent.auto_research import get_auto_research_runner
            runner = get_auto_research_runner()
        except Exception as exc:
            return {"success": False, "error": f"AutoResearch runner not available: {exc}"}

        if action == "status":
            return {"success": True, **runner.get_status()}

        if action == "start":
            interval = params.get("interval")
            if interval is not None:
                try:
                    runner._interval = float(interval)
                except (TypeError, ValueError):
                    pass
            runner.start()
            return {"success": True, "message": f"AutoResearch loop started (interval={runner._interval}s)"}

        if action == "stop":
            runner.stop()
            return {"success": True, "message": "AutoResearch loop stop requested"}

        if action == "run_now":
            topic = params.get("topic")
            content = params.get("content")
            test_prompts = params.get("test_prompts")

            # Temporarily override benchmark prompts if caller supplied custom ones
            _orig_prompts = None
            if test_prompts and isinstance(test_prompts, list) and test_prompts:
                from backend.agent import auto_research as _ar_mod
                _orig_prompts = _ar_mod.BENCHMARK_PROMPTS
                _ar_mod.BENCHMARK_PROMPTS = test_prompts

            # Build an override candidate when topic/content are provided directly
            override_candidate = None
            if topic:
                override_candidate = {
                    "name": topic,
                    "description": content or topic,
                    "score": 0.5,
                    "_key": "",
                    "_category": "research_topics",
                }

            try:
                asyncio.create_task(runner._run_cycle(
                    override_candidate=override_candidate))
                parts = ["Research cycle triggered"]
                if topic:
                    parts.append(f"topic='{topic}'")
                if test_prompts:
                    parts.append(f"{len(test_prompts)} custom prompt(s)")
                return {"success": True, "message": " — ".join(parts)}
            finally:
                if _orig_prompts is not None:
                    from backend.agent import auto_research as _ar_mod
                    _ar_mod.BENCHMARK_PROMPTS = _orig_prompts

        return {"success": False, "error": f"Unknown action: {action}"}

    async def _execute_crawler_query(self, params: Dict, session_id: str) -> Dict:
        """Agent tool: deep web research crawl (plan -> crawl -> extract).

        Distinct from the lightweight ``search`` tool: this plans source URLs
        from the query, crawls them with Crawl4AI, and extracts a structured
        summary + source links. The agent turns the result into a
        ``{speak, show}`` response. Trust is threaded automatically because
        ``crawler_query`` is in ``pacman_fragment._EXTERNAL_TOOLS`` (untrusted /
        reference zone) — see plan §6.1.

        NOTE (§6.4, follow-up): progress ``speak`` calls during the crawl ARE
        wired via the ``on_page_done`` callback below — the agent (and the user,
        via TTS) hears "Researching — fetched page N of M" as pages come in.
        The final summary is spoken by the agent's own ``speak`` tool after this
        returns.
        """
        query = (params.get("query") or "").strip()
        if not query:
            return {"success": False, "error": "crawler_query requires a 'query'"}

        try:
            from backend.crawler.crawler_engine import CrawlerEngine, CrawlerUnavailable
            from backend.crawler.crawl_planner import get_crawl_planner
            from backend.crawler.data_extractor import get_data_extractor
        except Exception as exc:
            return {"success": False, "error": f"crawler modules unavailable: {exc}"}

        # Step 1: Plan source URLs + extraction instructions.
        try:
            plan = await get_crawl_planner().plan(query)
        except Exception as exc:
            logger.error("[crawler_query] planning failed: %s", exc)
            return {"success": False, "error": f"planning failed: {exc}"}

        # Step 2: Crawl.
        try:
            # Progress utterances: let the user hear that research is happening
            # (Issue E follow-up — user reported no utterance while searching).
            # The speak tool is fire-and-forget and rate-limited; if the audio
            # pipeline is closed it is buffered/suppressed by ConversationKernel.
            from backend.agent.tools.speak_tool import get_speak_tool
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            _speak_tool = get_speak_tool()
            _bus = get_event_bus()

            # Flip the orb / ContextPill phase to "processing_tool" (SEARCHING)
            # so the user sees the assistant is actively researching, not just
            # "processing my STT". Bridged to the frontend via WSEventBridge.
            try:
                _bus.emit(
                    IRISStreamEvent.LISTENING_STATE,
                    data={"state": "processing_tool"},
                    session_id=session_id,
                )
            except Exception:
                pass  # never block the crawl on an event emit failure

            def _on_page_done(url: str, page_number: int, total: int) -> None:
                try:
                    _speak_tool.speak(
                        f"Researching — fetched page {page_number} of {total}.",
                        priority="low",
                    )
                except Exception as _spk_exc:  # pragma: no cover - best effort
                    logger.debug("[crawler_query] progress speak failed: %s", _spk_exc)
                # Live step feed: update the current working plan step + the
                # ContextPill action text with the site being read. The frontend
                # (useTaskProgress) maps this onto the in-progress step so the
                # plan card shows "Reading <host> (N/M)" as pages arrive.
                try:
                    from urllib.parse import urlparse

                    _host = urlparse(url or "").netloc or "source"
                    _bus.emit(
                        IRISStreamEvent.TASK_PROGRESS,
                        data={
                            "description": f"Reading {_host} ({page_number}/{total})",
                            "action": f"Reading {_host} ({page_number}/{total})",
                            # Rewrite the in-progress plan step text so the card
                            # shows the site being read live (not just the pill).
                            "update_step": True,
                        },
                        session_id=session_id,
                    )
                except Exception:
                    pass  # never block the crawl on an event emit failure

            async with CrawlerEngine() as engine:
                crawl_result = await engine.crawl(
                    query=query,
                    urls=plan.urls,
                    instructions=plan.instructions,
                    on_page_done=_on_page_done,
                )

            # Crawl finished — return the phase to "thinking" so the orb reflects
            # the agent summarising (the DER loop drives speaking next).
            try:
                _bus.emit(
                    IRISStreamEvent.LISTENING_STATE,
                    data={"state": "processing_conversation"},
                    session_id=session_id,
                )
            except Exception:
                pass  # never block on an event emit failure
        except CrawlerUnavailable as exc:
            # If we flipped the orb to processing_tool before the failure,
            # return it to processing_conversation so the UI doesn't stay stuck.
            if '_bus' in locals():
                try:
                    _bus.emit(IRISStreamEvent.LISTENING_STATE, data={"state": "processing_conversation"}, session_id=session_id)
                except Exception:
                    pass
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.error("[crawler_query] crawl failed: %s", exc)
            if '_bus' in locals():
                try:
                    _bus.emit(IRISStreamEvent.LISTENING_STATE, data={"state": "processing_conversation"}, session_id=session_id)
                except Exception:
                    pass
            return {"success": False, "error": f"crawl failed: {exc}"}

        # Step 3: Extract structured DashboardData.
        try:
            dashboard_data = await get_data_extractor().extract(
                result=crawl_result,
                instructions=plan.instructions,
                result_type=plan.result_type,
                title=plan.title,
            )
        except Exception as exc:
            logger.error("[crawler_query] extraction failed: %s", exc)
            return {"success": False, "error": f"extraction failed: {exc}"}

        pages: List[Dict[str, str]] = []
        for p in dashboard_data.get("pages", []):
            if isinstance(p, dict):
                pages.append({"url": p.get("url", ""), "title": p.get("title", "")})
            else:
                pages.append({"url": getattr(p, "url", ""), "title": getattr(p, "title", "")})

        # Reconstruct the full extracted content (combined markdown) from the
        # crawled pages so the agent can surface it in the `show` field. The
        # DataExtractor uses this same source to build its LLM prompt but does
        # not return it — so we rebuild it here (capped to match context limits).
        _CONTENT_CAP = 12_000
        _content_parts: List[str] = []
        for _p in getattr(crawl_result, "pages", []):
            _err = getattr(_p, "error", None)
            if _err:
                continue
            _md = getattr(_p, "markdown", "") or ""
            if _md:
                _content_parts.append(f"--- Source: {getattr(_p, 'url', '')} ---\n{_md}")
        _combined = "\n\n".join(_content_parts)
        if len(_combined) > _CONTENT_CAP:
            _combined = _combined[:_CONTENT_CAP] + "\n\n[...truncated...]"

        return {
            "success": True,
            "query": query,
            "title": dashboard_data.get("title", plan.title),
            "summary": dashboard_data.get("summary", ""),
            "content": _combined,
            "pages": pages,
            "links": [pg["url"] for pg in pages if pg.get("url")],
            "trust": "untrusted",  # external tool result — route to reference zone
        }

    async def _execute_web_search(self, params: Dict, session_id: str) -> Dict:
        """Agent tool: quick in-app web search (headless crawl of results).

        Replaces the old ``BrowserServer.search`` which called
        ``webbrowser.open()`` and launched the user's DESKTOP browser.  Web
        search is now fully in-app: the headless Crawl4AI engine fetches the
        search results page and returns the markdown.  Gated by the global
        internet-access flag (see the InternetGate block in execute_tool), so it
        is only reachable when web mode is ON.  Never touches the desktop.
        """
        query = (params.get("query") or "").strip()
        if not query:
            return {"success": False, "error": "search requires a 'query'"}

        try:
            from backend.crawler.crawler_engine import CrawlerEngine, CrawlerUnavailable
        except Exception as exc:
            return {"success": False, "error": f"crawler modules unavailable: {exc}"}

        search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        try:
            async with CrawlerEngine() as engine:
                crawl_result = await engine.crawl(
                    query=query,
                    urls=[search_url],
                    instructions=(
                        "Extract the most relevant answer and key facts from the "
                        "search results page. Prefer concise factual snippets."
                    ),
                )
        except CrawlerUnavailable as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.error("[web_search] crawl failed: %s", exc)
            return {"success": False, "error": f"search failed: {exc}"}

        # Rebuild markdown content from the crawled page(s).
        _CONTENT_CAP = 8_000
        _content_parts: List[str] = []
        for _p in getattr(crawl_result, "pages", []):
            if getattr(_p, "error", None):
                continue
            _md = getattr(_p, "markdown", "") or ""
            if _md:
                _content_parts.append(f"--- Source: {getattr(_p, 'url', '')} ---\n{_md}")
        _combined = "\n\n".join(_content_parts)
        if len(_combined) > _CONTENT_CAP:
            _combined = _combined[:_CONTENT_CAP] + "\n\n[...truncated...]"

        return {
            "success": True,
            "query": query,
            "content": _combined,
            "url": search_url,
            "trust": "untrusted",  # external tool result — route to reference zone
        }

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
            "vision_available": "vision" in self._mcp_servers,
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
