"""Behavioral tests: Permission flow — approval, denial, timeout.

Verifies end-to-end permission behavior through the tool bridge:
  - Read-only tools pass through without permission prompts
  - Side-effect tools trigger approval in developer mode
  - Destructive tools trigger confirmation in developer mode
  - Denied permission returns graceful error
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent.permissions import (
    PermissionTier,
    ToolPermissionRequest,
    classify_tool,
    get_permission_action,
    ToolPermissionSystem,
    reset_permission_system_for_testing,
)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset():
    reset_permission_system_for_testing()
    yield


# ── Permission flow tests ──────────────────────────────────────────────────


class TestPermissionFlow:
    def test_read_only_skips_permission_when_auto_approved(self):
        """Read-only tools auto-approve — no permission prompt needed."""
        system = ToolPermissionSystem()
        req = system.request_permission("read_file", PermissionTier.READ_ONLY, level="developer")
        assert req.status == "approved"

    def test_side_effect_requires_approval_in_developer(self):
        """Side-effect tools in developer mode create a pending request."""
        system = ToolPermissionSystem()
        req = system.request_permission("write_file", PermissionTier.SIDE_EFFECT, level="developer")
        assert req.status == "pending"

    def test_approve_side_effect_allows_execution(self):
        """Approved side-effect request can proceed."""
        system = ToolPermissionSystem()
        req = system.request_permission("write_file", PermissionTier.SIDE_EFFECT, level="developer")
        assert req.status == "pending"

        # Simulate user approval
        system.respond_to_permission(req.request_id, approved=True)
        assert req.request_id not in system._pending  # resolved

    def test_deny_side_effect_returns_error(self):
        """Denied side-effect request should prevent execution."""
        system = ToolPermissionSystem()

        with patch.object(system._bus, "emit") as mock_emit:
            req = system.request_permission("delete_file", PermissionTier.DESTRUCTIVE, level="personal")

            # Deny the request
            system.respond_to_permission(req.request_id, approved=False)

            # Should emit PERMISSION_DENIED event
            denied_events = [
                call for call in mock_emit.call_args_list
                if call[0][0].value == "permission:denied"
            ]
            assert len(denied_events) >= 1

    def test_timeout_returns_graceful_error(self):
        """Timed-out permission returns a graceful timeout error."""
        system = ToolPermissionSystem()
        req = system.request_permission("write_file", PermissionTier.SIDE_EFFECT, level="developer")
        req.timeout_seconds = 0.05
        system._pending[req.request_id] = req  # re-add with short timeout

        resolved = system.get_response(req, poll_interval=0.02)
        assert resolved.status == "timed_out"

    def test_confirm_destructive_requires_two_steps(self):
        """Destructive in developer mode requires approval + confirmation."""
        system = ToolPermissionSystem()
        req = system.request_permission(
            "delete_file", PermissionTier.DESTRUCTIVE,
            level="developer",
        )
        # With confirmation required, the response must pass confirmed=True
        system.respond_to_permission(req.request_id, approved=True, confirmed=True)
        assert req.request_id not in system._pending

    def test_personal_auto_approves_side_effect(self):
        """Personal mode auto-approves SIDE_EFFECT (no prompt)."""
        system = ToolPermissionSystem()
        req = system.request_permission("write_file", PermissionTier.SIDE_EFFECT, level="personal")
        assert req.status == "approved"

    def test_developer_requires_approval_for_side_effect(self):
        """Developer mode requires approval for SIDE_EFFECT."""
        system = ToolPermissionSystem()
        req = system.request_permission("write_file", PermissionTier.SIDE_EFFECT, level="developer")
        assert req.status == "pending"  # not auto-approved

    def test_tool_bridge_integration_classify(self):
        """Verify classify_tool returns expected tiers for common tools."""
        assert classify_tool("read_file", {}) == PermissionTier.READ_ONLY
        assert classify_tool("write_file", {}) == PermissionTier.SIDE_EFFECT
        assert classify_tool("delete_file", {}) == PermissionTier.DESTRUCTIVE
        assert classify_tool("run_command", {"command": "rm -rf /"}) == PermissionTier.DESTRUCTIVE


class TestPermissionEventBus:
    def test_auto_approve_does_not_emit_event(self):
        """Auto-approved requests do NOT emit PERMISSION_REQUEST events."""
        system = ToolPermissionSystem()
        with patch.object(system._bus, "emit") as mock_emit:
            system.request_permission("read_file", PermissionTier.READ_ONLY, level="developer")
            request_events = [
                call for call in mock_emit.call_args_list
                if call[0][0].value == "permission:request"
            ]
            assert len(request_events) == 0

    def test_pending_request_emits_event(self):
        """Pending requests emit PERMISSION_REQUEST event."""
        system = ToolPermissionSystem()
        with patch.object(system._bus, "emit") as mock_emit:
            system.request_permission("write_file", PermissionTier.SIDE_EFFECT, level="developer")
            request_events = [
                call for call in mock_emit.call_args_list
                if call[0][0].value == "permission:request"
            ]
            assert len(request_events) >= 1

    def test_destructive_emits_correct_timeout(self):
        """Destructive requests include longer timeout in event data."""
        system = ToolPermissionSystem()
        with patch.object(system._bus, "emit") as mock_emit:
            system.request_permission("delete_file", PermissionTier.DESTRUCTIVE, level="developer")
            for call in mock_emit.call_args_list:
                data = call[1].get("data", {})
                if data.get("tier") == "destructive":
                    assert data.get("timeout_seconds") == 60
                    assert data.get("requires_confirmation") is True
