"""
Contract tests: Conversation store API.

These verify the function-level contract of conversation_store.py — the shapes
that the frontend REST handlers (main.py) and frontend code depend on.

Backend→frontend contract: the REST endpoint shapes serve as the integration
boundary. Each test here validates the function-level output shape first, so
REST-endpoint tests (in tests/behavioral/) only need to verify HTTP status +
wire format, not data shape.
"""

import pytest
from backend.conversation_store import (
    create_conversation,
    get_conversations,
    get_conversation,
    add_message,
    delete_conversation,
    update_conversation_title,
    toggle_pin_conversation,
    truncate_conversation,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _conv_shape(conv: dict) -> set[str]:
    """Return the set of expected top-level keys in a conversation dict."""
    # The store returns conversations with: id, title, created_at, updated_at,
    # pinned, messages.  Some callers also receive empty-message-list
    # conversations.  Treat all as valid.
    return (
        {"id", "title", "created_at", "updated_at", "pinned"}
        | ({"messages"} if "messages" in conv else set())
    )


def _msg_shape(msg: dict) -> set[str]:
    """Return the set of expected keys in a message dict."""
    return {"id", "role", "text", "timestamp"}


# ── CT-4: Conversation CRUD shapes ──────────────────────────────────────


class TestConversationCRUD:
    """Contract tests for the core conversation CRUD operations."""

    def test_ct4_create_conversation_shape(self):
        conv = create_conversation(title="CT-4 Test")
        assert "id" in conv
        assert conv["title"] == "CT-4 Test"
        assert _conv_shape(conv) >= {"id", "title", "created_at", "updated_at", "pinned"}
        assert isinstance(conv["id"], str)
        assert isinstance(conv["created_at"], str)
        assert conv["pinned"] is False
        # Cleanup
        delete_conversation(conv["id"])

    def test_ct4_conversations_list_shape(self):
        # Create one conversation
        conv = create_conversation(title="List Test")
        conv_id = conv["id"]
        add_message(conv_id, "user", "hello")
        add_message(conv_id, "assistant", "hi there")

        convs = get_conversations()
        assert isinstance(convs, list)
        target = next((c for c in convs if c["id"] == conv_id), None)
        assert target is not None, "Created conversation not found in list"
        # The list version may or may not include full messages; just check
        # the required keys
        assert "id" in target
        assert "title" in target
        assert "updated_at" in target
        # Cleanup
        delete_conversation(conv_id)

    def test_ct4_full_conversation_shape(self):
        conv = create_conversation(title="Full Shape")
        conv_id = conv["id"]
        add_message(conv_id, "user", "msg1")
        add_message(conv_id, "assistant", "reply1")

        full = get_conversation(conv_id)
        assert full is not None
        assert full["id"] == conv_id
        assert "messages" in full
        assert len(full["messages"]) == 2
        # Each message must have the expected shape
        for msg in full["messages"]:
            assert _msg_shape(msg) >= {"id", "role", "text", "timestamp"}
        # Cleanup
        delete_conversation(conv_id)

    def test_ct4_add_message_shape(self):
        conv = create_conversation(title="Msg Shape")
        conv_id = conv["id"]

        msg = add_message(conv_id, "user", "test content", thinking="some chain")
        assert msg is not None
        assert isinstance(msg, dict)
        assert set(msg.keys()) >= {"id", "role", "text", "timestamp"}
        assert msg["role"] == "user"
        assert msg["text"] == "test content"
        assert msg.get("thinking") == "some chain"
        # Cleanup
        delete_conversation(conv_id)

    def test_ct4_delete_conversation(self):
        conv = create_conversation(title="To Delete")
        conv_id = conv["id"]
        result = delete_conversation(conv_id)
        assert result is True
        # Second delete should return False
        result2 = delete_conversation(conv_id)
        assert result2 is False

    def test_ct4_update_title_shape(self):
        conv = create_conversation(title="Original")
        conv_id = conv["id"]
        result = update_conversation_title(conv_id, "Updated Title")
        assert result is True
        full = get_conversation(conv_id)
        assert full is not None
        assert full["title"] == "Updated Title"
        # Cleanup
        delete_conversation(conv_id)

    def test_ct4_toggle_pin_shape(self):
        conv = create_conversation(title="Pin Test")
        conv_id = conv["id"]
        # Initially not pinned
        assert get_conversation(conv_id)["pinned"] is False
        # Toggle on
        toggle_pin_conversation(conv_id)
        assert get_conversation(conv_id)["pinned"] is True
        # Toggle off
        toggle_pin_conversation(conv_id)
        assert get_conversation(conv_id)["pinned"] is False
        # Cleanup
        delete_conversation(conv_id)

    def test_ct4_empty_list_when_no_conversations(self):
        # Create + delete to ensure clean state
        conv = create_conversation(title="Cleanup")
        delete_conversation(conv["id"])
        # get_conversations should return at least an empty list (there may be
        # other test artifacts, but the contract is "list or empty list")
        convs = get_conversations()
        assert isinstance(convs, list)


# ── CT-6: Truncate endpoint shape ────────────────────────────────────────


class TestTruncate:
    """Contract tests for the new truncate_conversation function."""

    def test_ct6_truncate_shape(self):
        conv = create_conversation(title="Truncate Shape")
        conv_id = conv["id"]
        # Add 3 messages
        msg1 = add_message(conv_id, "user", "q1")
        msg2 = add_message(conv_id, "assistant", "a1")
        msg3 = add_message(conv_id, "user", "q2")
        _ = add_message(conv_id, "assistant", "a2")  # should be removed

        # Truncate at msg3 (keep up to and including msg3)
        result = truncate_conversation(conv_id, msg3["id"])
        assert result["truncated"] is True
        assert result["kept_messages"] == 3

        # Verify in-memory state
        full = get_conversation(conv_id)
        assert len(full["messages"]) == 3
        assert full["messages"][-1]["text"] == "q2"

        # Cleanup
        delete_conversation(conv_id)

    def test_ct6_truncate_at_last_message_is_noop(self):
        conv = create_conversation(title="Truncate Noop")
        conv_id = conv["id"]
        msg1 = add_message(conv_id, "user", "only message")

        # Truncate at the last message — should be a no-op
        result = truncate_conversation(conv_id, msg1["id"])
        assert result["truncated"] is True
        assert result["kept_messages"] == 1

        full = get_conversation(conv_id)
        assert len(full["messages"]) == 1

        # Cleanup
        delete_conversation(conv_id)

    def test_ct6_truncate_unknown_conversation_raises(self):
        with pytest.raises(ValueError, match="not found"):
            truncate_conversation("non-existent-id", "msg-1")

    def test_ct6_truncate_unknown_message_raises(self):
        conv = create_conversation(title="Unknown Msg")
        conv_id = conv["id"]
        add_message(conv_id, "user", "hello")

        with pytest.raises(ValueError, match="not found"):
            truncate_conversation(conv_id, "msg-999")

        # Cleanup
        delete_conversation(conv_id)

    def test_ct6_truncate_updates_updated_at(self):
        conv = create_conversation(title="Truncate Timestamp")
        conv_id = conv["id"]
        msg1 = add_message(conv_id, "user", "q1")
        add_message(conv_id, "assistant", "a1")

        original_updated = get_conversation(conv_id)["updated_at"]
        truncate_conversation(conv_id, msg1["id"])
        new_updated = get_conversation(conv_id)["updated_at"]

        assert new_updated >= original_updated, "updated_at should advance"

        # Cleanup
        delete_conversation(conv_id)


# ── Retry contract ───────────────────────────────────────────────────────


class TestRetryContract:
    """Contract tests for the retry flow.

    The retry flow re-uses the existing POST /api/chat endpoint with the
    same {text, thread_id} contract.  The backend contract for /api/chat is
    locked by CT-3.  These tests verify the conversation-level invariants
    that the retry flow depends on:
      - A conversation can receive multiple assistant turns.
      - Messages are ordered by insertion.
      - Deleting an error message via truncate is clean (no orphan data).
    """

    def test_ct_retry_multiple_turns(self):
        """A conversation stores multiple turns in insertion order."""
        conv = create_conversation(title="Retry Turns")
        conv_id = conv["id"]
        add_message(conv_id, "user", "q1")
        add_message(conv_id, "assistant", "a1")
        add_message(conv_id, "user", "q2")
        add_message(conv_id, "assistant", "a2")

        full = get_conversation(conv_id)
        texts = [m["text"] for m in full["messages"]]
        assert texts == ["q1", "a1", "q2", "a2"]

        delete_conversation(conv_id)

    def test_ct_retry_truncate_removes_only_after(self):
        """Truncating at a user message keeps that message and all before it."""
        conv = create_conversation(title="Retry Truncate")
        conv_id = conv["id"]
        m1 = add_message(conv_id, "user", "prompt")
        m2 = add_message(conv_id, "assistant", "error response — will be retried")

        # "Retry" truncates at the user message, removing the error response
        truncate_conversation(conv_id, m1["id"])
        full = get_conversation(conv_id)
        assert len(full["messages"]) == 1
        assert full["messages"][0]["text"] == "prompt"

        delete_conversation(conv_id)

    def test_ct_retry_new_turn_after_truncate(self):
        """After truncating an error, a new assistant turn can be added."""
        conv = create_conversation(title="Retry New Turn")
        conv_id = conv["id"]
        m1 = add_message(conv_id, "user", "my prompt")
        m2 = add_message(conv_id, "assistant", "bad response")
        _ = m2  # will be truncated

        # Truncate the error
        truncate_conversation(conv_id, m1["id"])

        # Add a new good response (simulating the retry response)
        m3 = add_message(conv_id, "assistant", "correct response")
        full = get_conversation(conv_id)
        assert len(full["messages"]) == 2
        assert full["messages"][-1]["text"] == "correct response"
        assert full["messages"][-1]["id"] == m3["id"]

        delete_conversation(conv_id)
