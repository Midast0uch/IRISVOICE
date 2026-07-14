#!/usr/bin/env python3
"""
Tool Registry — single source of truth for agent tool capabilities.

Pillar A of the Agent + DER Unification Plan
(see docs/plans/2026-07-12-agent-der-unification.md).

Every tool the agent can call is described ONCE here as declarative
``ToolSpec`` metadata: pure data plus *string* executor references
(``executor`` / ``mcp_server`` / ``mcp_tool``).  That means this module can be
imported at startup WITHOUT pulling in any heavy internals (ML models, MCP
servers, GUI operators, the agent kernel).  Actual execution is resolved
lazily at call time by the dispatcher (tool_bridge.py), which is migrated to
read from this registry in Phase 2.

Design notes / deviations from the plan's illustrative dataclass:
  * ``permission_tier`` uses the LIVE ``PermissionTier`` values
    ("read_only" / "side_effect" / "destructive") from permissions.py, not the
    plan's illustrative "low" / "medium" / "high".  This lets Phase 2's
    ``classify_tool`` read the tier directly without a mapping layer.
  * ``capability_allowed`` reads capability flags through injectable provider
    functions (``set_capability_providers``) instead of importing
    ``agent_kernel`` directly.  This (a) avoids an import cycle, (b) keeps this
    module importable with zero heavy side-effects, and (c) makes the gate
    trivially unit-testable.  The kernel wires the real providers at startup
    (Phase 2).
  * Two extra fields support later phases:
      - ``critical``      — Caducean COMPRESS queue modulation (Phase 5) keeps
                            only critical=True steps when rec == 1 (COMPRESS).
      - ``parallel_safe`` — Phase 4 concurrent execution runs parallel_safe
                            tools via asyncio.gather.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = __name__ if isinstance(__name__, str) else "tool_registry"
import logging
logger = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    """Declarative description of a single agent tool."""

    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    category: str = "system"
    aliases: List[str] = field(default_factory=list)
    requires_internet: bool = False
    requires_desktop: bool = False
    # Live PermissionTier values from permissions.py: read_only | side_effect | destructive
    permission_tier: str = "read_only"
    # Where/how the tool executes.  Pure string refs — no heavy imports.
    executor: str = "internal"          # internal | mcp | dev | crawler | research | memory
    mcp_server: Optional[str] = None
    mcp_tool: Optional[str] = None
    # Caducean COMPRESS keeps only critical steps (Phase 5)
    critical: bool = False
    # Phase 4 concurrent execution: safe to run via asyncio.gather
    parallel_safe: bool = False


# ── Registry storage ────────────────────────────────────────────────────────
_REGISTRY: Dict[str, ToolSpec] = {}
_ALIAS_INDEX: Dict[str, str] = {}

# Capability flag providers — injected at runtime to avoid an import cycle with
# agent_kernel.  Defaults are permissive so the registry is usable before wiring.
_internet_provider: Callable[[], bool] = lambda: True
_desktop_provider: Callable[[], bool] = lambda: True


def set_capability_providers(
    internet: Optional[Callable[[], bool]] = None,
    desktop: Optional[Callable[[], bool]] = None,
) -> None:
    """Wire the real capability-flag getters (called once at kernel startup)."""
    global _internet_provider, _desktop_provider
    if internet is not None:
        _internet_provider = internet
    if desktop is not None:
        _desktop_provider = desktop


def register_tool(spec: ToolSpec) -> ToolSpec:
    """Register a tool spec.  Idempotent; rebuilds the alias index."""
    _REGISTRY[spec.name] = spec
    for alias in spec.aliases:
        _ALIAS_INDEX[alias] = spec.name
    return spec


def resolve_tool(name: str) -> Optional[ToolSpec]:
    """Normalize a tool name (alias-aware) to its canonical ToolSpec.

    Returns None if the name is unknown (and not a known alias).
    """
    if name in _REGISTRY:
        return _REGISTRY[name]
    if name in _ALIAS_INDEX:
        return _REGISTRY[_ALIAS_INDEX[name]]
    return None


def validate_tool_call(
    tool_name: str, params: Optional[Dict[str, Any]]
) -> "tuple[bool, str]":
    """Pre-execution validation for a planned step (RC1).

    Returns (is_valid, error_message). The dominant permanent-error class is an
    UNKNOWN tool name (the historical ``tool:null`` bug) — a step that names a
    tool the registry has never heard of can never succeed, so it is routed to
    graft recovery before execution instead of failing at runtime.

    NOTE: parameter *requiredness* is intentionally NOT enforced here. The
    registry's ``ToolSpec.parameters`` dict does not distinguish required from
    optional parameters (e.g. ``speak`` declares ``text``/``priority``/
    ``interrupt`` but only ``text`` is meaningfully required), so treating every
    declared parameter as required would wrongly reject valid calls. Tool
    existence is the safe, high-leverage check; parameter shaping remains the
    LLM planner's responsibility.
    """
    spec = resolve_tool(tool_name)
    if spec is None:
        return False, f"Tool '{tool_name}' not found in registry"
    if params is not None and not isinstance(params, dict):
        return False, f"Tool '{tool_name}' params must be a dict, got {type(params).__name__}"
    return True, ""


def capability_allowed(spec: ToolSpec) -> bool:
    """Declarative gate consolidation (Pillar A).

    Replaces the scattered InternetGate / DesktopGate checks in tool_bridge
    with one capability check.  Reads flags through injected providers so this
    module never imports agent_kernel.
    """
    if spec.requires_internet and not _internet_provider():
        return False
    if spec.requires_desktop and not _desktop_provider():
        return False
    return True


def is_parallel_safe(tool_name: Optional[str]) -> bool:
    """Phase 4b: authoritative source of truth for concurrent execution.

    A step is safe to run concurrently with other ready steps IFF its tool is
    routed to an MCP server OR its registry spec is marked ``parallel_safe``.
    This is the single gate the DER loop uses to decide whether a step may
    enter the concurrent batch — it does NOT rely on the LLM planner emitting
    the flag (which was unreliable).

    Routing-based rule (general policy): any tool executed by a registered /
    connected MCP server (vision, browser, file_manager, system, app_launcher,
    gui_automation, github, internal, and any future server such as Blender)
    is ``parallel_safe`` — each MCP server is an independent process/connection
    that handles concurrent calls.  Ordering of steps that genuinely depend on
    each other is enforced by the DER dependency graph (``depends_on``), not by
    serializing here.  Non-MCP tools fall back to their explicit
    ``parallel_safe`` flag (mutating/stateful tools such as run_command,
    git_commit, gui click, crawler_query are False).

    Returns False for unknown / None tools (fail-closed — never parallelize an
    unrecognized tool).
    """
    if not tool_name:
        return False
    spec = resolve_tool(tool_name)
    if spec is None:
        return False
    # MCP-executed tools run in independent server processes -> safe to parallelize
    # by default.  Exception: destructive SYSTEM-control tools (shutdown/restart/
    # lock) act on the whole machine, so they must stay serial even though MCP.
    if spec.executor == "mcp" or getattr(spec, "mcp_server", None):
        if getattr(spec, "mcp_server", None) == "system" and spec.permission_tier == "destructive":
            return False
        return True
    return bool(spec.parallel_safe)


def get_all_specs() -> List[ToolSpec]:
    """All registered specs (no gating).  Primarily for tests / introspection."""
    return list(_REGISTRY.values())


def get_registry_tools() -> List[Dict[str, Any]]:
    """LLM-facing tool descriptors for function calling.

    Drop-in replacement for ``AgentToolBridge.get_available_tools``:
      * capability gate (internet / desktop) via ``capability_allowed``
      * developer-only tool filtering via CapabilitySet (personal mode)
    Mirrors the shape get_available_tools() returns so the LLM sees identical
    tool schemas.
    """
    out: List[Dict[str, Any]] = []
    for spec in _REGISTRY.values():
        if not capability_allowed(spec):
            continue
        # [13.3] Runtime capability gate — developer-only tools blocked in personal mode
        try:
            from backend.capabilities import CapabilitySet
            if not CapabilitySet.is_tool_allowed(spec.name):
                continue
        except Exception:
            pass  # if CapabilitySet is unavailable, expose the tool
        tool = {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
            "category": spec.category,
        }
        if spec.mcp_server:
            tool["server"] = spec.mcp_server
        out.append(tool)
    return out


# ── Builtin tool registration ─────────────────────────────────────────────────
def register_builtin_tools() -> None:
    """Register every core backend tool as a ToolSpec.

    Pure data only — no heavy imports.  Safe to call at module import.
    Metadata is transcribed from AgentToolBridge.get_available_tools() and the
    execute_tool() dispatch map in tool_bridge.py so the registry is the single
    source of truth.
    """
    specs: List[ToolSpec] = []

    # ── Vision (routed to the vision MCP server) ─────────────────────────────
    specs += [
        ToolSpec(
            name="vision_detect_element",
            description="Detect a GUI element in a screenshot by description",
            parameters={"description": {"type": "string", "description": "Element to find"}},
            category="vision", executor="mcp", mcp_server="vision",
            mcp_tool="vision.find_ui_element", parallel_safe=True,
        ),
        ToolSpec(
            name="vision_analyze_screen",
            description="Analyze the current screen and describe what's visible",
            parameters={}, category="vision", executor="mcp", mcp_server="vision",
            mcp_tool="vision.analyze_screen", parallel_safe=True,
        ),
        ToolSpec(
            name="vision_validate_action",
            description="Validate if an action can be performed on an element",
            parameters={
                "action": {"type": "string", "description": "Action (click, type, etc.)"},
                "target": {"type": "string", "description": "Element description"},
            },
            category="vision", executor="mcp", mcp_server="vision",
            mcp_tool="vision.suggest_next_action", parallel_safe=True,
        ),
        ToolSpec(
            name="vision_get_context",
            description="Get current screen context from VisionSystem",
            parameters={}, category="vision", executor="mcp", mcp_server="vision",
            mcp_tool="vision.describe_live_frame", parallel_safe=True,
        ),
    ]

    # ── Screen (desktop-control, routed to the GUI operator) ─────────────────
    specs += [
        ToolSpec(
            name="take_screenshot",
            description="Take a screenshot of the current screen",
            parameters={}, category="vision", executor="gui",
            requires_desktop=True, parallel_safe=False,
        ),
        ToolSpec(
            name="start_screen_monitor",
            description="Start background screen monitoring for proactive help",
            parameters={"interval": {"type": "integer", "description": "Check interval in seconds"}},
            category="vision", executor="gui", requires_desktop=True, parallel_safe=False,
        ),
    ]

    # ── WEB / GUI control (desktop-control) ──────────────────────────────────
    specs += [
        ToolSpec(
            name="gui_click",
            description="Click at coordinates or on an element",
            parameters={"x": {"type": "integer"}, "y": {"type": "integer"}},
            category="web", executor="gui", requires_desktop=True, parallel_safe=False,
        ),
        ToolSpec(
            name="gui_type",
            description="Type text at current position or coordinates",
            parameters={
                "text": {"type": "string"},
                "x": {"type": "integer", "optional": True},
                "y": {"type": "integer", "optional": True},
            },
            category="web", executor="gui", requires_desktop=True, parallel_safe=False,
        ),
        ToolSpec(
            name="gui_press_key",
            description="Press a keyboard key",
            parameters={"key": {"type": "string", "description": "Key name (ctrl, enter, etc.)"}},
            category="web", executor="gui", requires_desktop=True, parallel_safe=False,
        ),
    ]

    # ── MCP tools (browser / file / system / app / github / gui_automation) ──
    specs += [
        ToolSpec(
            name="create_skill",
            description="Create a new learned skill",
            parameters={"name": {"type": "string"}, "content": {"type": "string"}},
            category="system", executor="mcp", mcp_server="internal", mcp_tool="create_skill",
        ),
        ToolSpec(
            name="open_url",
            description="Open URL in browser",
            parameters={"url": {"type": "string"}},
            category="web", executor="mcp", mcp_server="browser", mcp_tool="open_url",
            requires_desktop=True,
        ),
        ToolSpec(
            name="read_file",
            description="Read file contents",
            parameters={"path": {"type": "string"}},
            category="file", executor="mcp", mcp_server="file_manager", mcp_tool="read_file",
            permission_tier="read_only", parallel_safe=True, critical=True,
        ),
        ToolSpec(
            name="write_file",
            description="Write to file",
            parameters={"path": {"type": "string"}, "content": {"type": "string"}},
            category="file", executor="mcp", mcp_server="file_manager", mcp_tool="write_file",
            permission_tier="side_effect",
        ),
        ToolSpec(
            name="list_directory",
            description="List directory",
            parameters={"path": {"type": "string"}},
            category="file", executor="mcp", mcp_server="file_manager", mcp_tool="list_directory",
            permission_tier="read_only", parallel_safe=True,
        ),
        ToolSpec(
            name="create_directory",
            description="Create directory",
            parameters={"path": {"type": "string"}},
            category="file", executor="mcp", mcp_server="file_manager", mcp_tool="create_directory",
            permission_tier="side_effect",
        ),
        ToolSpec(
            name="delete_file",
            description="Delete file/directory",
            parameters={"path": {"type": "string"}},
            category="file", executor="mcp", mcp_server="file_manager", mcp_tool="delete_file",
            permission_tier="destructive",
        ),
        ToolSpec(
            name="get_system_info",
            description="Get system information",
            parameters={}, category="system", executor="mcp", mcp_server="system",
            mcp_tool="get_system_info", permission_tier="read_only", parallel_safe=True,
        ),
        ToolSpec(
            name="lock_screen",
            description="Lock the screen",
            parameters={}, category="system", executor="mcp", mcp_server="system",
            mcp_tool="lock", requires_desktop=True, permission_tier="destructive", parallel_safe=False,
        ),
        ToolSpec(
            name="shutdown",
            description="Shutdown system",
            parameters={"delay": {"type": "integer", "optional": True}},
            category="system", executor="mcp", mcp_server="system", mcp_tool="shutdown",
            requires_desktop=True, permission_tier="destructive", parallel_safe=False,
        ),
        ToolSpec(
            name="restart",
            description="Restart system",
            parameters={"delay": {"type": "integer", "optional": True}},
            category="system", executor="mcp", mcp_server="system", mcp_tool="restart",
            requires_desktop=True, permission_tier="destructive", parallel_safe=False,
        ),
        ToolSpec(
            name="launch_app",
            description="Launch an application",
            parameters={"app_name": {"type": "string"}},
            category="app", executor="mcp", mcp_server="app_launcher", mcp_tool="launch_app",
            requires_desktop=True, parallel_safe=False,
        ),
        ToolSpec(
            name="open_file",
            description="Open file with default app",
            parameters={"file_path": {"type": "string"}},
            category="app", executor="mcp", mcp_server="app_launcher", mcp_tool="open_file",
            requires_desktop=True, parallel_safe=False,
        ),
        # GitHub (PAT-based)
        ToolSpec(
            name="github_get_user",
            description="Get authenticated GitHub user info",
            parameters={}, category="github", executor="mcp", mcp_server="github",
            mcp_tool="github_get_user", permission_tier="read_only", parallel_safe=True,
        ),
        ToolSpec(
            name="github_list_repos",
            description="List user's GitHub repositories",
            parameters={}, category="github", executor="mcp", mcp_server="github",
            mcp_tool="github_list_repos", permission_tier="read_only", parallel_safe=True,
        ),
        ToolSpec(
            name="github_get_repo_branches",
            description="List branches for a GitHub repo",
            parameters={"repo_full_name": {"type": "string"}},
            category="github", executor="mcp", mcp_server="github",
            mcp_tool="github_get_repo_branches", permission_tier="read_only", parallel_safe=True,
        ),
        ToolSpec(
            name="github_generate_ssh_key",
            description="Generate SSH key for GitHub",
            parameters={"name": {"type": "string"}, "key_type": {"type": "string"}},
            category="github", executor="mcp", mcp_server="github",
            mcp_tool="github_generate_ssh_key", permission_tier="side_effect", parallel_safe=False,
        ),
        ToolSpec(
            name="github_list_ssh_keys",
            description="List generated SSH keys",
            parameters={}, category="github", executor="mcp", mcp_server="github",
            mcp_tool="github_list_ssh_keys", permission_tier="read_only", parallel_safe=True,
        ),
        ToolSpec(
            name="github_delete_ssh_key",
            description="Delete a generated SSH key",
            parameters={"name": {"type": "string"}},
            category="github", executor="mcp", mcp_server="github",
            mcp_tool="github_delete_ssh_key", permission_tier="destructive", parallel_safe=False,
        ),
        ToolSpec(
            name="github_connect_pat",
            description="Connect to GitHub with a PAT",
            parameters={"token": {"type": "string"}},
            category="github", executor="mcp", mcp_server="github",
            mcp_tool="github_connect_pat", permission_tier="side_effect", parallel_safe=False,
        ),
        # GUI Automation
        ToolSpec(
            name="gui_automate_click",
            description="Automated GUI click",
            parameters={"x": {"type": "integer"}, "y": {"type": "integer"}},
            category="gui", executor="mcp", mcp_server="gui_automation", mcp_tool="click",
            requires_desktop=True, parallel_safe=False,
        ),
        ToolSpec(
            name="gui_automate_type",
            description="Automated GUI typing",
            parameters={"text": {"type": "string"}},
            category="gui", executor="mcp", mcp_server="gui_automation", mcp_tool="type",
            requires_desktop=True, parallel_safe=False,
        ),
    ]

    # ── Git + Shell (developer mode, executed via subprocess) ────────────────
    specs += [
        ToolSpec(
            name="git_status",
            description="Show working tree status (staged, unstaged, untracked files)",
            parameters={"repo_path": {"type": "string", "description": "Absolute path to the git repo (optional, defaults to IRISVOICE root)"}},
            category="git", executor="dev", permission_tier="read_only", parallel_safe=True, critical=True,
        ),
        ToolSpec(
            name="git_diff",
            description="Show diff of staged or unstaged changes",
            parameters={
                "repo_path": {"type": "string"},
                "staged": {"type": "boolean", "description": "If true, show staged diff; otherwise unstaged"},
            },
            category="git", executor="dev", permission_tier="read_only", parallel_safe=True,
        ),
        ToolSpec(
            name="git_log",
            description="Show recent commit history",
            parameters={
                "repo_path": {"type": "string"},
                "n": {"type": "integer", "description": "Number of commits to show (default 10)"},
            },
            category="git", executor="dev", permission_tier="read_only", parallel_safe=True,
        ),
        ToolSpec(
            name="git_commit",
            description="Stage all changed files and create a commit",
            parameters={
                "message": {"type": "string", "description": "Commit message"},
                "repo_path": {"type": "string"},
            },
            category="git", executor="dev", permission_tier="side_effect", parallel_safe=False,
        ),
        ToolSpec(
            name="git_create_branch",
            description="Create and switch to a new branch",
            parameters={
                "branch": {"type": "string", "description": "New branch name"},
                "repo_path": {"type": "string"},
            },
            category="git", executor="dev", permission_tier="side_effect", parallel_safe=False,
        ),
        ToolSpec(
            name="git_checkout",
            description="Switch to an existing branch",
            parameters={"branch": {"type": "string"}, "repo_path": {"type": "string"}},
            category="git", executor="dev", permission_tier="side_effect", parallel_safe=False,
        ),
        ToolSpec(
            name="git_push",
            description="Push current branch to origin",
            parameters={
                "repo_path": {"type": "string"},
                "force": {"type": "boolean", "description": "Force push (default false)"},
            },
            category="git", executor="dev", permission_tier="side_effect", parallel_safe=False,
        ),
        ToolSpec(
            name="run_command",
            description="Run a shell command in the project directory (npm, python, pytest, etc.)",
            parameters={
                "command": {"type": "string", "description": "Command to run"},
                "cwd": {"type": "string", "description": "Working directory (defaults to IRISVOICE root)"},
            },
            category="shell", executor="dev", permission_tier="side_effect", parallel_safe=False,
        ),
    ]

    # ── Memory / Research / Internal ─────────────────────────────────────────
    specs += [
        ToolSpec(
            name="recall_memory",
            description=(
                "Search long-term episodic memory for relevant past context, "
                "solutions, or patterns. Use when you need prior knowledge for the current sub-task."
            ),
            parameters={"query": {"type": "string", "description": "What to search for"}},
            category="memory", executor="memory", permission_tier="read_only",
            parallel_safe=True, critical=True,
        ),
        ToolSpec(
            name="run_research",
            description=(
                "Run the AutoResearch improvement loop on anything — skills, behaviours, explanations, "
                "processes, response styles, or any topic you want to get better at. "
                "Use action='run_now' with topic+content to immediately research and improve any text or concept. "
                "Use action='start' to begin the background timer loop (auto-picks the lowest-confidence stored item each cycle), "
                "action='stop' to halt it, or action='status' to see recent results."
            ),
            parameters={
                "action": {"type": "string", "enum": ["run_now", "start", "stop", "status"], "description": "What to do"},
                "topic": {"type": "string", "description": "What to improve — a short label like 'Python debugging' or 'response formatting'. Used with run_now."},
                "content": {"type": "string", "description": "The current version of the text/concept to improve. If omitted, picks the lowest-confidence item from memory. Used with run_now."},
                "test_prompts": {"type": "array", "items": {"type": "string"}, "description": "Optional: custom test prompts to benchmark variants against (only used with run_now)"},
                "interval": {"type": "number", "description": "Optional: loop interval in seconds when using action=start (default 1800)"},
            },
            category="research", executor="research", permission_tier="side_effect", parallel_safe=False,
        ),
        ToolSpec(
            name="ask_user_question",
            description="Ask the user a question mid-task. Requires user input.",
            parameters={
                "text": {"type": "string", "description": "The question to ask"},
                "options": {"type": "array", "items": {"type": "string"}, "description": "Optional: multiple-choice options"},
                "allow_other": {"type": "boolean", "description": "Allow free-form input (default: true)"},
            },
            category="system", executor="internal", permission_tier="read_only", parallel_safe=False,
        ),
        ToolSpec(
            name="speak",
            description=(
                "Speak text aloud via TTS. You may proactively call this at ANY time and for ANY "
                "reason — to raise a concern, flag a risk, give feedback, ask for attention, or share "
                "a status update — not only at the end of a task. Use it whenever the user should HEAR "
                "something without reading. Fire-and-forget: returns immediately and never blocks. "
                "Text is capped at 500 chars. The same spoken words are also delivered to any connected "
                "external channels (e.g. Telegram) so the user hears you there too."
            ),
            parameters={
                "text": {"type": "string", "description": "The text to speak (max 500 characters)"},
                "priority": {"type": "string", "enum": ["normal", "high", "low"], "description": "Speech priority (default: normal)"},
                "interrupt": {"type": "boolean", "description": "If true and priority is high, interrupt current TTS to speak immediately (default: false)"},
            },
            category="system", executor="internal", permission_tier="read_only", parallel_safe=True,
        ),
    ]

    # ── Internet-gated web tools (aliased to fix the legacy name mismatch) ───
    specs += [
        ToolSpec(
            name="search",
            description="Search the web for a quick factual answer. Returns fetched page content as markdown.",
            parameters={"query": {"type": "string"}},
            category="web", executor="internal", requires_internet=True,
            aliases=["web_search", "google_search"], parallel_safe=True, critical=True,
        ),
        ToolSpec(
            name="crawler_query",
            description=(
                "Deep web research crawl for a topic. Plans source URLs from the query, "
                "crawls them with Crawl4AI, and returns a structured summary PLUS the full "
                "extracted page content (field 'content') with source links. Put 'content' "
                "in your 'show' field and 'summary' in 'speak'. Use for 'research', "
                "'everything about', or 'deep dive' requests — NOT for a quick factual "
                "lookup (use 'search' for that)."
            ),
            parameters={"query": {"type": "string", "description": "The research topic or question to investigate"}},
            category="web", executor="crawler", requires_internet=True, parallel_safe=False, critical=True,
        ),
    ]

    # ── Multimedia tools (Phase 5.2 / research D2) ───────────────────────────
    specs += [
        ToolSpec(
            name="transcribe_media",
            description=(
                "Transcribe an audio or video file to text using the local Parakeet "
                "ASR service. Automatically chunks long media into <=60s segments. "
                "Input is a local file path. Returns the full transcript, detected "
                "language, and duration."
            ),
            parameters={
                "audio_path": {"type": "string", "description": "Path to the audio/video file to transcribe"},
                "chunk_seconds": {"type": "integer", "description": "Max seconds per ASR chunk (default 55)", "default": 55},
            },
            category="media", executor="internal", requires_internet=False,
            parallel_safe=False, critical=False,
        ),
        ToolSpec(
            name="analyze_video_frames",
            description=(
                "Sample frames from a video at a fixed interval and run vision "
                "analysis on each frame (describe content, read text, detect objects). "
                "Returns per-frame answers and an aggregated summary. Use for "
                "'what happens in this video' or 'summarize the screen recording'."
            ),
            parameters={
                "video_path": {"type": "string", "description": "Path to the video file"},
                "question": {"type": "string", "description": "Question to ask about each frame", "default": "What is happening in this frame?"},
                "frame_interval": {"type": "number", "description": "Seconds between sampled frames (default 1.0)", "default": 1.0},
            },
            category="media", executor="internal", requires_internet=False,
            parallel_safe=False, critical=False,
        ),
        ToolSpec(
            name="clip_video",
            description=(
                "Trim a video to a sub-clip using ffmpeg. Input start/end as "
                "HH:MM:SS or seconds. Returns the output file path."
            ),
            parameters={
                "video_path": {"type": "string", "description": "Path to the source video"},
                "start": {"type": "string", "description": "Start time (HH:MM:SS or seconds)"},
                "end": {"type": "string", "description": "End time (HH:MM:SS or seconds)"},
                "output_path": {"type": "string", "description": "Destination path for the trimmed clip"},
            },
            category="media", executor="internal", requires_internet=False,
            parallel_safe=False, critical=False,
        ),
    ]

    for spec in specs:
        register_tool(spec)


# Populate the registry on import — pure data, no heavy side-effects.
register_builtin_tools()
