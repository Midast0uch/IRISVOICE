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
    def test_personal_read_only_auto_approves(self):
        assert get_permission_action(PermissionTier.READ_ONLY, "personal") == PermissionAction.AUTO_APPROVE

    def test_personal_side_effect_auto_approves(self):
        assert get_permission_action(PermissionTier.SIDE_EFFECT, "personal") == PermissionAction.AUTO_APPROVE

    def test_personal_destructive_requires_approval(self):
        assert get_permission_action(PermissionTier.DESTRUCTIVE, "personal") == PermissionAction.REQUIRE_APPROVAL

    def test_developer_read_only_auto_approves(self):
        assert get_permission_action(PermissionTier.READ_ONLY, "developer") == PermissionAction.AUTO_APPROVE

    def test_developer_side_effect_requires_approval(self):
        assert get_permission_action(PermissionTier.SIDE_EFFECT, "developer") == PermissionAction.REQUIRE_APPROVAL

    def test_developer_destructive_requires_confirmation(self):
        assert get_permission_action(PermissionTier.DESTRUCTIVE, "developer") == PermissionAction.REQUIRE_CONFIRMATION

    def test_personal_vs_developer_read_only(self):
        """Both personal and developer auto-approve read-only."""
        assert get_permission_action(PermissionTier.READ_ONLY, "personal") == get_permission_action(
            PermissionTier.READ_ONLY, "developer"
        )

    def test_personal_vs_developer_destructive(self):
        """Personal requires approval, developer requires confirmation."""
        personal = get_permission_action(PermissionTier.DESTRUCTIVE, "personal")
        developer = get_permission_action(PermissionTier.DESTRUCTIVE, "developer")
        assert personal != developer
        assert developer == PermissionAction.REQUIRE_CONFIRMATION


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
        req = system.request_permission("write_file", PermissionTier.SIDE_EFFECT, level="developer")
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
        req = system.request_permission("write_file", PermissionTier.SIDE_EFFECT, level="developer")
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
        system = ToolPermissionSystem()
        req = system.request_permission("write_file", PermissionTier.SIDE_EFFECT, level="developer")
        assert req.timeout_seconds == 30

    def test_destructive_timeout_longer(self):
        system = ToolPermissionSystem()
        req = system.request_permission("delete_file", PermissionTier.DESTRUCTIVE, level="developer")
        assert req.timeout_seconds == 60
