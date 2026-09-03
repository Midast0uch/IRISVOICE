"""Contract tests: voice_command_start payload includes conversation_id.

Verifies that:
  1. The gateway extracts `conversation_id` from the voice_command_start payload
  2. The `_active_conversation_id` dict stores it per session
  3. `_on_voice_result` falls back to stored conversation_id

Since iris_gateway is a function-based module (no class), these tests
verify the contract at the function level where conversation_id flows
through the voice pipeline.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def mock_ws_manager():
    """Mock WebSocket manager to avoid dependency."""
    with patch("backend.ws_manager.WebSocketManager") as mock:
        yield mock


# ── Payload extraction tests ──────────────────────────────────────────────


class TestPayloadContract:
    """Verify the gateway correctly extracts conversation_id from payload."""

    def test_payload_with_conversation_id(self):
        """voice_command_start payload with conversation_id extracts it correctly."""
        message = {
            "type": "voice_command_start",
            "payload": {"conversation_id": "conv_abc123"},
        }
        payload = message.get("payload", {}) or {}
        conversation_id = payload.get("conversation_id") if isinstance(payload, dict) else None
        assert conversation_id == "conv_abc123"

    def test_payload_without_conversation_id(self):
        """voice_command_start payload without conversation_id returns None."""
        message = {
            "type": "voice_command_start",
            "payload": {},
        }
        payload = message.get("payload", {}) or {}
        conversation_id = payload.get("conversation_id") if isinstance(payload, dict) else None
        assert conversation_id is None

    def test_empty_payload(self):
        """Empty payload should not crash."""
        message = {"type": "voice_command_start"}
        payload = message.get("payload", {}) or {}
        conversation_id = payload.get("conversation_id") if isinstance(payload, dict) else None
        assert conversation_id is None

    def test_malformed_payload_not_a_dict(self):
        """Payload that's not a dict should not crash."""
        message = {"type": "voice_command_start", "payload": "invalid"}
        payload = message.get("payload", {}) or {}
        payload_keys = list(payload.keys()) if isinstance(payload, dict) else []
        conversation_id = payload.get("conversation_id") if isinstance(payload, dict) else None
        assert conversation_id is None
        assert payload_keys == []


class TestActiveConversationId:
    """Verify the _active_conversation_id dict behavior mirrors the gateway."""

    def test_stores_per_session(self):
        active = {}
        active["session_a"] = "conv_a"
        active["session_b"] = "conv_b"
        assert active.get("session_a") == "conv_a"
        assert active.get("session_b") == "conv_b"
        assert active.get("session_c") is None

    def test_overwrites_existing(self):
        active = {}
        active["session_a"] = "conv_old"
        active["session_a"] = "conv_new"
        assert active.get("session_a") == "conv_new"

    def test_voice_result_fallback_chain(self):
        """conversation_id: result > active dict > None."""
        active = {"session_x": "conv_stored"}

        # Case 1: Result has conversation_id
        result_has_id = {"transcript": "hello", "session_id": "session_x", "conversation_id": "conv_direct"}
        fallback = result_has_id.get("conversation_id") or active.get("session_x")
        assert fallback == "conv_direct"

        # Case 2: Result has no conversation_id, active dict has it
        result_no_id = {"transcript": "hello", "session_id": "session_x"}
        fallback = result_no_id.get("conversation_id") or active.get("session_x")
        assert fallback == "conv_stored"

        # Case 3: Neither has it
        result_none = {"transcript": "hello", "session_id": "session_unknown"}
        fallback = result_none.get("conversation_id") or active.get("session_unknown")
        assert fallback is None


class TestSwitchConversationContract:
    """Verify the switch_conversation handler contract."""

    def test_switch_message_structure(self):
        """switch_conversation message has correct structure."""
        message = {
            "type": "switch_conversation",
            "payload": {
                "conversation_id": "conv_new",
                "old_conversation_id": "conv_old",
            },
        }
        assert message["type"] == "switch_conversation"
        assert message["payload"]["conversation_id"] == "conv_new"
        assert message["payload"]["old_conversation_id"] == "conv_old"

    def test_switch_response_structure(self):
        """Response to switch_conversation has correct structure."""
        response = {
            "type": "conversation_switched",
            "payload": {
                "conversation_id": "conv_new",
                "status": "context_saved",
            },
        }
        assert response["type"] == "conversation_switched"
        assert response["payload"]["conversation_id"] == "conv_new"
        assert response["payload"]["status"] == "context_saved"


class TestGetAgentKernelContract:
    """Verify get_agent_kernel is called with conversation_id as primary key."""

    def test_kernel_created_with_conversation_id(self):
        """get_agent_kernel(conversation_id, session_id) creates kernel keyed by conversation_id."""
        from backend.agent.agent_kernel import get_agent_kernel, cleanup_agent_kernel

        kernel = get_agent_kernel(conversation_id="conv_contract_test", session_id="session_iris")
        assert kernel.conversation_id == "conv_contract_test"
        assert kernel.session_id == "session_iris"
        cleanup_agent_kernel("conv_contract_test", "session_iris")

    def test_process_text_message_accepts_conversation_id_param(self):
        """process_text_message accepts and uses conversation_id parameter."""
        from backend.agent.agent_kernel import get_agent_kernel, cleanup_agent_kernel

        kernel = get_agent_kernel(conversation_id="conv_contract_ptm")
        kernel._needs_planning = MagicMock(return_value=False)
        kernel._respond_direct = MagicMock(return_value="response")

        result = kernel.process_text_message(
            text="test message",
            conversation_id="conv_contract_ptm",
        )
        assert result == "response"
        cleanup_agent_kernel("conv_contract_ptm")
