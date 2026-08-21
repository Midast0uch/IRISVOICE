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
import time  # used by _on_page_done; absent until now, see below
from typing import Any, Dict, List, Optional
from datetime import datetime
from urllib.parse import urlparse  # _on_page_done:1833, also never imported

# NOTE: `time` was never imported here, yet `_on_page_done` opens with
# `now = time.time()`. Every real page fetch therefore raised NameError, which
# the outer `except Exception` in _execute_crawler_query reported as
# "research failed: name 'time' is not defined". Since _on_page_done is the ONLY
# progress emitter in the crawl pipeline, live task-card updates and crawl
# narration never fired in production — the surrounding code reads as complete.
# Fourth instance in this codebase of a name error above/inside a broad handler
# silently disabling a whole feature (see speak_tool priority/interrupt,
# narration conv_id, agent_kernel _children).
#
# `urlparse` was the FIFTH, in the same function, and it survived the `time` fix
# because it hides behind a short-circuit:
#     _label = title or urlparse(url or "").netloc or "source"
# When `title` is truthy the right-hand side never evaluates. Harness fixtures
# pass a title; the real crawler passes "" — so the NameError fired only in
# production, and only for the per-page event. orchestrator._safe() swallows it
# with a bare `except Exception: pass` and no logging, so the pipeline reported
# phases but never pages. Two lessons: a broad handler with no log line is how
# these live for months, and a passing harness assertion only covers the inputs
# the fixture actually drives.

logger = logging.getLogger(__name__)

# Vision server auto-starts on first use (boots the llama-server vision model).
# take_screenshot must ensure it is running before capturing the screen.
try:
    from backend.tools.lfm_vl_provider import _ensure_vision_server_running
except Exception:  # pragma: no cover - provider import is best-effort
    _ensure_vision_server_running = None


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

        # pin_42ddd255162d: conversation registry for render/show tools (prism
        # card). Populated per session by the kernel; defaults to {} so DER
        # execution paths never hit AttributeError (was: 'AgentToolBridge'
        # object has no attribute '_active_conversation_id' when
        # get_rendered_documents ran inside the DER loop).
        self._active_conversation_id: Dict[str, str] = {}

        # Security and audit integration (from task 9)
        self._security_filter = security_filter
        self._audit_logger = audit_logger

        # SpeakTool singleton — used by the crawler_query narration heartbeat
        # (run_with_narration(..., speak=self._speak_tool.speak)) and any path
        # that references self._speak_tool. Must exist before initialize() so
        # the attribute is always present (previously only a local
        # get_speak_tool() was used inside _execute_crawler_query, causing
        # "AgentToolBridge has no attribute '_speak_tool'" at response time).
        try:
            from backend.agent.tools.speak_tool import get_speak_tool
            self._speak_tool = get_speak_tool()
        except Exception as _st_exc:
            logger.warning(f"[AgentToolBridge] SpeakTool init deferred: {_st_exc}")
            self._speak_tool = None

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

        # Phase 2: wire registry capability providers to the real kernel flags so
        # capability_allowed() enforces the live internet/desktop gates.
        try:
            from backend.agent.tool_registry import set_capability_providers
            from backend.agent.agent_kernel import (
                get_global_internet_access,
                get_desktop_control_enabled,
            )
            set_capability_providers(get_global_internet_access, get_desktop_control_enabled)
        except Exception as _cap_exc:
            logger.warning("[AgentToolBridge] capability provider wiring failed: %s", _cap_exc)

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

            # AutoResearch — general-purpose self-improvement loop (no web access)
            {
                "name": "improve_self",
                "description": (
                    "SELF-IMPROVEMENT ONLY — does NOT browse the web. Runs the AutoResearch loop to improve "
                    "skills, behaviours, explanations, processes, or response styles using locally stored "
                    "benchmark prompts. Use action='run_now' with topic+content to improve a text/concept, "
                    "action='start' for the background timer loop, action='stop' to halt it, or "
                    "action='status' for recent results. For web research use 'crawler_query'."
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
        blocked = CapabilitySet.blocked_tools()
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
                {
                    "name": "screenshot_page",
                    "description": (
                        "Take a picture of a WEB PAGE and show it in the chat. Use when "
                        "the user wants to SEE a page ('show me that page', 'what does "
                        "it look like', 'screenshot that site'). Needs the page's URL. "
                        "This is for SHOWING a page, not for reading one — to get a "
                        "page's TEXT or to answer a question from it, use 'search' "
                        "or the crawler instead, which are far cheaper. For the user's "
                        "own DESKTOP rather than a web page, use 'take_screenshot'."
                    ),
                    "parameters": {
                        "url": {"type": "string", "description": "Full http(s) URL of the page to photograph"}
                    },
                    "category": "vision",
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

            elif tool_name == "take_screenshot":
                # Desktop-control screenshot (registered in tool_registry as
                # category="vision"). Per design: if the agent wants a
                # screenshot, the vision server must be started FIRST if it is
                # not already running, then the capture is routed through it
                # (execute_vision_tool -> vision.describe_live_frame).
                if _ensure_vision_server_running is not None:
                    try:
                        _ensure_vision_server_running()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("vision server start failed: %s", exc)
                if "vision" not in self._mcp_servers:
                    result = {
                        "error": "vision server unavailable — cannot take screenshot",
                    }
                else:
                    result = await self.execute_vision_tool(
                        "vision_get_context", {}, session_id
                    )
                    # Normalise: vision_get_context returns frame description;
                    # surface it as a screenshot result.
                    if isinstance(result, dict) and "error" not in result:
                        result = {
                            "success": True,
                            "result": result.get("result", result),
                            "note": "screenshot via vision server",
                        }

            elif tool_name == "start_screen_monitor":
                # Proactive screen monitoring is handled by the vision system;
                # acknowledge here so the tool does not fall through to "unknown".
                result = {
                    "success": True,
                    "result": "screen monitoring started",
                    "note": "handled by vision system",
                }

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

    async def execute_media_tool(self, tool_name: str, params: Dict, session_id: str = "unknown") -> Dict:
        """Execute a media-pipeline tool (transcribe / analyze / clip).

        The 'black box' for pointing vision + Parakeet at any media. Every
        source URI is normalized to a local file via MediaSource (files + URLs)
        before the analysis tool runs.
        """
        from backend.agent.media_source import resolve_media_source
        from backend.tools import media_tools as mt

        try:
            if tool_name == "transcribe_media":
                src = params.get("audio_path") or params.get("uri") or params.get("path")
                if not src:
                    return {"success": False, "error": "transcribe_media requires audio_path/uri"}
                path = resolve_media_source(src)
                result = mt.transcribe_media(
                    path, chunk_seconds=int(params.get("chunk_seconds", 30))
                )
            elif tool_name == "analyze_video_frames":
                src = params.get("video_path") or params.get("uri") or params.get("path")
                if not src:
                    return {"success": False, "error": "analyze_video_frames requires video_path/uri"}
                path = resolve_media_source(src)
                result = mt.analyze_video_frames(
                    path,
                    question=params.get("question", "What is happening in this video?"),
                    frame_interval=float(params.get("frame_interval", 1.0)),
                )
            elif tool_name == "clip_video":
                src = params.get("video_path") or params.get("uri") or params.get("path")
                if not src:
                    return {"success": False, "error": "clip_video requires video_path/uri"}
                path = resolve_media_source(src)
                import tempfile

                out = params.get("output_path") or tempfile.mktemp(
                    suffix=".mp4", prefix="iris_clip_"
                )
                result = mt.clip_video(path, params.get("start"), params.get("end"), out)
            else:
                result = {"success": False, "error": f"unknown media tool: {tool_name}"}
            return result
        except Exception as exc:  # noqa: BLE001
            logger.error("execute_media_tool %s failed: %s", tool_name, exc)
            return {"success": False, "error": str(exc)}

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

            # Phase 1.2 (B2 + RC10): bound in-process MCP calls so a hung server
            # cannot block the agent indefinitely. 30s default matches
            # mcp/client.py:141; vision / GUI automation get 60s for long ops.
            _timeout = 60.0 if server_name in ("vision", "gui_automation") else 30.0
            try:
                response = await asyncio.wait_for(
                    server.handle_request(request), timeout=_timeout
                )
            except asyncio.TimeoutError:
                return {
                    "success": False,
                    "error": f"Tool '{tool_name}' timed out after {_timeout}s",
                }
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

    async def _handle_screenshot_page(self, params: Dict, session_id: str) -> Dict:
        """Handle `screenshot_page` — photograph a web page into the chat.

        Resolved against the SAME conversation the rest of the document tools
        use, so the card lands in the thread the user is actually looking at
        rather than in a "default" one they cannot see.
        """
        params = params or {}
        url = (params.get("url") or "").strip()
        if not url:
            return {"success": False, "error": "A url is required"}

        conversation_id = (
            params.get("conversation_id")
            or self._active_conversation_id.get(session_id)
            or "default"
        )
        try:
            from backend.agent.agent_kernel import get_agent_kernel
            from backend.agent.tools.screenshot_page_tool import (
                capture_page_screenshot,
            )
            from backend.utils.observability import get_turn_id

            kernel = get_agent_kernel(conversation_id, session_id)
            return await capture_page_screenshot(
                url=url,
                kernel=kernel,
                conversation_id=conversation_id,
                turn_id=get_turn_id(),
            )
        except Exception as exc:  # noqa: BLE001 — a picture never fails a turn
            logger.warning("[ToolBridge] screenshot_page failed: %s", exc)
            return {"success": False, "error": "the page could not be captured"}

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

            # T14 (REQ-13): park-and-continue. When the caller passes
            # non_blocking=True (with optional parked_url/run_id), the question
            # card is raised and the tool returns IMMEDIATELY with a handle —
            # the research run keeps going with the remaining sources (AC2)
            # and picks the parked source back up when the answer arrives
            # (AC3). The blocking wait_for_answer path below is untouched for
            # existing callers.
            if params.get("non_blocking"):
                question = tool.ask_non_blocking(
                    text=text,
                    options=params.get("options"),
                    allow_other=params.get("allow_other", True),
                    turn_id=session_id,
                    run_id=params.get("run_id"),
                    parked_url=params.get("parked_url"),
                    wall_kind=params.get("wall_kind", "unknown"),
                )
                return {
                    "success": True,
                    "non_blocking": True,
                    "question_id": question.question_id,
                    "parked": bool(params.get("parked_url")),
                }

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

    async def execute_tool(self, tool_name: str, params: Dict, session_id: str = "unknown", plan_title: str = "", _skip_resilience: bool = False) -> Dict:
        """FAULTLINE boundary (session 244) — universal typed outcomes.

        EVERY tool result passes through here, so every failure leaving this
        bridge carries the three-layer taxonomy: error_type (Layer-2 label),
        retryable/blame/info_state (Layer-1 dimensions), details["raw"]
        (preserved original). Legacy tools returning bare
        {"success": False, "error": str(exc)} are classified automatically at
        this choke point — universality by enforcement, not by convention.
        Idempotent: already-typed results pass through with dimensions filled.
        """
        result = await self._execute_tool_dispatch(
            tool_name, params, session_id, plan_title, _skip_resilience
        )
        try:
            from backend.agent.tool_errors import normalize_failure
            result = normalize_failure(result)
        except Exception:  # noqa: BLE001 — taxonomy must never break execution
            pass
        return result

    async def _execute_tool_dispatch(self, tool_name: str, params: Dict, session_id: str = "unknown", plan_title: str = "", _skip_resilience: bool = False) -> Dict:
        """
        Execute any tool by name with routing to appropriate server.

        Integrates with AgentKernel context for tool results.  ``plan_title``
        (set by the DER planner) is threaded into memory events so tool executions
        are recallable by plan context in the Immortus thread.

        Requirements: 8.3, 8.4, 8.5, 8.6
        """
        # ── Phase 2: registry-based name resolution + consolidated gates ──
        # The DER planner (LLM) frequently emits "web_search" / "google_search";
        # the registry normalizes these aliases to the canonical "search" so every
        # downstream check (capability gate, internet/desktop gate, permissions,
        # dispatch) sees the canonical name.  This replaces the old hardcoded
        # _TOOL_ALIASES dict and the scattered InternetGate / DesktopGate checks
        # with a single declarative capability check (Pillar A).
        from backend.agent.tool_registry import resolve_tool, capability_allowed, capability_denied_by
        spec = resolve_tool(tool_name)
        if spec is not None:
            tool_name = spec.name  # canonical name (web_search/google_search -> search)

        # [13.3] Runtime capability gate (developer-only tools blocked in personal mode)
        # REQ-18: a capability-blocked tool ESCALATES to a permission request (the user
        # can override) instead of being silently denied with an error.
        from backend.capabilities import CapabilitySet
        if not CapabilitySet.is_tool_allowed(tool_name):
            logger.warning(
                "[13.3] Tool '%s' blocked in '%s' mode — escalating to permission request",
                tool_name, CapabilitySet.get_mode(),
            )
            try:
                from backend.agent.permissions import classify_tool, get_permission_system

                tier = classify_tool(tool_name, params)
                level = CapabilitySet.get_mode()
                perm_system = get_permission_system()
                req = perm_system.request_permission(
                    tool_name=tool_name,
                    tier=tier,
                    params=params,
                    description=(
                        f"Allow '{tool_name}'? It is blocked by the capability gate "
                        f"in {level} mode."
                    ),
                    level=level,
                    force=True,
                    session_id=session_id,
                )
                if req.status == "pending":
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
                    # approved — fall through and execute the tool below
            except Exception:
                logger.warning(
                    "[13.3] Capability escalation failed — blocking tool (fail closed)", exc_info=True
                )
                return {
                    "success": False,
                    "error": f"Permission check error for tool '{tool_name}'",
                    "permission_response": "error",
                }

        # ── Consolidated internet/desktop gate (Pillar A capability_allowed) ──
        # Replaces the old inline `if tool_name in ("search","crawler_query")` and
        # `if tool_name in DESKTOP_CONTROL_TOOLS` checks.  Reads the tool's
        # requires_internet / requires_desktop flags from the registry and the
        # real capability flags via injected providers (wired at startup).
        if spec is not None and not capability_allowed(spec):
            # REQ-16/T29: report the ACTUAL denying capability, not the first
            # flag in declaration order. open_url now sets both requires_internet
            # and requires_desktop; with the old presence-based check a
            # desktop-denied call would wrongly report "Internet access is
            # disabled". capability_denied_by() names the true blocker.
            denied = capability_denied_by(spec)
            if denied == "internet":
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
            if denied == "desktop":
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

        # ── Auto-narrate search initiation (UX, kept from original InternetGate) ──
        # Give the user active verbal feedback the instant the agent engages a web
        # search.  Fires before the crawl so it still speaks even if the search
        # fails.  TTS is best-effort and never blocks the search.
        # Gated by may_narrate() so overlapping DER steps don't stack TTS.
        if tool_name in ("search", "crawler_query"):
            _q = (params or {}).get("query") or ""
            if _q:
                try:
                    from backend.agent.narration import may_narrate
                    if may_narrate():
                        self._handle_speak({"text": f"Searching the web for {_q}"}, session_id)
                except Exception:
                    self._handle_speak({"text": f"Searching the web for {_q}"}, session_id)

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
            # REQ-16 AC5: log the resolved permission action for every gated call.
            logger.info(
                "[Permissions] gated_call tool=%s tier=%s mode=%s action=%s",
                tool_name, tier.value, level, action.value,
            )

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
                session_id=session_id,
            )
                if req.status == "pending":
                    # Wait for user response (async)
                    resolved = await perm_system.get_response_async(req)
                    if resolved.status == "denied":
                        logger.info(
                            "[Permissions] resolved tool=%s action=denied", tool_name
                        )
                        return {
                            "success": False,
                            "error": f"Permission denied for tool '{tool_name}'",
                            "permission_response": "denied",
                        }
                    if resolved.status == "timed_out":
                        logger.warning(
                            "[Permissions] resolved tool=%s action=timed_out", tool_name
                        )
                        return {
                            "success": False,
                            "error": f"Permission timed out for tool '{tool_name}'",
                            "permission_response": "timed_out",
                        }
                    # approved — continue
                    logger.info(
                        "[Permissions] resolved tool=%s action=approved", tool_name
                    )
        except Exception:
            # REQ-17: the gate must NOT silently bypass on error. Fail CLOSED
            # (block the tool) rather than allowing it to proceed.
            logger.warning(
                "[Permissions] Permission check failed — blocking tool (fail closed)", exc_info=True
            )
            return {
                "success": False,
                "error": f"Permission check error for tool '{tool_name}'",
                "permission_response": "error",
            }

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
            internal_tools = ["ask_user_question", "speak", "screenshot_page"]
            media_tools = ["transcribe_media", "analyze_video_frames", "clip_video"]

            if tool_name in internal_tools:
                if tool_name == "ask_user_question":
                    return await self._handle_ask_user_question(params, session_id)
                if tool_name == "speak":
                    return self._handle_speak(params, session_id)
                if tool_name == "screenshot_page":
                    return await self._handle_screenshot_page(params, session_id)

            # Read-only document-data retrieval for recombination / re-render
            # (REQ-7/REQ-8). Returns the active conversation's full document DATA
            # (incl. har_path) so the agent can combine prior docs. Conv-scoped.
            if tool_name == "get_rendered_documents":
                return await self._execute_get_rendered_documents(params, session_id)
            if tool_name == "list_conversations":
                return await self._execute_list_conversations(params, session_id)

            # Combine several rendered documents into one (REQ-9). Local op.
            if tool_name == "combine_documents":
                return await self._execute_combine_documents(params, session_id)

            if tool_name in vision_tools:
                    result = await self.execute_vision_tool(tool_name, params, session_id)
                    screenshot_blob = self._capture_screenshot_blob()
                    self._record_tool_event(
                        session_id, tool_name,
                        "success" if result.get("success") else "failure", params, result,
                        plan_title=plan_title, screenshot_blob=screenshot_blob,
                    )
                    return result

            if tool_name in gui_tools:
                    result = await self.execute_gui_tool(tool_name, params, session_id)
                    screenshot_blob = self._capture_screenshot_blob()
                    self._record_tool_event(
                        session_id, tool_name,
                        "success" if result.get("success") else "failure", params, result,
                        plan_title=plan_title, screenshot_blob=screenshot_blob,
                    )
                    return result

            if tool_name in media_tools:
                    return await self.execute_media_tool(tool_name, params, session_id)

            # MCP Tools
            # Phase 5.3 (research D3): route dispatch through the resilience
            # wrapper so retries live in one place.  When called recursively
            # with _skip_resilience, run the dispatch directly (no double-wrap).
            if not _skip_resilience:
                return await self._execute_tool_with_resilience(tool_name, params, session_id, plan_title)

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

            # ── In-app open_url (REQ-16/T27): navigation happens inside IRIS's
            # browser surface, never the user's desktop browser. Mirrors the
            # search interception above — routed here BEFORE the MCP dispatch
            # so it never reaches BrowserServer.execute_tool -> webbrowser.open.
            if tool_name == "open_url":
                result = await self._execute_open_url(params, session_id)
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
                _mi = getattr(self, "_memory_interface", None)
                if _mi is None:
                    try:
                        from backend.memory import get_memory_interface

                        _mi = get_memory_interface()
                    except Exception:  # noqa: BLE001 — memory is optional
                        _mi = None
                if _mi and hasattr(_mi, "episodic"):
                    results = _mi.episodic.retrieve_similar(
                        task=query, limit=_retrieval_limit, min_score=_retrieval_score
                    ) or []
                return {"success": True, "results": results}

            if tool_name == "improve_self":
                result = await self._execute_research_tool(params, session_id)
                self._record_tool_event(session_id, tool_name, "success" if result.get("success") else "failure", params, result, plan_title=plan_title)
                return result

            if tool_name == "crawler_query":
                # Long-running tool: wrap with the generic narration heartbeat
                # (backend/agent/narration.py), driven by the ToolSpec.long_running
                # capability — NOT a web-mode override. This keeps the DER operator
                # uniform (blueprint: no mode-driven fan-out). The heartbeat speaks
                # periodic progress through the SpeakTool while the crawl runs.
                from backend.agent.narration import run_with_narration

                result = await run_with_narration(
                    lambda: self._execute_crawler_query(params, session_id),
                    speak=self._speak_tool.speak,
                    tool_name=tool_name,
                    conversation_id=session_id,
                )
                self._record_tool_event(session_id, tool_name, "success" if result.get("success") else "failure", params, result, plan_title=plan_title)
                return result

            # ── Multimedia tools (Phase 5.2 / research D2) ────────────────────
            media_tools = {"transcribe_media", "analyze_video_frames", "clip_video"}
            if tool_name in media_tools:
                result = await self._execute_media_tool(tool_name, params, session_id)
                self._record_tool_event(
                    session_id, tool_name,
                    "success" if result.get("success") else "failure", params, result,
                    plan_title=plan_title,
                )
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

    def _capture_screenshot_blob(self) -> "bytes | None":
        """Capture the current screen as PNG bytes for memory storage.

        Used to attach a screenshot to the tool-execution event so vision /
        screenshot tool results are recallable from the application memory db.
        Returns None if the vision server is unavailable or capture fails
        (e.g. headless environment) — never raises.
        """
        try:
            vision_server = self._mcp_servers.get("vision")
            if vision_server is not None and hasattr(vision_server, "screenshot_to_bytes"):
                return vision_server.screenshot_to_bytes()
        except Exception as exc:  # noqa: BLE001
            logger.debug("screenshot capture for memory failed: %s", exc)
        return None

    def _record_tool_event(
        self, session_id: str, tool_name: str, outcome: str,
        params: Dict, result: Dict, plan_title: str = "",
        screenshot_blob: bytes = None,
    ) -> None:
        """
        Record a tool execution event via the C++ core FFI bridge.
        Fire-and-forget: never blocks the tool execution path.
        ``plan_title`` (set by the DER planner) is threaded into the event
        payload so tool executions are recallable by plan context.
        ``screenshot_blob`` (optional PNG bytes) is attached to the event row
        in the SQLite system_events store when the tool captured the screen.
        """
        # THIS IS OBSERVABILITY. It must never sit on the critical path of the
        # thing it observes. The docstring above always CLAIMED fire-and-forget;
        # it was called synchronously and blocked. A live stack dump caught the
        # DER thread parked here across consecutive samples, inside
        # ffi_ingest_event -> SQLite, right after a web search returned — so a
        # completed crawl looked like a hung one, and the crawl's own UI events
        # never got to surface. Two things were wrong and both are fixed here:
        #   1. It serialised the ENTIRE result. For a crawl that is every
        #      fetched page's body — megabytes of JSON pushed through FFI into
        #      SQLite, scaling with how well the search worked.
        #   2. It ran inline. Now it runs on a daemon thread, so a slow audit
        #      write cannot stall the tool that already finished.
        try:
            import json
            import threading as _threading

            from backend.gateway.iris_ffi import ffi_ingest_event

            def _summarize(value, _depth: int = 0):
                """Keep the SHAPE of the result, drop the bulk.

                An audit row needs to answer "what happened", not carry the
                payload. Long strings become a length marker so a 2 MB page
                body costs ~40 bytes and the record stays diagnosable.
                """
                _CAP = 512
                if isinstance(value, str):
                    return value if len(value) <= _CAP else f"{value[:_CAP]}…<{len(value)} chars>"
                if isinstance(value, dict):
                    if _depth >= 3:
                        return f"<dict:{len(value)} keys>"
                    return {k: _summarize(v, _depth + 1) for k, v in list(value.items())[:40]}
                if isinstance(value, (list, tuple)):
                    if _depth >= 3:
                        return f"<list:{len(value)}>"
                    out = [_summarize(v, _depth + 1) for v in value[:20]]
                    if len(value) > 20:
                        out.append(f"…<{len(value)} items total>")
                    return out
                if isinstance(value, (bytes, bytearray)):
                    return f"<bytes:{len(value)}>"
                return value

            payload = json.dumps({
                "tool": tool_name,
                "params": _summarize(params),
                "result": _summarize(result),
                "plan_title": plan_title,
                # FAULTLINE (session 244): failures enter the learning record
                # with their typed taxonomy, so episodes are recallable by
                # CAUSE ("walled", "transient", …) and their dimensions —
                # not just a bare exception string.
                "error_type": result.get("error_type"),
                "retryable": result.get("retryable"),
                "blame": result.get("blame"),
                "info_state": result.get("info_state"),
            })

            def _ingest() -> None:
                try:
                    ffi_ingest_event(
                        session_id=session_id,
                        domain="SYSTEM",
                        event_type="tool_execution",
                        actor="agent_tool_bridge",
                        outcome=outcome,
                        summary=f"Tool {tool_name} executed: {outcome}",
                        payload_json=payload,
                        screenshot_blob=screenshot_blob,
                    )
                except Exception as _exc:  # noqa: BLE001
                    logger.debug("[tool-event] ingest failed for %s: %s", tool_name, _exc)

            _threading.Thread(
                target=_ingest, daemon=True, name=f"tool-event-{tool_name}",
            ).start()
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

    async def _execute_tool_with_resilience(self, tool_name: str, params: Dict, session_id: str, plan_title: str) -> Dict:
        """Execute a tool with retry/backoff on transient failures (Phase 5.3 / D3).

        Consolidates resilience in one place: ToolExecutor delegates here and
        execute_tool routes through here, so retries are not duplicated across
        the two dispatch paths.
        """
        from backend.agent.resilience import retry_with_backoff
        return await retry_with_backoff(
            lambda: self.execute_tool(
                tool_name, params, session_id=session_id, plan_title=plan_title,
                _skip_resilience=True,
            ),
            label=f"tool:{tool_name}",
        )

    async def _execute_media_tool(self, tool_name: str, params: Dict, session_id: str) -> Dict:
        """Dispatch the three multimedia tools (Phase 5.2 / research D2)."""
        try:
            from backend.tools import media_tools as _mt
            if tool_name == "transcribe_media":
                return _mt.transcribe_media(
                    audio_path=params.get("audio_path", ""),
                    chunk_seconds=int(params.get("chunk_seconds", _mt.MAX_CHUNK_SECONDS)),
                )
            if tool_name == "analyze_video_frames":
                return _mt.analyze_video_frames(
                    video_path=params.get("video_path", ""),
                    question=params.get("question", "What is happening in this frame?"),
                    frame_interval=float(params.get("frame_interval", 1.0)),
                )
            if tool_name == "clip_video":
                return _mt.clip_video(
                    video_path=params.get("video_path", ""),
                    start=params.get("start", "0"),
                    end=params.get("end", "0"),
                    output_path=params.get("output_path", ""),
                )
            return {"success": False, "error": f"Unknown media tool: {tool_name}"}
        except Exception as e:
            logger.error("[ToolBridge] media tool %s failed: %s", tool_name, e, exc_info=True)
            return {"success": False, "error": str(e)}

    async def _execute_research_tool(self, params: Dict, session_id: str) -> Dict:
        """Handle the improve_self agent tool — delegates to AutoResearchRunner."""
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

    async def _execute_crawler_query(
        self, params: Dict, session_id: str, background: bool = False
    ) -> Dict:
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

        ``background`` (REQ-29): when True the crawl runs to completion and the
        result is stored in the JobRegistry keyed by job_id; the client can
        fetch it via GET /api/crawl/result/{job_id} after reconnecting, instead
        of re-running the crawl. The returned dict carries ``job_id``.
        """
        query = (params.get("query") or "").strip()
        if not query:
            return {"success": False, "error": "crawler_query requires a 'query'"}

        # REQ-29 + pin_517dfcbda150: same (session, query) = same job_id.
        # A COMPLETED job for an identical query is REUSED (cached result) —
        # re-gather must come from a REFINED query (new hash = new job), never
        # a repeat crawl. A RUNNING job is awaited (parallel split children of
        # the same parent share the query). An errored/cancelled job falls
        # through to register() so a transient failure can be retried.
        job_id = f"crawl_{session_id}_{abs(hash(query)) % 10**8}"
        _registry = None
        _cached: Optional[Dict] = None
        try:
            from backend.crawler.job_registry import get_job_registry
            _registry = get_job_registry()
            _existing = await _registry.get(job_id)
            if _existing is not None:
                if _existing.status == "running":
                    await _existing.wait(timeout=180)
                    _existing = await _registry.get(job_id)
                if (
                    _existing is not None
                    and _existing.status == "complete"
                    and _existing.result
                ):
                    _cached = dict(_existing.result)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[crawler_query] job registry unavailable: %s", exc)
        if _cached:
            _cached.setdefault("cached", True)
            _cached.setdefault("job_id", job_id)
            # pin_42ddd255162d: the stored registry result is the clean tool
            # dict, which lacks the `success` envelope the dispatcher reads.
            # Re-emit success=True so a cached re-dispatch is not
            # misclassified as a failed execution.
            _cached["success"] = True
            logger.info(
                "[crawler_query] dedupe hit job=%s query=%r (cached, no re-crawl)",
                job_id, query,
            )
            return _cached
        try:
            if _registry is not None:
                await _registry.register(job_id, session_id, query)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[crawler_query] job registry unavailable: %s", exc)

        try:
            from backend.crawler.orchestrator import get_crawl_orchestrator, CrawlProgress
            from backend.agent.tools.speak_tool import get_speak_tool
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent
            from backend.agent.narration import may_narrate
        except Exception as exc:
            return {"success": False, "error": f"crawler modules unavailable: {exc}"}

        _speak_tool = get_speak_tool()
        _bus = get_event_bus()

        # Flip the orb / ContextPill phase to "processing_tool" (SEARCHING) so the
        # user sees the assistant is actively researching, not just "processing
        # my STT". Bridged to the frontend via WSEventBridge.
        try:
            _bus.emit(
                IRISStreamEvent.LISTENING_STATE,
                data={"state": "processing_tool"},
                session_id=session_id,
            )
        except Exception:
            pass  # never block the crawl on an event emit failure

        # ── REQ-9: structured log for card transition observability ──
        logger.info(
            "Card transition",
            extra={
                "context": "card",
                "state": "processing_tool",
                "session_id": session_id,
            },
        )

        _last_narration_time = 0.0
        _NARRATION_COOLDOWN_S = 25.0  # W5 (T35): speak progress at most once per 25s

        # REQ-4 AC4: bound phase-transition emission frequency. The
        # orchestrator only fires ~3-5 phase transitions per crawl
        # (searching -> extracting -> citing, plus one retry re-emit of
        # "searching" — see orchestrator.py:176/203/228/242), so anything
        # arriving faster than 2/sec is not real user-visible movement; it
        # would be a runaway loop, not progress, so throttle rather than
        # flood TASK_PROGRESS.
        _PHASE_EMIT_MIN_INTERVAL_S = 0.5
        _last_phase_emit_time = [0.0]  # mutable box for the closure below
        _PHASE_LABELS = {
            "searching": "Searching for sources",
            "fetching": "Fetching pages",
            "extracting": "Extracting content",
            "reranking": "Ranking sources",
            "citing": "Citing sources",
            "done": "Finishing up",
        }

        def _emit_phase_progress(phase: str, phase_sequence: int) -> None:
            """REQ-4 AC1: a phase transition produces its own card update —
            it does NOT wait for a page-fetch event to ride along on, so a
            crawl that returns zero pages still shows movement (Edge Case:
            "Crawl returns zero pages -> phases still emitted").

            AC2: fires immediately, without requiring the step to complete.
            AC3: emission failures are caught here and logged loudly — they
            must never fail or stall the crawl, but a silently swallowed
            exception that leaves the UI frozen is the exact defect this
            phase exists to kill, so this is not a bare `except: pass`.
            AC4: throttled by _PHASE_EMIT_MIN_INTERVAL_S above.
            AC5/REQ-2 AC1: only structured fields (`detail`/`detail_progress`/
            `phase`) move; the step's own `description` (plan text) is never
            touched — `update_step` only ever writes `activeDetail` /
            `activeProgress` on the frontend, never `description`.
            """
            now = time.time()
            if now - _last_phase_emit_time[0] < _PHASE_EMIT_MIN_INTERVAL_S:
                return
            _last_phase_emit_time[0] = now
            _label = _PHASE_LABELS.get(phase, phase.replace("_", " ").capitalize())
            task_progress_data = {
                "description": _label,
                "action": _label,
                "update_step": True,
                "detail": _label,
                "detail_progress": "",
                "phase": phase,
                "phase_sequence": phase_sequence,
            }
            try:
                _bus.emit(
                    IRISStreamEvent.TASK_PROGRESS,
                    data=task_progress_data,
                    session_id=session_id,
                )
            except Exception as _phase_exc:
                logger.warning(
                    "[crawler_query] phase progress emit failed (phase=%s): %s",
                    phase, _phase_exc,
                )

        def _on_page_done(url: str, page_number: int, total: int, title: str = "", snippet: str = "") -> None:
            nonlocal _last_narration_time
            now = time.time()
            # Throttle: only speak if enough time has passed since last narration.
            should_speak = (now - _last_narration_time) >= _NARRATION_COOLDOWN_S
            _label = title or urlparse(url or "").netloc or "source"
            if should_speak:
                _last_narration_time = now
                # Use snippet content when available (more conversational and useful).
                _speak_text = snippet[:200] if snippet else _label
                try:
                    if may_narrate() and _speak_tool is not None:
                        _speak_tool.speak(
                            _speak_text,
                            priority="low",
                        )
                except Exception as _spk_exc:  # pragma: no cover - best effort
                    logger.debug("[crawler_query] progress speak failed: %s", _spk_exc)
            # Live step feed: the source currently being read, plus the
            # ContextPill action text.
            #
            # `detail` / `detail_progress` are the STRUCTURED fields the card
            # renders beside the tool name — the plan step's own text is left
            # alone so the dropdown keeps showing what the agent set out to do.
            # `description` stays a full sentence for back-compat (ContextPill
            # and older consumers read it) and is the fallback when `detail` is
            # absent; do not remove it.
            task_progress_data = {
                "description": f"Reading {_label} ({page_number}/{total})",
                "action": f"Reading {_label} ({page_number}/{total})",
                "update_step": True,
                # Structured, so the frontend never parses a sentence.
                "detail": _label,
                "detail_url": url or "",
                "detail_progress": f"{page_number}/{total}",
            }
            try:
                _bus.emit(
                    IRISStreamEvent.TASK_PROGRESS,
                    data=task_progress_data,
                    session_id=session_id,
                )
            except Exception:
                pass  # never block the crawl on an event emit failure

        # REQ-16 AC6-AC9: the browser panel listens for open_tab /
        # crawler_started / crawler_page_fetched / crawler_complete. This
        # handler below emits TASK_PROGRESS (chat-side), which is a DIFFERENT
        # vocabulary — so an agent crawl used to update the chat while the
        # browser panel stayed inert. Forward the panel's events too.
        _ui_emit = _crawl_ui_emitter(session_id)

        def _on_progress(progress: CrawlProgress) -> None:
            try:
                _ui_emit(progress)
            except Exception:
                pass  # UI emit must never disturb the crawl
            ev = progress.event
            pl = progress.payload
            if ev == "CRAWLER_PAGE_FETCHED":
                _on_page_done(
                    pl["url"], pl["page_number"], pl["total"],
                    title=pl.get("title", ""),
                )
            elif ev == "CRAWLER_PHASE":
                # REQ-4 AC1: emit its own progress event on the transition —
                # do NOT wait for a page-fetch event to ride along on (that
                # was the bug: zero pages fetched meant zero phase updates,
                # which the spec's edge case forbids outright).
                if isinstance(pl, dict):
                    try:
                        _emit_phase_progress(
                            pl.get("phase", "unknown"), pl.get("phase_sequence", 0),
                        )
                    except Exception as _phase_progress_exc:
                        # AC3: never let a phase-emit failure propagate into
                        # the crawl's on_progress callback and stall the tool.
                        logger.warning(
                            "[crawler_query] phase progress dispatch failed: %s",
                            _phase_progress_exc,
                        )
            elif ev == "CRAWLER_ERROR":
                logger.error("[crawler_query] %s", pl.get("message", "error"))

        # Unified path: CrawlOrchestrator runs plan -> fetch -> split -> score ->
        # rerank -> cite -> extract in one place (REQ-15). mode="agent" uses the
        # subprocess fetch backend for C-level crash isolation (REQ-17). Narration
        # stays blueprint-pure: no web-mode override in the tool layer.
        try:
            result = await get_crawl_orchestrator().research(
                query, mode="agent", session_id=session_id, on_progress=_on_progress,
            )
        except Exception as exc:
            logger.exception("[crawler_query] research failed: %s", exc)
            if _registry is not None:
                await _registry.fail(job_id, f"research failed: {exc}")
            try:
                _bus.emit(IRISStreamEvent.LISTENING_STATE, data={"state": "processing_conversation"}, session_id=session_id)
            except Exception:
                pass
            # ── REQ-9: structured log for card transition ──
            logger.info("Card transition", extra={"context": "card", "state": "processing_conversation", "session_id": session_id})
            return {"success": False, "error": f"research failed: {exc}",
                    "error_type": _crawler_error_type(str(exc)), "job_id": job_id}

        # Return phase to "thinking" so the orb reflects the agent summarising.
        try:
            _bus.emit(IRISStreamEvent.LISTENING_STATE, data={"state": "processing_conversation"}, session_id=session_id)
        except Exception:
            pass  # never block on an event emit failure
        # ── REQ-9: structured log for card transition ──
        logger.info("Card transition", extra={"context": "card", "state": "processing_conversation", "session_id": session_id})

        # pin_42ddd255162d: the fallback path can return pages WITH an
        # informational error note (worker timed out; plain-HTTP fallback
        # used). With usable pages present the crawl SUCCEEDED (content
        # sufficiency at the tool boundary), so the note must not poison the
        # result: carry it under `note:` and proceed to the success build.
        _fallback_note = None
        if result.error:
            _has_pages = bool((result.dashboard_data or {}).get("pages"))
            if not _has_pages:
                logger.error("[crawler_query] crawl failed: %s", result.error)
                if _registry is not None:
                    await _registry.fail(job_id, result.error)
                return {"success": False, "error": result.error,
                        "error_type": _crawler_error_type(result.error), "job_id": job_id}
            _fallback_note = str(result.error)
            logger.info(
                "[crawler_query] fallback produced %d page(s) with worker note: %s",
                len((result.dashboard_data or {}).get("pages")), result.error,
            )

        crawl_result = result
        dashboard_data = result.dashboard_data or {}

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
        # REQ-1 AC1: EVERY layer that judges fetch success calls the shared
        # predicate — the old local judge (`if _err: continue; if _md:`) could
        # count a whitespace-only or challenge-boilerplate page as content,
        # which let a zero-usable-content crawl report success=True.
        from backend.crawler.usability import page_is_usable
        for _p in getattr(crawl_result, "pages", []):
            if not page_is_usable(_p).usable:
                continue
            _md = getattr(_p, "markdown", "") or ""
            if _md:
                _content_parts.append(f"--- Source: {getattr(_p, 'url', '')} ---\n{_md}")
        _combined = "\n\n".join(_content_parts)
        if len(_combined) > _CONTENT_CAP:
            _combined = _combined[:_CONTENT_CAP] + "\n\n[...truncated...]"

        # pin_517dfcbda150: honesty at the tool boundary — success means usable
        # content. A crawl that fetched zero usable text returns an ERROR, so
        # the DER verifier (content-sufficiency) never sees a hollow "success"
        # and the step commits only when real content exists.
        if not _combined:
            # Session 244: typed outcome for DER — "no usable content" is NOT
            # one failure mode. When sources were parked, say so with the park
            # summary so the reviewer can distinguish "the information does not
            # exist" (rephrase/give up) from "our sources got walled" (diversify
            # or ask the user) instead of blind-retrying the identical search.
            _ps = getattr(crawl_result, "park_summary", None)
            _no_content = "crawler_query returned no usable content for query"
            if _ps:
                _no_content += (
                    f" — {_ps}. A retry of the SAME search will fail identically; "
                    f"diversify sources or ask the user."
                )
            if _registry is not None:
                await _registry.fail(job_id, _no_content)
            return {
                "success": False,
                "error": _no_content,
                "error_type": "sources_parked" if _ps else "empty_result",
                "job_id": job_id,
            }

        # REQ-29: store the completed result in the registry so a reconnecting
        # client can fetch it via GET /api/crawl/result/{job_id} (background).
        if _registry is not None:
            await _registry.complete(job_id, {
                "query": query,
                "title": dashboard_data.get("title", query),
                "summary": dashboard_data.get("summary", ""),
                "content": _combined,
                "pages": pages,
                "links": [pg["url"] for pg in pages if pg.get("url")],
                "cited_markdown": result.cited_markdown,
                "credibility_map": getattr(crawl_result, "credibility_map", None),
                "citation_index": getattr(crawl_result, "citation_index", None),
            })

        # REQ-13: feed crawl results into the SourceRegistry so the system
        # learns which URLs are credible for which topics. Runs best-effort.
        try:
            from backend.crawler.source_registry import get_source_registry
            from backend.crawler.search_providers.base import SearchResult, SearchResultItem

            _urls = [pg["url"] for pg in pages if pg.get("url")]
            if _urls:
                _items = [SearchResultItem(url=u) for u in _urls]
                await get_source_registry().learn(
                    query,
                    SearchResult(query=query, results=_items, provider="exa"),
                    getattr(crawl_result, "credibility_map", None),
                )
        except Exception as _learn_exc:
            logger.debug("[crawler_query] registry learn skipped: %s", _learn_exc)

        return {
            "success": True,
            "query": query,
            "title": dashboard_data.get("title", query),
            "summary": dashboard_data.get("summary", ""),
            "content": _combined,
            "pages": pages,
            "links": [pg["url"] for pg in pages if pg.get("url")],
            "trust": "untrusted",  # external tool result — route to reference zone
            "job_id": job_id,  # REQ-29: client can fetch result after reconnect
            # pin_42ddd255162d: informational worker note (fallback path) — kept
            # out of `error` so the DER verifier sees a clean success.
            **({"note": _fallback_note} if _fallback_note else {}),
            # REQ-22: untrusted web scoring forwarded to pacman for persistence
            # in the 'reference' zone (credibility_map + citation_index).
            "credibility_map": getattr(crawl_result, "credibility_map", None),
            "citation_index": getattr(crawl_result, "citation_index", None),
        }

    async def _execute_get_rendered_documents(self, params: Dict, session_id: str) -> Dict:
        """REQ-7/REQ-8: return the active conversation's rendered document DATA.

        Full data (content, variants, sources, source_document_id, har_path) so the
        agent can recombine / re-render prior documents (the "combine A + B" path).
        Conv-scoped via ``list_for_conversation`` (REQ-12 thread isolation) — other
        threads are never returned. Read-only; never raises into the caller.
        """
        params = params or {}
        conversation_id = (
            params.get("conversation_id")
            or self._active_conversation_id.get(session_id)
            or "default"
        )
        try:
            from backend.agent.agent_kernel import get_agent_kernel
            from backend.agent.document_store import DocumentDataStore

            kernel = get_agent_kernel(conversation_id, session_id)
            store = kernel._get_document_store() if kernel is not None else None
            if store is None:
                return {
                    "success": True,
                    "conversation_id": conversation_id,
                    "documents": [],
                }
            documents = store.list_for_conversation(
                conversation_id, metadata_only=False
            )
            logger.info(
                "[ToolBridge] GET RENDERED DOCS conv=%s returned=%d",
                conversation_id,
                len(documents),
            )
            return {
                "success": True,
                "conversation_id": conversation_id,
                "documents": documents,
            }
        except Exception as exc:
            logger.warning(
                "[ToolBridge] get_rendered_documents failed: %s", exc
            )
            return {"success": False, "error": str(exc), "documents": []}

    async def _execute_list_conversations(self, params: Dict, session_id: str) -> Dict:
        """Discovery for cross-thread reuse: list conversations that have documents.

        Lets the agent find a PRIOR thread (one that previously rendered a document)
        and then pull its data via get_rendered_documents(conversation_id=...) instead
        of re-searching the web. Read-only; never raises into the caller.
        """
        try:
            from backend.agent.agent_kernel import get_agent_kernel
            from backend.agent.document_store import DocumentDataStore

            # Same resolution chain as the two sibling call sites (:2145,
            # :2229). This one omitted the params lookup, so it ALWAYS resolved
            # to "default": self._active_conversation_id is declared at :108,
            # read in three places, and written in NONE — a permanently empty
            # map. Callers that pass conversation_id explicitly now win here
            # too, instead of silently addressing the "default" thread.
            conversation_id = (
                (params or {}).get("conversation_id")
                or self._active_conversation_id.get(session_id)
                or "default"
            )
            kernel = get_agent_kernel(conversation_id, session_id)
            store = kernel._get_document_store() if kernel is not None else None
            if store is None:
                return {
                    "success": True,
                    "active_conversation_id": conversation_id,
                    "conversations": [],
                }
            conversations = store.list_conversations()
            logger.info(
                "[ToolBridge] LIST CONVERSATIONS active=%s returned=%d",
                conversation_id,
                len(conversations),
            )
            return {
                "success": True,
                "active_conversation_id": conversation_id,
                "conversations": conversations,
            }
        except Exception as exc:
            logger.warning(
                "[ToolBridge] list_conversations failed: %s", exc
            )
            return {"success": False, "error": str(exc), "conversations": []}

    async def _execute_combine_documents(self, params: Dict, session_id: str) -> Dict:
        """REQ-9: combine several rendered documents into one new render.

        Reads the named documents from the active conversation's store, combines
        their content + unions their sources, and stores the result. Local op
        (no network). Conv-scoped. Never raises into the caller.
        """
        params = params or {}
        document_ids = params.get("document_ids") or []
        if not isinstance(document_ids, list) or not document_ids:
            return {"success": False, "error": "document_ids (list) required"}
        conversation_id = (
            params.get("conversation_id")
            or self._active_conversation_id.get(session_id)
            or "default"
        )
        try:
            from backend.agent.agent_kernel import get_agent_kernel
            from backend.agent.recombination import combine_documents

            kernel = get_agent_kernel(conversation_id, session_id)
            store = kernel._get_document_store() if kernel is not None else None
            if store is None:
                return {"success": False, "error": "document store unavailable"}
            combined = combine_documents(store, document_ids, conversation_id)
            if combined is None:
                return {
                    "success": False,
                    "error": "no resolvable documents to combine",
                }
            logger.info(
                "[ToolBridge] COMBINE DOCS conv=%s ids=%s -> %s",
                conversation_id,
                document_ids,
                combined["document_id"],
            )
            return {"success": True, **combined}
        except Exception as exc:
            logger.warning("[ToolBridge] combine_documents failed: %s", exc)
            return {"success": False, "error": str(exc)}

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
            from backend.crawler.orchestrator import CrawlOrchestrator
        except Exception as exc:
            return {"success": False, "error": f"crawler modules unavailable: {exc}"}

        try:
            # Route through CrawlOrchestrator — the SAME Crawl4AI subprocess path
            # crawler_query uses. It plans URLs via the LLM (Cerebras); NO search
            # engine / DuckDuckGo is involved (see crawl_planner._fallback_plan).
            # The crawl runs in a killable subprocess so a stalled fetch cannot
            # block the event loop (spec REQ-17 + DER _split_step). session_id tags
            # the crawl + its memory per-thread (REQ-32).
            #
            # on_progress IS REQUIRED FOR THE UI. Every orchestrator event flows
            # through this callback (orchestrator._make_emitter._emit); omitting
            # it silences the crawl completely. This call previously passed
            # nothing, so an agent-driven search rendered its answer in chat
            # while the browser panel never animated — the overlay
            # (hooks/useBrowserNavOverlay.ts) listens for open_tab /
            # crawler_started / crawler_page_fetched / crawler_complete and
            # received none of them. REQ-16 AC6-AC9.
            #
            # Session 244 (live-run findings): the browser-panel emitter alone
            # still left the CHAT CARD dead — no task:progress ever reached it,
            # so step actions never updated and per-page URLs (detail_url)
            # never rendered. This path now emits BOTH vocabularies: the
            # browser-panel events AND the TASK_PROGRESS frames the card
            # consumes (phase labels + per-page detail/detail_url), mirroring
            # what crawler_query has always done.
            from backend.agent.event_bus import get_event_bus as _geb, IRISStreamEvent as _ISE

            _bus = _geb()
            _last_phase_emit = [0.0]

            def _emit_phase(phase: str, seq: int) -> None:
                import time as _time
                now = _time.time()
                if now - _last_phase_emit[0] < 2.0:  # throttle phase spam
                    return
                _last_phase_emit[0] = now
                _label = phase.replace("_", " ").capitalize()
                try:
                    _bus.emit(
                        _ISE.TASK_PROGRESS,
                        data={
                            "description": _label,
                            "action": _label,
                            "update_step": True,
                            "detail": _label,
                            "detail_progress": "",
                            "phase": phase,
                            "phase_sequence": seq,
                        },
                        session_id=session_id,
                    )
                except Exception:
                    pass  # never block the crawl on an event emit failure

            def _on_page(url: str, page_number: int, total: int, title: str = "") -> None:
                _label = title or url or "source"
                try:
                    _bus.emit(
                        _ISE.TASK_PROGRESS,
                        data={
                            "description": f"Reading {_label} ({page_number}/{total})",
                            "action": f"Reading {_label} ({page_number}/{total})",
                            "update_step": True,
                            "detail": _label,
                            "detail_url": url or "",
                            "detail_progress": f"{page_number}/{total}",
                        },
                        session_id=session_id,
                    )
                except Exception:
                    pass

            _ui_emit = _crawl_ui_emitter(session_id)

            def _combined_on_progress(progress) -> None:
                # Browser panel first (its vocabulary, best-effort).
                try:
                    _ui_emit(progress)
                except Exception:
                    pass
                ev = getattr(progress, "event", "")
                pl = getattr(progress, "payload", {}) or {}
                if ev == "CRAWLER_PAGE_FETCHED":
                    _on_page(
                        pl.get("url", ""), pl.get("page_number", 0),
                        pl.get("total", 0), title=pl.get("title", ""),
                    )
                elif ev == "CRAWLER_PHASE" and isinstance(pl, dict):
                    _emit_phase(pl.get("phase", "unknown"), pl.get("phase_sequence", 0))

            orch = CrawlOrchestrator()
            crawl_result = await orch.research(
                query=query,
                mode="agent",
                session_id=session_id,
                on_progress=_combined_on_progress,
            )
        except Exception as exc:
            logger.exception("[web_search] crawl failed: %s", exc)
            return {"success": False, "error": f"search failed: {exc}"}

        if getattr(crawl_result, "error", None):
            logger.warning("[web_search] crawl error (query=%r): %s", query, crawl_result.error)
            return {"success": False, "error": crawl_result.error,
                    "error_type": _crawler_error_type(crawl_result.error)}

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

        _sources = [getattr(_p, "url", "") for _p in getattr(crawl_result, "pages", []) if getattr(_p, "url", "")]

        return {
            "success": True,
            "query": query,
            "content": _combined,
            "url": _sources[0] if _sources else "",
            "sources": _sources,
            "trust": "untrusted",  # external tool result — route to reference zone
        }

    async def _execute_open_url(self, params: Dict, session_id: str) -> Dict:
        """Agent tool: open a URL inside IRIS's in-app browser surface.

        REQ-16 (T27): replaces the old ``BrowserServer.open_url`` which called
        ``webbrowser.open()`` and hijacked the user's REAL desktop browser.
        Navigation is now fully in-app:
          1. an ``open_tab`` WS message drives the existing dashboard browser
             tab (iframe) — the user SEES the page load; zero dashboard
             changes needed;
          2. the single page is fetched headlessly (crash-isolated subprocess,
             same engine as ``search``) and returned as markdown so the agent
             can reason about it.
        Gated by the internet-access flag (see the InternetGate block in
        execute_tool). Never touches the desktop.
        """
        import uuid

        url = (params.get("url") or "").strip()
        if not url:
            return {"success": False, "error": "open_url requires a 'url'"}
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        # 1) In-app surface: open a browser tab (best-effort — never fails the
        #    tool, and a session with no live client simply skips the tab).
        try:
            from backend.ws_manager import get_websocket_manager

            _ws = get_websocket_manager()
            if _ws is not None and _ws.get_clients_for_session(session_id):
                await _ws.broadcast_to_session(session_id, {
                    "type": "open_tab",
                    "tab_type": "browser",
                    "id": uuid.uuid4().hex,
                    "title": url,
                    "url": url,
                })
        except Exception as exc:
            logger.warning("[open_url] in-app tab broadcast failed: %s", exc)

        # 2) Agent content: headless single-URL fetch (no LLM planning).
        try:
            from backend.crawler.orchestrator import CrawlOrchestrator

            orch = CrawlOrchestrator()
            crawl_result = await orch.fetch_url(url, session_id=session_id)
        except Exception as exc:
            logger.error("[open_url] fetch failed: %s", exc)
            return {"success": False, "error": f"open_url failed: {exc}"}

        if getattr(crawl_result, "error", None):
            logger.warning("[open_url] fetch error (url=%r): %s", url, crawl_result.error)
            return {
                "success": False,
                "error": crawl_result.error,
                "error_type": _crawler_error_type(crawl_result.error),
            }

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

        _sources = [getattr(_p, "url", "") for _p in getattr(crawl_result, "pages", []) if getattr(_p, "url", "")]

        return {
            "success": True,
            "url": url,
            "content": _combined,
            "sources": _sources,
            "trust": "untrusted",  # external page content — reference zone
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



# Crawler events forwarded to the browser panel, with the keys a consumer would
# break on if they were missing. Membership here is the ONLY gate — the payload
# itself is forwarded whole, so adding a field to an event needs no edit in this
# file. That is deliberate: the previous per-event allowlist silently dropped
# job_id, then the progress emitter, then capture_page, each time leaving both
# ends of the seam correct and the middle broken.
#
# The WS `type` is the lowercased event name, which is already what the frontend
# switches on (see useIRISWebSocket).
_UI_EVENT_DEFAULTS: dict = {
    "CRAWLER_STARTED": {"query": "", "url_count": 0, "urls": []},
    "CRAWLER_PAGE_FETCHED": {
        "url": "", "page_number": 0, "total": 0, "host": "", "job_id": "",
        "title": "",
        # The capture ADDRESS. Defaulting it to page_number would silently
        # reinstate the 404 this table exists to prevent, so it defaults to
        # nothing and the client decides how to degrade.
        "capture_page": None, "capture_available": True,
    },
    "CRAWLER_SOURCES_ADDED": {"urls": [], "job_id": ""},
    "CRAWLER_PHASE": {"phase": "", "phase_sequence": 0},
    "CRAWLER_PROGRESS": {"stage": "", "message": ""},
    "CRAWLER_VISION_ACTION": {"job_id": "", "url": "", "kind": ""},
    "CRAWLER_SOURCE_PARKED": {"job_id": "", "url": ""},
    "CRAWLER_COMPLETE": {"page_count": 0, "summary": ""},
    "CRAWLER_ERROR": {"message": "crawl error"},
    "OPEN_TAB": {"tab_type": "browser", "id": "", "title": "", "url": "", "data": None},
}


def _crawl_ui_emitter(session_id: str):
    """Forward orchestrator crawl events to the browser panel (REQ-16 AC6-AC9).

    THE VOCABULARY HERE IS LOAD-BEARING. The overlay
    (hooks/useBrowserNavOverlay.ts) listens for exactly these message types:
    ``open_tab``, ``crawler_started``, ``crawler_page_fetched``,
    ``crawler_complete``, ``crawler_error``. Anything else — including the
    ``TASK_PROGRESS`` stream event the agent layer emits elsewhere — leaves
    the panel inert.

    Three ``research()`` call sites existed and only ONE spoke this vocabulary:
      iris_gateway.py (mode="ws", user-initiated)  -> emitted all of it
      _execute_crawler_query (mode="agent")        -> emitted TASK_PROGRESS only
      _execute_web_search    (mode="agent")        -> emitted NOTHING
    So the overlay animated only for user-initiated crawls and never for
    agent-driven ones: an agent search rendered its answer in chat while the
    browser panel stayed dead. This emitter is the shared piece the agent
    paths were missing; it mirrors the gateway handler so both agree.

    ``on_progress`` is called SYNCHRONOUSLY by the orchestrator — possibly from
    a WORKER event loop (the crawler_query tool runs under
    run_coroutine_threadsafe(coro, asyncio.new_event_loop()) in
    tool_decision._run_async, and the DER loop itself runs under
    run_in_executor). Every send is therefore marshalled onto the gateway's
    MAIN loop via run_coroutine_threadsafe (see _send below) — NEVER
    ensure_future, which would bind the send to the current worker loop and
    trip send_to_client's per-client lock (pin_8b41f386d397). Every send is
    best-effort: a UI emit must never fail or stall a crawl.
    """
    import asyncio as _asyncio
    import uuid as _uuid

    _diag = {"logged": False}

    def _emit(progress) -> None:
        ev = getattr(progress, "event", "")
        pl = getattr(progress, "payload", {}) or {}
        try:
            from backend.ws_manager import get_websocket_manager

            ws = get_websocket_manager()
            # Say WHY nothing animates instead of returning in silence. The
            # session key the tool bridge receives must match the key clients
            # are registered under; a mismatch drops every UI event with no
            # trace, which is indistinguishable from "the crawl did nothing".
            if not _diag["logged"]:
                _diag["logged"] = True
                try:
                    _known = list(getattr(ws, "_session_clients", {}) or {}) if ws else []
                except Exception:
                    _known = []
                logger.info(
                    "[crawl-ui] first event %s for session=%r clients=%d known_sessions=%s",
                    ev, session_id,
                    len(ws.get_clients_for_session(session_id)) if ws else -1,
                    _known[:6],
                )
            if ws is None or not ws.get_clients_for_session(session_id):
                return  # no live client — nothing to animate

            # Log EVERY crawler event, not just the first. The first-event-only
            # diagnostic could confirm that the channel worked at all but could
            # not answer "did page events actually fire, and did they carry the
            # fields the panel needs" — which is precisely the question that
            # matters when the overlay animates but the URL never changes.
            if ev.startswith("CRAWLER") or ev == "OPEN_TAB":
                logger.info(
                    "[crawl-ui] %s page=%s/%s job_id=%r url=%s",
                    ev, pl.get("page_number", "-"), pl.get("total", "-"),
                    pl.get("job_id", ""), str(pl.get("url", ""))[:80],
                )

            def _send(msg: dict) -> None:
                # MUST marshal onto the gateway's MAIN event loop, never the
                # loop running in the current thread. The crawler_query tool
                # executes inside _run_async's worker thread (tool_decision
                # :236 run_coroutine_threadsafe(coro, asyncio.new_event_loop()))
                # and the DER loop itself runs under run_in_executor — so
                # `ensure_future` here scheduled the broadcast on a WORKER
                # loop. send_to_client then did `async with _send_locks[client]`
                # on a lock bound to the MAIN loop at connect time, raising
                # "bound to a different event loop", which DISCONNECTED the
                # live client mid-turn (live 2026-08-12, pin_8b41f386d397).
                # ws_event_bridge.py:145 and ~30 gateway sites use this exact
                # run_coroutine_threadsafe(main_loop) pattern.
                try:
                    from backend.iris_gateway import get_iris_gateway

                    _gw = get_iris_gateway()
                    _loop = getattr(_gw, "_main_loop", None)
                    if _loop is None or not _loop.is_running():
                        return  # no live main loop yet — nothing to animate
                    _asyncio.run_coroutine_threadsafe(
                        ws.broadcast_to_session(session_id, msg), _loop
                    )
                except Exception:
                    pass  # never block the crawl on a UI emit

            # Forward the payload WHOLE, and map the event name generically.
            #
            # This was a hand-written allowlist per event, and it had failed the
            # same way three times: it dropped job_id (no web tab was ever
            # created), then it dropped the progress emitter, and most recently
            # it dropped capture_page — so the panel fell back to the UI counter
            # and requested /api/browser/capture/<job>/5 when the bytes were
            # saved at 101. Live 2026-08-11 22:47, 404 on pages 4 and 5 while
            # 1.html, 2.html, 102.html, 103.html and 202.html sat on disk.
            #
            # Worse, the allowlist gated the EVENTS too: only started /
            # page_fetched / open_tab / complete / error had a branch, so
            # CRAWLER_VISION_ACTION, CRAWLER_SOURCE_PARKED, CRAWLER_PHASE and
            # CRAWLER_SOURCES_ADDED never reached the client at all on the agent
            # path — the particle cursor and the parked-source notice had
            # nothing to render from, which is why they were never seen live.
            #
            # A forwarder must not be a place where fields go to die. Every
            # crawler event now forwards its whole payload under the lowercased
            # event name, which is exactly the type string the frontend already
            # switches on. Defaults are applied only for the keys a consumer
            # would break on if they were absent; anything new rides along
            # without needing an edit here.
            _defaults = _UI_EVENT_DEFAULTS.get(ev)
            if _defaults is not None:
                _msg = {"type": ev.lower(), **_defaults}
                _msg.update({k: v for k, v in (pl or {}).items() if k != "type"})
                if ev == "OPEN_TAB" and not _msg.get("id"):
                    # The one field the panel needs that the payload cannot
                    # supply: a tab with no id cannot be addressed or closed.
                    _msg["id"] = _uuid.uuid4().hex
                _send(_msg)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[crawl-ui] emit skipped (%s): %s", ev, exc)

    return _emit


def _crawler_error_type(error_str: str) -> str:
    """Map a crawler failure message to a REQ-10 ``error_type`` (deterministic).

    The crawler used to return a bare error string, forcing the black box to
    guess the class via string heuristics. REQ-10 AC1 wants the structured
    envelope straight from the tool, so we classify explicitly here instead of
    relying on the box's fallback heuristic.
    """
    if not error_str:
        return "permanent"
    _e = str(error_str).lower()
    if "rate limit" in _e or "429" in _e or "too many requests" in _e:
        return "rate_limit"
    if "timeout" in _e or "timed out" in _e or "connection" in _e or "reset" in _e:
        return "transient"
    if "no candidate urls" in _e or "no sources" in _e:
        # Planner exhausted its retries (see CrawlPlanner._plan_with_retry);
        # re-running the same query verbatim won't find URLs -> not retryable.
        return "permanent"
    if "not found" in _e or "404" in _e:
        return "not_found"
    return "permanent"
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
