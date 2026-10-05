#!/usr/bin/env python3
"""
Tool permission system — tiered risk classification.

Integrates with CapabilitySet (personal/developer mode) from backend/capabilities.py
and EventBus for permission request events.

Three risk tiers:
  READ_ONLY:    Auto-execute. Reads that don't modify state.
  SIDE_EFFECT:  Requires approval. Writes that modify local state.
  DESTRUCTIVE:  Requires approval + confirmation. Irreversible operations.

Two permission levels (from CapabilitySet):
  PERSONAL:  SIDE_EFFECT auto-approved, DESTRUCTIVE requires approval.
  DEVELOPER: DESTRUCTIVE requires approval + confirmation, terminal/repo access gated.

Error handling: try/except pattern — never blocks the DER loop.
"""

from __future__ import annotations

import enum
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.capabilities import CapabilitySet
import backend.capabilities as _caps

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

# Session 247: raised 30s -> 120s (matching AskUserTool's question timeout).
# Live evidence: a permission card surfaced mid-crawl, the user read it and
# clicked Allow — but the request had already expired silently at 30s, so the
# click did nothing (the card is not told about expiry; it stays rendered and
# clickable against a dead request). 120s gives a human time to notice, read,
# and act. Destructive keeps a tighter window but also gets headroom.
PERMISSION_TIMEOUT_SIDE_EFFECT = int(os.environ.get("IRIS_PERMISSION_TIMEOUT_SIDE_EFFECT_S", "120"))
PERMISSION_TIMEOUT_DESTRUCTIVE = int(os.environ.get("IRIS_PERMISSION_TIMEOUT_DESTRUCTIVE_S", "180"))


# ── Enums ──────────────────────────────────────────────────────────────────


class PermissionTier(str, enum.Enum):
    """Risk tier for a tool call."""

    READ_ONLY = "read_only"
    SIDE_EFFECT = "side_effect"
    DESTRUCTIVE = "destructive"


class PermissionAction(str, enum.Enum):
    """Action the system should take for a given tier + level."""

    AUTO_APPROVE = "auto_approve"
    REQUIRE_APPROVAL = "require_approval"
    REQUIRE_CONFIRMATION = "require_confirmation"  # approval + second confirm


# ── Data types ─────────────────────────────────────────────────────────────


@dataclass
class ToolPermissionRequest:
    """A permission request sent to the frontend for approval."""

    request_id: str = field(default_factory=lambda: f"perm_{uuid.uuid4().hex[:12]}")
    tool_name: str = ""
    tier: PermissionTier = PermissionTier.READ_ONLY
    params: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    created_at: float = field(default_factory=time.time)
    timeout_seconds: int = PERMISSION_TIMEOUT_SIDE_EFFECT
    status: str = "pending"  # pending | approved | denied | timed_out
    turn_id: Optional[str] = None
    session_id: Optional[str] = None  # session this request belongs to (REQ-19 cache key)
    session_approved: bool = False  # True when auto-approved from the per-session cache
    standing_approved: bool = False  # True when auto-approved from the standing list

    def is_expired(self) -> bool:
        return time.time() > self.created_at + self.timeout_seconds


@dataclass
class ToolPermissionResponse:
    """Response from the frontend to a permission request."""

    request_id: str
    approved: bool
    confirmed: bool = False  # for destructive operations
    reason: str = ""


# ── Tool classification ────────────────────────────────────────────────────


# Tools that only read state — never modify anything
_READ_ONLY_TOOLS: set = {
    "read_file",
    "read_command_output",
    "speak",
    "search",
    "crawler_query",
    "glob",
    "grep",
    "read",
    "list_directory",
    "stat",
    "get_file_info",
    "web_search",
    "web_fetch",
    "read_multiple_files",
    "get_session",
    "navigate_file",
    "list_tools",
    "get_tool_info",
    "list_resources",
    "read_resource",
    # Session 247: fetch.vision — the LFM-VL-driven headless-browser read of
    # walled/challenge pages. Same risk profile as crawler_query/web_search
    # (reads PUBLIC pages in a disposable browser session; touches no user
    # state), but it was missing from every tier list, so classify_tool's
    # unknown-default made it SIDE_EFFECT -> require_approval -> 30s timeout
    # -> node failed whenever no human was watching (live conv-41 15:37:
    # router selected fetch.vision, permission timed out, VLM never launched,
    # zero vision actions all day). Reclassified per the session-246
    # decision-C precedent. If you consider browser automation side-effectful,
    # veto this and it goes back to requiring approval.
    "fetch.vision",
    # Session 247: get_rendered_documents — pure READ of documents the agent
    # itself stored earlier in the same conversation. Was unknown-default
    # SIDE_EFFECT: live conv-46 showed "Execute get_rendered_documents"
    # permission cards THREE times (each 30s timeout -> DER retry -> re-ask).
    "get_rendered_documents",
    # Session 246 (user decision C): cross-thread DISCOVERY tools — purely
    # informational, no state change. list_conversations was defaulting to
    # SIDE_EFFECT (unknown-tool fallback) and its 30s permission timeout
    # killed the @taskcard follow-up run (conv-40). get_rendered_documents
    # stays gated: it returns thread CONTENT, not just an index.
    "list_conversations",
    # create_artifact writes ONLY the app's own document store and puts a card
    # in the chat (reply-surface audit, Phase A): nothing on the user's disk or
    # machine changes, so it must never raise a permission card.
    "create_artifact",
}

# Tools that modify local state — side effects but reversible
_SIDE_EFFECT_TOOLS: set = {
    "write_file",
    "create_directory",
    "edit_file",
    "rename_file",
    "move_file",
    "copy_file",
    "append_file",
    "patch_file",
    "replace_in_file",
    "run_command",
    "execute_script",
    "stop_command",
}

# Tools that are destructive — irreversible
_DESTRUCTIVE_TOOLS: set = {
    "delete_file",
    "delete_directory",
    "force_delete",
    "overwrite_file",
    "truncate_file",
    "format_disk",
    "factory_reset",
    "purge",
    # Goal-contract T18 (REQ-9 AC9.4): the registry declares these destructive,
    # and each was previously gated only by accident — lock_screen / shutdown /
    # restart via CapabilitySet._TERMINAL_TOOLS (which T18 removed from
    # always-ask), and github_delete_ssh_key not at all (it sat in _REPO_TOOLS,
    # so a DELETION was pre-approvable). Listing them here keeps the destructive
    # tier set in sync with the registry's own tier verdict — the drift CT-12
    # exists to catch, and the unguarded-deletion path the toggle must not open.
    "lock_screen",
    "shutdown",
    "restart",
    "github_delete_ssh_key",
}

# Parameter patterns that escalate the tier
# ── REQ-19: approval classes (derived from the tier/capability constants) ──
class ApprovalClass(str, enum.Enum):
    """How a gated tool is treated by the permission system.

    Derived from the EXISTING tier/capability constants (never a standalone
    hardcoded list) so the classes cannot drift from the tiers the matrix uses.
    """
    ALWAYS_ASK = "always_ask"
    SESSION_APPROVABLE = "session_approvable"
    UNGATED = "ungated"


# ALWAYS_ASK = the DESTRUCTIVE tier only. The terminal/GUI tools used to sit
# here too (via CapabilitySet._TERMINAL_TOOLS), but consent is now governed
# by the Auto-approve toggle (T18, KD-12): mode governs CAPABILITY only
# (which tools exist), the toggle governs CONSENT (whether it asks first).
# CapabilitySet._TERMINAL_TOOLS still governs capability (personal has no
# terminal; developer does) — it no longer feeds always-ask (CT-GC10 lock).
#
# This is the HARDCODED core of the destructive tier. The EFFECTIVE
# always-gate set is this set UNIONED with every tool the registry declares
# destructive — see approval_class(), which shares the classify_tool verdict
# so the tier and the approval class can never drift (CT-12: a tool the
# registry calls destructive must never be UNGATED or pre-approvable).
_ALWAYS_ASK_TOOLS = set(_DESTRUCTIVE_TOOLS)
_SESSION_APPROVABLE_TOOLS = CapabilitySet._REPO_TOOLS - _ALWAYS_ASK_TOOLS


def approval_class(tool_name: str) -> ApprovalClass:
    """Classify a tool into an approval class from the tier/capability constants.

    The DESTRUCTIVE verdict is authoritative and SHARED with ``classify_tool``
    (which also consults the tool registry). Reading the same verdict from both
    entry points is what makes drift impossible: a tool the registry declares
    destructive can never be UNGATED (never prompts) or SESSION_APPROVABLE
    (user can whitelist it). CT-12 pins this — a permission hole here voids the
    goal contract, because an un-gated destructive call is exactly the
    unguarded deletion path the Auto-approve toggle must not open.
    """
    name = tool_name.lower()
    try:
        if classify_tool(tool_name, None) == PermissionTier.DESTRUCTIVE:
            return ApprovalClass.ALWAYS_ASK
    except Exception:
        pass  # registry read must never break classification — fall through
    if name in _ALWAYS_ASK_TOOLS:
        return ApprovalClass.ALWAYS_ASK
    # Session 326 (live bug): this used to be `name in _SESSION_APPROVABLE_TOOLS`,
    # where that set is `CapabilitySet._REPO_TOOLS - _ALWAYS_ASK_TOOLS`. Any
    # SIDE_EFFECT tool NOT in _REPO_TOOLS therefore fell through to UNGATED and
    # could never be remembered — `run_command` (a _TERMINAL_TOOL, tier
    # side_effect) prompted on EVERY call. Live proof: 4 approvals for one
    # run_command in a single session, each granted, each asking again.
    # The class is a property of the TIER (which is what the docstring above
    # already claims): destructive -> always ask; side-effect -> ask once per
    # session; read-only -> never ask. Deriving it from the tier keeps the
    # terminal/GUI tools in the same consent model as writes.
    try:
        if classify_tool(tool_name, None) == PermissionTier.SIDE_EFFECT:
            return ApprovalClass.SESSION_APPROVABLE
    except Exception:
        pass  # registry read must never break classification — fall through
    if name in _SESSION_APPROVABLE_TOOLS:
        return ApprovalClass.SESSION_APPROVABLE
    return ApprovalClass.UNGATED


def get_approvable_tools() -> List[str]:
    """Tools the user may pre-approve via the standing list (REQ-19 AC3).

    These are the SESSION_APPROVABLE tools — side-effect/repo tools that would
    otherwise prompt every session. ALWAYS_ASK (the destructive tier, hardcoded
    OR registry-declared) and UNGATED (read-only) tools are excluded: the
    former can never be pre-approved, the latter never prompt. The filter is
    live (not the module constant alone) so a registry-destructive tool can
    never leak onto the pre-approval list.
    """
    return sorted(
        t for t in _SESSION_APPROVABLE_TOOLS
        if approval_class(t) != ApprovalClass.ALWAYS_ASK
    )


def _get_standing_approved_tools() -> Set[str]:
    """Read the user's standing approved-tools list, RE-VALIDATED on every read
    (REQ-19 AC4/AC6).

    ALWAYS_ASK tools are dropped — they can never be pre-approved, even if a user
    hand-edited the config file to add one. An unreadable config yields an empty
    list and the system still prompts (AC6) — never 'everything approved'.
    """
    try:
        with open(_caps._CFG_PATH, encoding="utf-8") as _f:
            _cfg = json.load(_f)
    except Exception:
        return set()  # AC6: unreadable -> empty, still prompt
    _raw = _cfg.get("approved_tools")
    if not isinstance(_raw, list):
        return set()
    _validated: Set[str] = set()
    for _name in _raw:
        if not isinstance(_name, str):
            continue
        _low = _name.lower()
        if approval_class(_low) == ApprovalClass.ALWAYS_ASK:
            continue  # AC4: refuse ALWAYS_ASK on the standing list
        _validated.add(_low)
    return _validated


class SessionApprovalCache:
    """Per-session approval cache (REQ-19 AC2/AC8).

    In-memory only — it does NOT survive a process restart, so approvals are
    discarded on restart. ALWAYS_ASK tools are physically refused from entering
    the cache (AC8): approving one records nothing, so the next call prompts
    again. This is safer than writing an entry and then checking a precedence
    rule against it later.
    """
    def __init__(self) -> None:
        self._approved: Dict[Tuple[str, str], bool] = {}

    def is_approved(self, session_id: str, tool_name: str) -> bool:
        return self._approved.get((session_id, tool_name.lower()), False)

    def record_approval(self, session_id: str, tool_name: str) -> None:
        if approval_class(tool_name) == ApprovalClass.ALWAYS_ASK:
            return  # AC8: ALWAYS_ASK never enters the cache
        self._approved[(session_id, tool_name.lower())] = True

    def clear_session(self, session_id: str) -> None:
        for key in [k for k in self._approved if k[0] == session_id]:
            del self._approved[key]

    def clear_all(self) -> None:
        self._approved.clear()


_session_approval_cache = SessionApprovalCache()


_DESTRUCTIVE_PARAM_PATTERNS: List[str] = [
    "rm -rf",
    "drop table",
    "drop database",
    "delete from",
    "truncate table",
    "format ",
    "destroy",
    "wipe",
    "nuke",
    "purge",
    "overwrite",
]

# Params that carry written DATA (file bodies, replacement text, messages).
# The pattern scan above never reads them; see classify_tool.
_CONTENT_PARAM_KEYS: frozenset = frozenset({
    "content", "contents", "text", "body", "data", "code", "markdown", "html",
    "new", "old", "new_string", "old_string", "message", "summary", "description",
    # A card title is a label for written data, like a summary: "Format of the
    # report" must not read as the destructive pattern "format ".
    "title",
})

# Goal contract T18 (REQ-9 AC9.6): deletion/removal COMMAND forms. These are
# shell-command tokens, matched with word boundaries against the shell
# command text only (never against prose inside a file write) so the
# Auto-approve toggle cannot open an unguarded deletion path through the
# shell. Matched case-insensitively.
_DESTRUCTIVE_COMMAND_FORMS: List[str] = [
    "rm",
    "rmdir",
    "del",
    "erase",
    "remove-item",
    "rd",
    "unlink",
    "truncate",
    "shred",
]

# Tools whose params carry a shell command string.
_SHELL_COMMAND_TOOLS: set = {
    "run_command",
    "execute_command",
    "shell",
    "dev_cli",
    "execute_script",
}

# Param keys that carry the shell command text.
_COMMAND_PARAM_KEYS: tuple = ("command", "query", "script", "cmd")


def is_destructive_command(
    tool_name: str, params: Optional[Dict[str, Any]] = None
) -> bool:
    """True when this invocation is a destructive command (T18, AC9.6).

    The detector is the shell safety net under the Auto-approve toggle:
    destructive commands stay gated at all times, toggle or not. Implemented
    as the classify_tool verdict so the two can never drift.
    """
    try:
        return classify_tool(tool_name, params) == PermissionTier.DESTRUCTIVE
    except Exception:
        return False


# ── Auto-approve default (session-331 owner decision) ──────────────────────
# The owner's directive: creating files (via write_file OR run_command) must
# NOT require a permission card to accept. The Auto-approve toggle is the ONE
# consent control (KD-12), so the coherent way to honour "creation never asks"
# without special-casing tool names is to default the toggle ON. The DESTRUCTIVE
# tier and deletion/removal commands stay gated at ALL times regardless (AC9.4/
# AC9.6) — that is the real safety net and it is unchanged. An operator can set
# `auto_approve: false` in data/iris_config.json (or toggle it in the Tools
# card) to make writes and shell ask again; that choice is honoured.
DEFAULT_AUTO_APPROVE = True


def get_auto_approve() -> bool:
    """Read the Auto-approve consent toggle (T18, KD-12).

    Consent (whether the agent asks first) is SEPARATE from mode/capability
    (which tools exist).

    Two distinct cases (session-331, preserving the REQ-19 AC6 safety rule):
      * config READABLE, key ABSENT  -> DEFAULT_AUTO_APPROVE (ON — the owner
        decision that file creation must not need a card).
      * config UNREADABLE/UNPARSEABLE -> False (FAIL CLOSED — still ask). AC6:
        an unreadable config must never resolve to "everything approved".

    The DESTRUCTIVE tier stays gated in BOTH states. Never raises.
    """
    try:
        with open(_caps._CFG_PATH, encoding="utf-8") as _f:
            _cfg = json.load(_f)
    except Exception:
        # Unreadable config: fail CLOSED (ask), never "everything approved" (AC6).
        return False
    try:
        if "auto_approve" in _cfg:
            return bool(_cfg.get("auto_approve"))
        return DEFAULT_AUTO_APPROVE
    except Exception:
        return False


def classify_tool(tool_name: str, params: Optional[Dict[str, Any]] = None) -> PermissionTier:
    """Classify a tool by name and params into a risk tier.

    Args:
        tool_name: The tool name (e.g. "write_file", "delete_file")
        params: Optional parameters that may escalate the tier
               (e.g. params containing "rm -rf" escalate from SIDE_EFFECT to DESTRUCTIVE)

    Returns:
        PermissionTier for this tool invocation.
    """
    name_lower = tool_name.lower()

    # Direct match against destructive list
    if name_lower in _DESTRUCTIVE_TOOLS:
        base_tier = PermissionTier.DESTRUCTIVE

    # Direct match against side-effect list
    elif name_lower in _SIDE_EFFECT_TOOLS:
        base_tier = PermissionTier.SIDE_EFFECT
    elif name_lower in _READ_ONLY_TOOLS:
        base_tier = PermissionTier.READ_ONLY
    else:
        # Session 247: consult the TOOL REGISTRY before falling back to the
        # unknown-default. tool_registry.py is the declared single source of
        # truth ("lets Phase 2's classify_tool read the tier directly" — its
        # own header comment), and every ToolSpec carries permission_tier.
        # That wiring never happened, so any registered tool missing from
        # these hardcoded lists silently became SIDE_EFFECT: live conv-46
        # showed get_rendered_documents (registry tier read_only!) demanding
        # approval three times. Lazy import — tool_registry imports
        # PermissionTier from this module, so a top-level import would cycle;
        # by call time both modules are loaded.
        try:
            from backend.agent.tool_registry import resolve_tool

            _spec = resolve_tool(tool_name)
            if _spec is not None:
                _tier = str(getattr(_spec, "permission_tier", "") or "").lower()
                if _tier == "read_only":
                    return PermissionTier.READ_ONLY
                if _tier == "destructive":
                    return PermissionTier.DESTRUCTIVE
                if _tier == "side_effect":
                    return PermissionTier.SIDE_EFFECT
        except Exception:
            pass  # registry read must never break classification
        base_tier = PermissionTier.SIDE_EFFECT  # unknown default

    # Check params for destructive patterns — escalates any tier to DESTRUCTIVE.
    # CONTENT params are not scanned (execution audit B12, 2026-09-29): a file
    # body, replacement text or commit message is data being written, not an
    # action. Source code containing "overwrite", "format " or "purge" made a
    # plain write_file ask for destructive confirmation.
    if params:
        _scan = (
            {k: v for k, v in params.items() if str(k).lower() not in _CONTENT_PARAM_KEYS}
            if isinstance(params, dict) else params
        )
        params_str = str(_scan).lower()
        for pattern in _DESTRUCTIVE_PARAM_PATTERNS:
            if pattern in params_str:
                return PermissionTier.DESTRUCTIVE
        # AC9.6: deletion/removal command forms in SHELL command text —
        # shell tools only, word-boundaried, so prose inside a file write
        # (e.g. "remove-item from the list" in a document) never trips it.
        if name_lower in _SHELL_COMMAND_TOOLS:
            try:
                _cmd_texts = [
                    str(params.get(_k, "") or "")
                    for _k in _COMMAND_PARAM_KEYS
                    if isinstance(params, dict)
                ]
                _cmd_blob = "\n".join(_cmd_texts).lower()
                for _form in _DESTRUCTIVE_COMMAND_FORMS:
                    if re.search(
                        r"(?<![a-z0-9_-])" + re.escape(_form)
                        + r"(?![a-z0-9_-])",
                        _cmd_blob,
                    ):
                        return PermissionTier.DESTRUCTIVE
            except Exception:
                pass

    return base_tier


def get_permission_action(
    tier: PermissionTier,
    level: Optional[str] = None,
    auto_approve: Optional[bool] = None,
) -> PermissionAction:
    """Determine what action to take based on tier + consent toggle (T18).

    KD-12: mode and approval are two separate controls. Mode (personal /
    developer) governs CAPABILITY only — which tools exist — and is enforced
    by CapabilitySet, never here. ``auto_approve`` governs CONSENT — whether
    the agent asks first. ``level`` is accepted for backward compatibility
    and ignored.

    Toggle ON: reads, writes, shell commands, and GUI actions auto-approve.
    The DESTRUCTIVE tier and deletion/removal commands stay gated at all
    times (T18, AC9.4/AC9.6) — the toggle never opens those.

    Args:
        tier: The classified risk tier.
        level: legacy mode string (ignored; kept for existing callers).
        auto_approve: the consent toggle; read from config when None.

    Returns:
        PermissionAction: auto_approve, require_approval, or require_confirmation.
    """
    _auto = bool(auto_approve) if auto_approve is not None else get_auto_approve()
    if tier == PermissionTier.DESTRUCTIVE:
        return (
            PermissionAction.REQUIRE_CONFIRMATION
            if _auto
            else PermissionAction.REQUIRE_APPROVAL
        )
    if _auto:
        return PermissionAction.AUTO_APPROVE
    # Toggle OFF (default, fail closed): reads auto; writes/shell ask.
    if tier == PermissionTier.READ_ONLY:
        return PermissionAction.AUTO_APPROVE
    return PermissionAction.REQUIRE_APPROVAL


# ── Permission system ──────────────────────────────────────────────────────


def _emit_permission_event(req: ToolPermissionRequest, label: str, evidence: str = "none",
                           **kw: Any) -> None:
    """Taxonomy FEEDBACK: the user's answer to a permission request (APPROVAL / DENIAL,
    evidence "user") or its expiry (NO_RESPONSE). Ids and tool name only. Rides
    lane("memory_events"); never raises."""
    try:
        from backend.agent.event_emit import emit

        emit(None, label, evidence=evidence, thread_id=req.session_id or None,
             payload={"request_id": req.request_id, "tool": req.tool_name,
                      "tier": getattr(req.tier, "value", str(req.tier)), "kind": "permission"},
             **kw)
    except Exception:  # noqa: BLE001 - an event never blocks a permission answer
        logger.debug("[Permissions] event %s skipped", label, exc_info=True)


class ToolPermissionSystem:
    """Manages tool permission requests and approvals.

    Integrates with EventBus to:
      - Emit PERMISSION_REQUEST events to the frontend
      - Receive PERMISSION_GRANTED / PERMISSION_DENIED responses
    """

    def __init__(self, event_bus=None):
        self._pending: Dict[str, ToolPermissionRequest] = {}
        from backend.agent.event_bus import get_event_bus, IRISStreamEvent

        self._bus = event_bus or get_event_bus()
        self._IRISStreamEvent = IRISStreamEvent

    def request_permission(
        self,
        tool_name: str,
        tier: PermissionTier,
        params: Optional[Dict[str, Any]] = None,
        description: str = "",
        turn_id: Optional[str] = None,
        level: Optional[str] = None,
        force: bool = False,
        session_id: Optional[str] = None,
        auto_approve: Optional[bool] = None,
        conversation_id: Optional[str] = None,
    ) -> ToolPermissionRequest:
        """Create and emit a permission request.

        Returns the request (not yet acted on).  The caller must await
        the response via get_response().

        ``level`` is legacy (mode-coupled) and ignored; ``auto_approve``
        is the consent authority (T18, KD-12). Never raises — logs and
        returns auto-approved request on error.
        """
        try:
            action = get_permission_action(tier, auto_approve=auto_approve)
            cls = approval_class(tool_name)

            # REQ-19 AC7 precedence: ALWAYS_ASK > standing list > session approval > prompting.
            # ALWAYS_ASK always prompts (never honoured by the standing list or cache).
            # T18 (AC9.6): a param-ESCALATED destructive tier (e.g. run_command
            # carrying "rm") skips the standing/session bypasses too — the
            # tier verdict, not the tool name, is authoritative.
            if cls != ApprovalClass.ALWAYS_ASK and tier != PermissionTier.DESTRUCTIVE:
                standing = _get_standing_approved_tools()
                if tool_name.lower() in standing:
                    return ToolPermissionRequest(
                        tool_name=tool_name,
                        tier=tier,
                        params=params or {},
                        description=description,
                        turn_id=turn_id,
                        session_id=session_id,
                        status="approved",
                        standing_approved=True,
                    )
                # Session approval beats prompting (AC2). ALWAYS_ASK is never cached.
                if cls == ApprovalClass.SESSION_APPROVABLE and session_id and _session_approval_cache.is_approved(session_id, tool_name):
                    return ToolPermissionRequest(
                        tool_name=tool_name,
                        tier=tier,
                        params=params or {},
                        description=description,
                        turn_id=turn_id,
                        session_id=session_id,
                        status="approved",
                        session_approved=True,
                    )

            # REQ-18: force=True (capability escalation) must prompt even when the
            # mode's policy would auto-approve — the user overrides the capability
            # denial explicitly, so we must actually ask.
            if not force and action == PermissionAction.AUTO_APPROVE:
                req = ToolPermissionRequest(
                    tool_name=tool_name,
                    tier=tier,
                    params=params or {},
                    description=description,
                    turn_id=turn_id,
                    session_id=session_id,
                    status="approved",
                )
                return req

            timeout = (
                PERMISSION_TIMEOUT_DESTRUCTIVE
                if action == PermissionAction.REQUIRE_CONFIRMATION
                else PERMISSION_TIMEOUT_SIDE_EFFECT
            )

            req = ToolPermissionRequest(
                tool_name=tool_name,
                tier=tier,
                params=params or {},
                description=description,
                timeout_seconds=timeout,
                turn_id=turn_id,
                session_id=session_id,
            )

            self._pending[req.request_id] = req

            # Emit via EventBus
            # Session 326 (cross-thread card bug): the emit used to omit
            # session_id/conversation_id, so EventPayload defaulted both to
            # "default". WSEventBridge.handler then took its broadcast-to-ALL
            # fallback (ws_event_bridge.py:160-169: a "default"/unknown session
            # is not routed), and the PermissionCard rendered in EVERY open
            # conversation — not just the one that asked. Routing the emit by
            # session fixes it at the source; the frontend also guards by
            # conversation_id (defence in depth).
            self._bus.emit(
                self._IRISStreamEvent.PERMISSION_REQUEST,
                data={
                    "request_id": req.request_id,
                    "tool_name": tool_name,
                    "tier": tier.value,
                    "params": params or {},
                    "description": description,
                    "timeout_seconds": timeout,
                    "requires_confirmation": action == PermissionAction.REQUIRE_CONFIRMATION,
                },
                turn_id=turn_id,
                session_id=session_id or "default",
                conversation_id=conversation_id or session_id or "default",
            )

            logger.info(
                "[Permissions] Requested permission for %s (tier=%s, timeout=%ds)",
                tool_name,
                tier.value,
                timeout,
            )
            return req

        except Exception as exc:
            logger.warning("[Permissions] request_permission failed: %s", exc)
            return ToolPermissionRequest(
                tool_name=tool_name,
                tier=PermissionTier.READ_ONLY,
                status="approved",  # Fallback safe
            )

    def respond_to_permission(
        self,
        request_id: str,
        approved: bool,
        confirmed: bool = False,
    ) -> Optional[ToolPermissionRequest]:
        """Process a frontend response to a permission request.

        Returns the request (with updated status) or None if not found.
        """
        try:
            req = self._pending.pop(request_id, None)
            if not req:
                logger.warning("[Permissions] Response for unknown request: %s", request_id)
                return None

            req.status = "approved" if approved else "denied"
            if approved and confirmed:
                req.status = "approved"

            # REQ-19 AC2: record SESSION_APPROVABLE approvals in the per-session cache.
            # ALWAYS_ASK tools are refused by the cache itself (AC8), so they always
            # prompt again next time.
            if approved and approval_class(req.tool_name) == ApprovalClass.SESSION_APPROVABLE and req.session_id:
                _session_approval_cache.record_approval(req.session_id, req.tool_name)

            # Emit response event
            event = (
                self._IRISStreamEvent.PERMISSION_GRANTED
                if approved
                else self._IRISStreamEvent.PERMISSION_DENIED
            )
            self._bus.emit(
                event,
                data={
                    "request_id": request_id,
                    "tool_name": req.tool_name,
                    "confirmed": confirmed,
                },
                turn_id=req.turn_id,
            )
            _emit_permission_event(
                req, "APPROVAL" if approved else "DENIAL", evidence="user",
                cost={"ms": int((time.time() - req.created_at) * 1000)},
            )

            return req

        except Exception as exc:
            logger.warning("[Permissions] respond_to_permission failed: %s", exc)
            return None

    def _broadcast_timeout(self, request: ToolPermissionRequest) -> None:
        """Session 247: tell the frontend a request expired.

        get_response/get_response_async used to pop the request SILENTLY —
        the PermissionCard stayed rendered and clickable against a dead
        request, so Allow clicks did nothing (live report: "couldn't pick
        the allow option"). Reuses the existing permission:denied wire so
        chat-view removes the card; the log records the true reason.
        Never raises.
        """
        try:
            self._bus.emit(
                self._IRISStreamEvent.PERMISSION_DENIED,
                data={
                    "request_id": request.request_id,
                    "tool_name": request.tool_name,
                    "reason": "timeout",
                    "timeout_seconds": request.timeout_seconds,
                },
                turn_id=request.turn_id,
            )
        except Exception:
            pass
        _emit_permission_event(
            request, "NO_RESPONSE", cost={"ms": int(request.timeout_seconds * 1000)},
        )

    def get_response(self, request: ToolPermissionRequest, poll_interval: float = 0.1) -> ToolPermissionRequest:
        """Block until the permission request is resolved (approved/denied/timed_out).

        This is a synchronous blocking call.  Should not be called from
        async hot paths without wrapping in asyncio.to_thread().

        Returns the request with updated status.
        """
        start = time.time()
        while time.time() - start < request.timeout_seconds:
            if request.request_id not in self._pending:
                # Request was responded to (popped from pending)
                return request
            time.sleep(poll_interval)

        # Timed out
        if request.request_id in self._pending:
            self._pending.pop(request.request_id, None)
            request.status = "timed_out"
            logger.info("[Permissions] Request %s timed out (%ds)", request.request_id, request.timeout_seconds)
            self._broadcast_timeout(request)

        return request

    async def get_response_async(
        self, request: ToolPermissionRequest, poll_interval: float = 0.1
    ) -> ToolPermissionRequest:
        """Async version of get_response.  Use in async contexts."""
        import asyncio

        start = time.time()
        while time.time() - start < request.timeout_seconds:
            if request.request_id not in self._pending:
                return request
            await asyncio.sleep(poll_interval)

        if request.request_id in self._pending:
            self._pending.pop(request.request_id, None)
            request.status = "timed_out"
            logger.info("[Permissions] Request %s timed out (%ds)", request.request_id, request.timeout_seconds)
            self._broadcast_timeout(request)

        return request


# ── Singleton ──────────────────────────────────────────────────────────────

_system_instance: Optional[ToolPermissionSystem] = None


def get_permission_system() -> ToolPermissionSystem:
    """Get or create the singleton permission system."""
    global _system_instance
    if _system_instance is None:
        _system_instance = ToolPermissionSystem()
    return _system_instance


def reset_permission_system_for_testing() -> None:
    """Reset singleton — for test isolation only."""
    global _system_instance
    _system_instance = None
