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
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.capabilities import CapabilitySet
import backend.capabilities as _caps

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

PERMISSION_TIMEOUT_SIDE_EFFECT = 30   # seconds
PERMISSION_TIMEOUT_DESTRUCTIVE = 60   # seconds


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


# ALWAYS_ASK = destructive tools ∪ terminal tools. SESSION_APPROVABLE = repo tools
# minus the always-ask set. Everything else is UNGATED (no prompt).
_ALWAYS_ASK_TOOLS = _DESTRUCTIVE_TOOLS | CapabilitySet._TERMINAL_TOOLS
_SESSION_APPROVABLE_TOOLS = CapabilitySet._REPO_TOOLS - _ALWAYS_ASK_TOOLS


def approval_class(tool_name: str) -> ApprovalClass:
    """Classify a tool into an approval class from the tier/capability constants."""
    name = tool_name.lower()
    if name in _ALWAYS_ASK_TOOLS:
        return ApprovalClass.ALWAYS_ASK
    if name in _SESSION_APPROVABLE_TOOLS:
        return ApprovalClass.SESSION_APPROVABLE
    return ApprovalClass.UNGATED


def get_approvable_tools() -> List[str]:
    """Tools the user may pre-approve via the standing list (REQ-19 AC3).

    These are exactly the SESSION_APPROVABLE tools — side-effect/repo tools that
    would otherwise prompt every session. ALWAYS_ASK (destructive/terminal) and
    UNGATED (read-only) tools are intentionally excluded: the former can never be
    pre-approved, the latter never prompt.
    """
    return sorted(_SESSION_APPROVABLE_TOOLS)


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
        base_tier = PermissionTier.SIDE_EFFECT  # unknown default

    # Check params for destructive patterns — escalates any tier to DESTRUCTIVE
    if params:
        params_str = str(params).lower()
        for pattern in _DESTRUCTIVE_PARAM_PATTERNS:
            if pattern in params_str:
                return PermissionTier.DESTRUCTIVE

    return base_tier


def get_permission_action(tier: PermissionTier, level: str) -> PermissionAction:
    """Determine what action to take based on tier + permission level.

    Args:
        tier: The classified risk tier.
        level: "personal" or "developer".

    Returns:
        PermissionAction: auto_approve, require_approval, or require_confirmation.
    """
    if level == "personal":
        # Personal: READ_ONLY auto, SIDE_EFFECT auto, DESTRUCTIVE require approval
        if tier == PermissionTier.DESTRUCTIVE:
            return PermissionAction.REQUIRE_APPROVAL
        return PermissionAction.AUTO_APPROVE

    # Developer: READ_ONLY auto, SIDE_EFFECT require approval, DESTRUCTIVE require confirmation
    if tier == PermissionTier.READ_ONLY:
        return PermissionAction.AUTO_APPROVE
    if tier == PermissionTier.SIDE_EFFECT:
        return PermissionAction.REQUIRE_APPROVAL
    return PermissionAction.REQUIRE_CONFIRMATION


# ── Permission system ──────────────────────────────────────────────────────


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
    ) -> ToolPermissionRequest:
        """Create and emit a permission request.

        Returns the request (not yet acted on).  The caller must await
        the response via get_response().

        Never raises — logs and returns auto-approved request on error.
        """
        try:
            _level = level or CapabilitySet.get_mode()
            action = get_permission_action(tier, _level)
            cls = approval_class(tool_name)

            # REQ-19 AC7 precedence: ALWAYS_ASK > standing list > session approval > prompting.
            # ALWAYS_ASK always prompts (never honoured by the standing list or cache).
            if cls != ApprovalClass.ALWAYS_ASK:
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

            return req

        except Exception as exc:
            logger.warning("[Permissions] respond_to_permission failed: %s", exc)
            return None

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
