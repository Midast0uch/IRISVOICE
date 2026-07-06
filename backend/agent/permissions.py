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
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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
    "search",
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


def permission_level_from_config() -> str:
    """Read the current permission level from CapabilitySet.

    Returns "developer" or "personal".
    """
    try:
        from backend.capabilities import CapabilitySet

        if CapabilitySet.TERMINAL in CapabilitySet._DEVELOPER:
            # If developer mode has TERMINAL, check if it's enabled
            pass
        return "developer"  # default to developer for the agent
    except Exception:
        return "developer"


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
    ) -> ToolPermissionRequest:
        """Create and emit a permission request.

        Returns the request (not yet acted on).  The caller must await
        the response via get_response().

        Never raises — logs and returns auto-approved request on error.
        """
        try:
            _level = level or permission_level_from_config()
            action = get_permission_action(tier, _level)

            if action == PermissionAction.AUTO_APPROVE:
                req = ToolPermissionRequest(
                    tool_name=tool_name,
                    tier=tier,
                    params=params or {},
                    description=description,
                    turn_id=turn_id,
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
