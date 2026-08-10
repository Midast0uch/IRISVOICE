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
    # Long-running tools (e.g. crawler_query) may block for up to a minute. When
    # True, execute_tool wraps the run with a periodic narration heartbeat so the
    # user hears progress instead of silence. This is a tool CAPABILITY, not a
    # mode check — the DER operator reads it uniformly (blueprint: no mode-driven
    # fan-out; all behavior collapses into the one operator). See pin_9e97e21340e7.
    long_running: bool = False


# ── Registry storage ────────────────────────────────────────────────────────
_REGISTRY: Dict[str, ToolSpec] = {}
_ALIAS_INDEX: Dict[str, str] = {}

# Capability flag providers — injected at runtime to avoid an import cycle with
# agent_kernel.  Defaults are FAIL-CLOSED: if a provider is not wired, the
# capability is DENIED.  The web-mode gate is an open/close switch controlled by
# the frontend toggle (set_web_mode -> set_global_internet_access). When unwired
# or off, the agent must have ZERO internet tools — never fail open
# (see pin_9e97e21340e7).
_internet_provider: Callable[[], bool] = lambda: False
_desktop_provider: Callable[[], bool] = lambda: False


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


# ── Node metadata (REQ-2, specs/dag-node-execution-model) ─────────────────
# The registry carries OPTIONAL node metadata. A tool that never declares a
# NodeSpec behaves exactly as it does today (REQ-7 AC1 — strangler-fig); a
# declared node gains routable outcomes, artifact types, and advertised
# recovery (REQ-2 AC2). REQ-2 AC1: this extends the EXISTING registry — no
# third registry.
_NODE_SPECS: Dict[str, "NodeSpec"] = {}


def register_node(spec: "NodeSpec") -> "NodeSpec":
    """Register node metadata for an already-registered tool.

    REQ-2 edge / CT-8: two nodes registering the same name is forbidden —
    registration FAILS LOUDLY at startup rather than silently shadowing.
    (Deliberately NOT idempotent, unlike ``register_tool``: a duplicate node
    declaration is a programming error, not a rebuild artifact.)

    The underlying ToolSpec must already exist in the registry (its fields are
    the node's execution contract); registering node metadata for an unknown
    tool is also a loud failure, never a silent orphan.
    """
    from backend.agent.nodes.spec import NodeSpec  # lazy — no import cycle

    if not isinstance(spec, NodeSpec):
        raise TypeError(
            f"register_node requires a NodeSpec, got {type(spec).__name__}"
        )
    if spec.name not in _REGISTRY:
        raise ValueError(
            f"register_node({spec.name!r}): no ToolSpec registered for this name; "
            f"register the tool first"
        )
    if spec.name in _NODE_SPECS:
        raise ValueError(
            f"register_node({spec.name!r}): duplicate node registration — a node "
            f"name may be registered exactly once (REQ-2 edge, CT-8)"
        )
    _NODE_SPECS[spec.name] = spec
    # Wire the node into the router's advertisement table (REQ-4 AC1).
    try:
        from backend.agent.nodes.router import get_node_router

        get_node_router().register_node(spec)
    except Exception:  # pragma: no cover - router wiring is best-effort
        logger.warning("register_node(%s): router wiring deferred", spec.name)
    return spec


def get_node_spec(name: str) -> Optional["NodeSpec"]:
    """Node metadata for *name*, or None when the tool is undeclared (REQ-2 AC5)."""
    return _NODE_SPECS.get(name)


def get_all_node_specs() -> List["NodeSpec"]:
    """Every declared node spec (REQ-2 AC2/AC3 introspection)."""
    return list(_NODE_SPECS.values())


def declare_default_node_metadata() -> int:
    """Declare NodeSpecs for tools that are first-class nodes by registration
    alone (REQ-6 AC4 — no backend code change; the modules stay untouched).

    This is the REQ-6 proof: the five ``vision.*`` MCP tools, the media
    (audio/parakeet) tools, and the web tools become nodes purely by declaring
    their artifact types and advertised recovery here. Registration is
    idempotent (a tool already declared is skipped). Returns the number of
    declarations applied.
    """
    from backend.agent.nodes.outcome import Reason  # lazy — no import cycle
    from backend.agent.nodes.spec import NodeSpec

    _declared = 0
    # Artifact kind per tool: what the node produces (REQ-6 AC2).
    # NOTE: crawler_query's NodeSpec is owned by the capabilities facade
    # (_register_crawler_query_composite — it carries composite_of metadata);
    # declaring it here too would trip register_node's duplicate guard (CT-8).
    _produce: Dict[str, str] = {
        # vision.* MCP tools -> "frames" / "text" artifacts
        "vision_detect_element": "text",
        "vision_analyze_screen": "text",
        "vision_validate_action": "text",
        "vision_get_context": "text",
        # media / parakeet pipeline -> large artifacts by REFERENCE (D7)
        "transcribe_media": "audio_ref",
        "analyze_video_frames": "video_ref",
        "clip_video": "video_ref",
        # web tools
        "search": "pages",
        # memory / research
        "recall_memory": "text",
        "improve_self": "text",
    }
    # Nodes whose backing service can be absent -> UNAVAILABLE + route around
    # (REQ-6 AC5): vision tools emit UPSTREAM_ERROR when the vision server is
    # down; media tools likewise.
    _emits: Dict[str, frozenset] = {
        "vision_detect_element": frozenset({Reason.UPSTREAM_ERROR}),
        "vision_analyze_screen": frozenset({Reason.UPSTREAM_ERROR}),
        "vision_validate_action": frozenset({Reason.UPSTREAM_ERROR}),
        "vision_get_context": frozenset({Reason.UPSTREAM_ERROR}),
        "transcribe_media": frozenset({Reason.UPSTREAM_ERROR, Reason.NO_CANDIDATES}),
        "analyze_video_frames": frozenset({Reason.UPSTREAM_ERROR, Reason.NO_CANDIDATES}),
        "clip_video": frozenset({Reason.UPSTREAM_ERROR}),
        "search": frozenset({Reason.NO_CANDIDATES, Reason.TRANSPORT_ERROR}),
    }
    for _name, _prod in _produce.items():
        if _name in _NODE_SPECS:
            continue
        _spec = _REGISTRY.get(_name)
        if _spec is None:
            continue  # tool not registered — nothing to declare
        try:
            register_node(NodeSpec(
                tool=_spec,
                produces=_prod,
                emits_reasons=_emits.get(_name, frozenset()),
                recovers_reasons=frozenset(),
            ))
            _declared += 1
        except Exception:  # pragma: no cover - best-effort declaration
            logger.warning("declare_default_node_metadata(%s) failed", _name)
    return _declared


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


def capability_denied_by(spec: ToolSpec) -> Optional[str]:
    """Name the capability that actually denies a spec, or None if allowed.

    Unlike ``capability_allowed`` (a boolean), this tells the caller WHICH
    gate closed — "internet" or "desktop" — so the error message matches the
    real cause. REQ-16/T29: ``open_url`` now sets BOTH flags, so a
    flag-presence check alone cannot tell internet-denied from
    desktop-denied; the dispatcher uses this to report the true blocker.
    """
    if spec.requires_internet and not _internet_provider():
        return "internet"
    if spec.requires_desktop and not _desktop_provider():
        return "desktop"
    return None


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
            description=(
                "Capture a screenshot of the user's screen so IRIS can SEE what is "
                "on the desktop. ONLY use when the user explicitly wants IRIS to look "
                "at or interact with the screen (e.g. 'look at my screen', 'what's on "
                "my desktop', 'click that button'). For FINDING INFORMATION or ANSWERING "
                "QUESTIONS, use the 'web_search' tool (exa) instead — do NOT screenshot "
                "to research a topic."
            ),
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
            description="Open URL in the in-app browser surface",
            parameters={"url": {"type": "string"}},
            category="web", executor="mcp", mcp_server="browser", mcp_tool="open_url",
            # REQ-16 AC3 (T29): open_url is gated like every other network tool —
            # requires internet access. requires_desktop stays True (the tool is
            # still listed under desktop-control tools); the gate reports the
            # ACTUAL denying capability via capability_denied_by().
            requires_internet=True,
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
            name="improve_self",
            description=(
                "SELF-IMPROVEMENT ONLY — does NOT browse the web or fetch external information. "
                "Improves the agent's own skills, behaviours, explanations, processes, or response "
                "styles using locally stored benchmark prompts (AutoResearch loop). "
                "Use action='run_now' with topic+content to improve a specific piece of text/concept, "
                "action='start' for the background timer loop, action='stop' to halt it, or "
                "action='status' for recent results. "
                "For fetching real-world data, web pages, or researching a company/topic from the internet, "
                "use 'crawler_query' instead — this tool cannot access the web."
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
            description="Ask the user a question mid-task. Requires user input. "
                        "Pass non_blocking=true (with parked_url + run_id) to raise the "
                        "question card and return immediately so the task keeps going; "
                        "the parked source is resumed when the answer arrives.",
            parameters={
                "text": {"type": "string", "description": "The question to ask"},
                "options": {"type": "array", "items": {"type": "string"}, "description": "Optional: multiple-choice options"},
                "allow_other": {"type": "boolean", "description": "Allow free-form input (default: true)"},
                "non_blocking": {"type": "boolean", "description": "If true, raise the card and return immediately (REQ-13 AC1)"},
                "parked_url": {"type": "string", "description": "Source URL to park behind the question (REQ-13 AC2)"},
                "run_id": {"type": "string", "description": "Research run id for the parked-source registry (REQ-13 AC6)"},
                "wall_kind": {"type": "string", "enum": ["captcha", "login", "paywall", "unknown"], "description": "Wall that blocked the source (REQ-13)"},
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
        ToolSpec(
            name="get_rendered_documents",
            description=(
                "Return the active conversation's rendered document DATA (content, "
                "variants, sources, source_document_id, har_path) so you can recombine "
                "or re-render prior documents. Use this when the user asks to 'combine', "
                "'merge', or 'reuse' earlier documents, or when you need a document's "
                "provenance/HAR to decide if a source is stale. Returns FULL data (not "
                "the light UI metadata). Cross-thread capable: if ``conversation_id`` is "
                "provided it returns THAT thread's documents (use ``list_conversations`` "
                "to discover prior threads); otherwise the active conversation's."
            ),
            parameters={
                "conversation_id": {
                    "type": "string",
                    "description": "Optional: conversation to read (defaults to the active conversation). Pass a different thread's id to reuse its existing rendered data.",
                },
            },
            category="memory", executor="internal", requires_internet=False,
            permission_tier="read_only", parallel_safe=True,
        ),
        ToolSpec(
            name="list_conversations",
            description=(
                "List every conversation thread that has at least one rendered "
                "document, newest-first (returns conversation_id, doc_count, "
                "latest_created_at). Use this to DISCOVER prior threads — e.g. when "
                "the user says 'continue the previous task' or 'use the document from "
                "before' — then call get_rendered_documents(conversation_id=...) on the "
                "relevant thread to pull its EXISTING data instead of re-searching the "
                "web. Cross-thread discovery; read-only."
            ),
            parameters={},
            category="memory", executor="internal", requires_internet=False,
            permission_tier="read_only", parallel_safe=True,
        ),
        ToolSpec(
            name="combine_documents",
            description=(
                "Combine several rendered documents into ONE new render (the "
                "'combine A + B' path). Content is concatenated and the SOURCE "
                "list is the union of all inputs, so provenance is preserved on "
                "the combined doc. Use this when the user asks to 'merge', "
                "'combine', or 'summarize together' earlier documents. Local "
                "operation — does not re-crawl; consult HAR before any re-crawl."
            ),
            parameters={
                "document_ids": {
                    "type": "array",
                    "description": "Document IDs to combine (order preserved)",
                    "items": {"type": "string"},
                },
                "conversation_id": {
                    "type": "string",
                    "description": "Optional: conversation to write into (defaults to active)",
                },
            },
            category="memory", executor="internal", requires_internet=False,
            permission_tier="read_only", parallel_safe=False,
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
                "DEEP WEB RESEARCH CRAWL — the tool to use when the user wants real-world data "
                "fetched from the internet (e.g. 'research companies', 'deep dive on a topic', "
                "'gather everything about X', 'crawl the web for Y'). Plans source URLs from the "
                "query, crawls them with Crawl4AI, and returns a structured summary PLUS the full "
                "extracted page content (field 'content') with source links. Emits live progress "
                "events to the UI (crawler_started, page_fetched, open_tab, crawler_complete) so the "
                "user sees the search happening. Put 'content' in your 'show' field and 'summary' in "
                "'speak'. NOT for a quick factual lookup (use 'search' for that). Requires internet access."
            ),
            parameters={"query": {"type": "string", "description": "The research topic or question to investigate"}},
            category="web", executor="crawler", requires_internet=True, parallel_safe=False,
            critical=True, long_running=True,
        ),
    ]

    # ── Multimedia tools (Phase 5.2 / research D2) ───────────────────────────
    specs += [
        ToolSpec(
            name="transcribe_media",
            description=(
                "Transcribe an audio or video file to text using the local Parakeet "
                "ASR service. Automatically chunks long media into <=60s segments. "
                "Input is a local file path OR a URL (http/https, incl. YouTube) — the "
                "media pipeline resolves either to a local file automatically. Returns "
                "the full transcript, detected language, and duration."
            ),
            parameters={
                "audio_path": {"type": "string", "description": "Path or URL to the audio/video file to transcribe"},
                "uri": {"type": "string", "description": "Alias for audio_path (any media file or URL)"},
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
                "'what happens in this video' or 'summarize the screen recording'. "
                "Input is a local file path OR a URL (http/https, incl. YouTube)."
            ),
            parameters={
                "video_path": {"type": "string", "description": "Path or URL to the video file"},
                "uri": {"type": "string", "description": "Alias for video_path (any media file or URL)"},
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
                "HH:MM:SS or seconds. Returns the output file path. Input is a local "
                "file path OR a URL (http/https, incl. YouTube)."
            ),
            parameters={
                "video_path": {"type": "string", "description": "Path or URL to the source video"},
                "uri": {"type": "string", "description": "Alias for video_path (any media file or URL)"},
                "start": {"type": "string", "description": "Start time (HH:MM:SS or seconds)"},
                "end": {"type": "string", "description": "End time (HH:MM:SS or seconds)"},
                "output_path": {"type": "string", "description": "Destination path for the trimmed clip (auto-generated if omitted)"},
            },
            category="media", executor="internal", requires_internet=False,
            parallel_safe=False, critical=False,
        ),
    ]

    for spec in specs:
        register_tool(spec)
    # REQ-6 AC4 / T14: vision.* MCP tools + media/parakeet + web tools become
    # nodes by registration alone — no backend code change. Runs after the
    # tools exist so register_node's tool-must-exist guard passes.
    declare_default_node_metadata()


# Populate the registry on import — pure data, no heavy side-effects.
register_builtin_tools()
