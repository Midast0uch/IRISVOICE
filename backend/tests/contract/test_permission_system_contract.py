"""Contract tests: Tool permission system (Phase 4).

Verifies:
  - classify_tool: tier assignment by tool name and params
  - get_permission_action: auto-approve / require_approval / require_confirmation
  - ToolPermissionRequest lifecycle (create, expire)
  - Integration with CapabilitySet
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.agent.permissions import (
    PermissionTier,
    PermissionAction,
    ToolPermissionRequest,
    classify_tool,
    get_permission_action,
    ToolPermissionSystem,
    get_permission_system,
    reset_permission_system_for_testing,
)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset():
    reset_permission_system_for_testing()
    yield


# ── classify_tool tests ────────────────────────────────────────────────────


class TestClassifyTool:
    def test_read_only_tools(self):
        assert classify_tool("read_file") == PermissionTier.READ_ONLY
        assert classify_tool("search") == PermissionTier.READ_ONLY
        assert classify_tool("glob") == PermissionTier.READ_ONLY
        assert classify_tool("web_search") == PermissionTier.READ_ONLY
        assert classify_tool("Read_File") == PermissionTier.READ_ONLY  # case-insensitive

    def test_side_effect_tools(self):
        assert classify_tool("write_file") == PermissionTier.SIDE_EFFECT
        assert classify_tool("edit_file") == PermissionTier.SIDE_EFFECT
        assert classify_tool("create_directory") == PermissionTier.SIDE_EFFECT
        assert classify_tool("run_command") == PermissionTier.SIDE_EFFECT

    def test_destructive_tools(self):
        assert classify_tool("delete_file") == PermissionTier.DESTRUCTIVE
        assert classify_tool("format_disk") == PermissionTier.DESTRUCTIVE
        assert classify_tool("factory_reset") == PermissionTier.DESTRUCTIVE

    def test_unknown_tool_defaults_side_effect(self):
        """Unknown tools default to SIDE_EFFECT (conservative)."""
        assert classify_tool("unknown_tool") == PermissionTier.SIDE_EFFECT

    def test_destructive_param_patterns_escalate(self):
        """Params with destructive patterns escalate from SIDE_EFFECT to DESTRUCTIVE."""
        # run_command is SIDE_EFFECT, but params with "rm -rf" escalate
        result = classify_tool("run_command", {"command": "rm -rf /"})
        assert result == PermissionTier.DESTRUCTIVE

    def test_safe_params_do_not_escalate(self):
        """Safe params leave tier unchanged."""
        result = classify_tool("run_command", {"command": "ls -la"})
        assert result == PermissionTier.SIDE_EFFECT

    def test_empty_params_do_not_change_tier(self):
        assert classify_tool("run_command", {}) == PermissionTier.SIDE_EFFECT

    def test_none_params_do_not_change_tier(self):
        assert classify_tool("run_command") == PermissionTier.SIDE_EFFECT

    def test_param_case_insensitive(self):
        result = classify_tool("run_command", {"command": "RM -RF /"})
        assert result == PermissionTier.DESTRUCTIVE


# ── get_permission_action tests ────────────────────────────────────────────


class TestPermissionAction:
    """Goal-contract T18 (REQ-9 AC9.4, KD-12): CONSENT comes from the
    Auto-approve toggle; MODE no longer decides approval. The old matrix
    (personal auto-approves SIDE_EFFECT, developer requires confirmation)
    is superseded by the explicit toggle."""

    def test_toggle_off_read_only_auto_approves(self):
        assert get_permission_action(
            PermissionTier.READ_ONLY, auto_approve=False
        ) == PermissionAction.AUTO_APPROVE

    def test_toggle_off_side_effect_requires_approval(self):
        assert get_permission_action(
            PermissionTier.SIDE_EFFECT, auto_approve=False
        ) == PermissionAction.REQUIRE_APPROVAL

    def test_toggle_off_destructive_requires_approval(self):
        assert get_permission_action(
            PermissionTier.DESTRUCTIVE, auto_approve=False
        ) == PermissionAction.REQUIRE_APPROVAL

    def test_toggle_on_side_effect_auto_approves(self):
        assert get_permission_action(
            PermissionTier.SIDE_EFFECT, auto_approve=True
        ) == PermissionAction.AUTO_APPROVE

    def test_toggle_on_read_only_auto_approves(self):
        assert get_permission_action(
            PermissionTier.READ_ONLY, auto_approve=True
        ) == PermissionAction.AUTO_APPROVE

    def test_toggle_on_destructive_still_gated(self):
        """AC9.4/AC9.6: the DESTRUCTIVE tier stays gated in BOTH toggle
        states — the toggle never opens a destructive path."""
        assert get_permission_action(
            PermissionTier.DESTRUCTIVE, auto_approve=True
        ) == PermissionAction.REQUIRE_CONFIRMATION
        assert get_permission_action(
            PermissionTier.DESTRUCTIVE, auto_approve=False
        ) == PermissionAction.REQUIRE_APPROVAL

    def test_mode_does_not_decide_approval(self):
        """KD-12: mode governs capability only. Passing a mode string with no
        toggle leaves the consent default in force. Session-331: the default is
        now ON (owner: file creation must not need a card), so SIDE_EFFECT
        auto-approves by default; the point of THIS test is that mode is
        irrelevant — both modes resolve identically, and the toggle alone
        decides."""
        assert get_permission_action(
            PermissionTier.SIDE_EFFECT, "personal"
        ) == get_permission_action(PermissionTier.SIDE_EFFECT, "developer")
        # The default (toggle absent -> ON) auto-approves.
        assert get_permission_action(
            PermissionTier.SIDE_EFFECT, "personal"
        ) == PermissionAction.AUTO_APPROVE
        # With the toggle explicitly OFF, it requires approval — regardless of mode.
        assert get_permission_action(
            PermissionTier.SIDE_EFFECT, auto_approve=False
        ) == PermissionAction.REQUIRE_APPROVAL


# ── ToolPermissionRequest tests ────────────────────────────────────────────


class TestPermissionRequest:
    def test_default_status_is_pending(self):
        req = ToolPermissionRequest(tool_name="test")
        assert req.status == "pending"

    def test_request_has_unique_id(self):
        req1 = ToolPermissionRequest(tool_name="a")
        req2 = ToolPermissionRequest(tool_name="b")
        assert req1.request_id != req2.request_id

    def test_is_expired_detects_timeout(self):
        import time

        req = ToolPermissionRequest(tool_name="test", timeout_seconds=0.001)
        time.sleep(0.005)
        assert req.is_expired()

    def test_is_not_expired_within_timeout(self):
        req = ToolPermissionRequest(tool_name="test", timeout_seconds=30)
        assert not req.is_expired()


class TestPermissionSystem:
    def test_read_only_auto_approves(self):
        system = ToolPermissionSystem()
        req = system.request_permission("read_file", PermissionTier.READ_ONLY, level="developer")
        assert req.status == "approved"

    def test_side_effect_developer_requires_approval(self):
        system = ToolPermissionSystem()
        req = system.request_permission(
            "write_file", PermissionTier.SIDE_EFFECT,
            level="developer", auto_approve=False,
        )
        assert req.status == "pending"

    def test_destructive_personal_requires_approval(self):
        system = ToolPermissionSystem()
        req = system.request_permission("delete_file", PermissionTier.DESTRUCTIVE, level="personal")
        assert req.status == "pending"

    def test_destructive_developer_requires_confirmation(self):
        system = ToolPermissionSystem()
        req = system.request_permission("delete_file", PermissionTier.DESTRUCTIVE, level="developer")
        assert req.status == "pending"

    def test_respond_approved_changes_status(self):
        system = ToolPermissionSystem()
        req = system.request_permission(
            "write_file", PermissionTier.SIDE_EFFECT,
            level="developer", auto_approve=False,
        )
        assert req.status == "pending"

        result = system.respond_to_permission(req.request_id, approved=True)
        assert result is not None
        assert result.status == "approved"

    def test_respond_denied_changes_status(self):
        system = ToolPermissionSystem()
        req = system.request_permission("write_file", PermissionTier.SIDE_EFFECT, level="developer")
        system.respond_to_permission(req.request_id, approved=False)
        # Get the resolved request
        assert req.request_id not in system._pending  # was popped

    def test_respond_unknown_request_returns_none(self):
        system = ToolPermissionSystem()
        result = system.respond_to_permission("nonexistent", approved=True)
        assert result is None

    def test_get_response_timeout(self):
        system = ToolPermissionSystem()
        req = system.request_permission(
            "delete_file", PermissionTier.DESTRUCTIVE,
            level="developer",
            turn_id="timeout_test",
        )
        # Use a very short timeout for testing
        req.timeout_seconds = 0.1
        # Temporarily put it back in pending with the short timeout
        system._pending[req.request_id] = req

        import time
        resolved = system.get_response(req, poll_interval=0.05)
        assert resolved.status == "timed_out"

    def test_auto_approve_sets_timeout_correctly(self):
        """The pending wait uses the side-effect timeout constant (raised to
        120 s in session 247 so a human can notice, read, and click)."""
        from backend.agent.permissions import PERMISSION_TIMEOUT_SIDE_EFFECT

        system = ToolPermissionSystem()
        req = system.request_permission(
            "write_file", PermissionTier.SIDE_EFFECT, auto_approve=False
        )
        assert req.timeout_seconds == PERMISSION_TIMEOUT_SIDE_EFFECT

    def test_destructive_timeout_longer(self):
        """Destructive keeps the tighter-but-longer window (180 s)."""
        from backend.agent.permissions import (
            PERMISSION_TIMEOUT_DESTRUCTIVE,
            PERMISSION_TIMEOUT_SIDE_EFFECT,
        )

        system = ToolPermissionSystem()
        req = system.request_permission(
            "delete_file", PermissionTier.DESTRUCTIVE, auto_approve=True
        )
        assert req.timeout_seconds == PERMISSION_TIMEOUT_DESTRUCTIVE
        assert PERMISSION_TIMEOUT_DESTRUCTIVE >= PERMISSION_TIMEOUT_SIDE_EFFECT
