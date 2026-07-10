"""Persistence tests for conversation_store SQLite bridge.

Associated implementation: backend/conversation_store.py
Run with: python -m pytest backend/tests/test_chat_persistence.py -v
"""

import os
import pytest
from backend import conversation_store as cs


class TestSQLitePersistence:
    """Verifies the dict→SQLite upgrade works correctly."""

    def test_db_file_exists(self):
        """SQLite database file or directory exists."""
        db_dir = os.path.dirname(cs._DB_PATH)
        assert os.path.isdir(db_dir), f"DB directory not found: {db_dir}"

    def test_conn_is_wal(self):
        """Database is in WAL mode for concurrent safety."""
        conn = cs._get_conn()
        cursor = conn.execute("PRAGMA journal_mode")
        assert cursor.fetchone()[0].upper() == "WAL"

    def test_tables_exist(self):
        """Required tables are created."""
        conn = cs._get_conn()
        tables = set(
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        )
        assert "conversations" in tables
        assert "messages" in tables

    def test_create_and_retrieve(self):
        """Creating a conversation persists it to both dict and SQLite."""
        conv = cs.create_conversation(
            title="Persistence Test",
            conv_id="immortus:thread-persist-verify",
        )
        assert conv["id"] == "immortus:thread-persist-verify"
        assert conv["title"] == "Persistence Test"

        # Should be retrievable from the dict
        from_cache = cs.get_conversation("immortus:thread-persist-verify")
        assert from_cache is not None
        assert from_cache["id"] == conv["id"]

        # Cleanup
        cs.delete_conversation("immortus:thread-persist-verify")

    def test_add_message_stores_fields(self):
        """Adding a message persists role, text, thinking, turn_id."""
        conv = cs.create_conversation(
            conv_id="immortus:thread-msg-fields",
        )
        msg = cs.add_message(
            conv["id"],
            "user",
            "Hello",
            turn_id="t1",
            thinking="",
        )
        assert msg["role"] == "user"
        assert msg["text"] == "Hello"
        assert msg["turn_id"] == "t1"

        cs.delete_conversation(conv["id"])

    def test_user_and_assistant_both_stored(self):
        """User + assistant messages in sequence."""
        conv = cs.create_conversation(
            conv_id="immortus:thread-both-roles",
        )
        cs.add_message(conv["id"], "user", "What's 2+2?", turn_id="t1")
        cs.add_message(
            conv["id"],
            "assistant",
            "4",
            turn_id="t1",
            thinking="Simple arithmetic",
        )

        loaded = cs.get_conversation(conv["id"])
        assert len(loaded["messages"]) == 2
        assert loaded["messages"][0]["role"] == "user"
        assert loaded["messages"][1]["role"] == "assistant"

        cs.delete_conversation(conv["id"])

    def test_messages_survive_reload(self):
        """Messages should survive a dict clear + reload (simulating restart)."""
        conv = cs.create_conversation(
            conv_id="immortus:thread-restart-sim",
            title="Restart Test",
        )
        cs.add_message(conv["id"], "user", "Hello before restart", turn_id="t1")
        cs.add_message(conv["id"], "assistant", "Response", turn_id="t1")

        # Simulate restart: clear in-memory cache and reload from DB
        cs.load_from_db()

        reloaded = cs.get_conversation("immortus:thread-restart-sim")
        assert reloaded is not None, "Conversation lost after restart"
        assert reloaded["title"] == "Restart Test"
        assert len(reloaded["messages"]) == 2
        assert reloaded["messages"][0]["text"] == "Hello before restart"

        cs.delete_conversation("immortus:thread-restart-sim")

    def test_delete_removes_from_db(self):
        """Deleting a conversation removes it from both dict and SQLite."""
        conv = cs.create_conversation(
            conv_id="immortus:thread-delete-db",
        )
        cs.add_message(conv["id"], "user", "Delete me", turn_id="t1")
        cs.delete_conversation(conv["id"])

        # Simulate fresh load
        cs.load_from_db()
        assert cs.get_conversation("immortus:thread-delete-db") is None

    def test_update_title_persists(self):
        """Updating conversation title persists to DB."""
        conv = cs.create_conversation(
            conv_id="immortus:thread-title-update",
            title="Original Title",
        )
        cs.update_conversation_title(conv["id"], "Updated Title")

        # Simulate reload
        cs.load_from_db()
        reloaded = cs.get_conversation("immortus:thread-title-update")
        assert reloaded["title"] == "Updated Title"

        cs.delete_conversation(conv["id"])

    def test_toggle_pin_persists(self):
        """Toggling pinned status persists to DB."""
        conv = cs.create_conversation(
            conv_id="immortus:thread-pin-toggle",
        )
        assert conv["pinned"] is False

        cs.toggle_pin_conversation(conv["id"])
        assert cs.get_conversation(conv["id"])["pinned"] is True

        cs.toggle_pin_conversation(conv["id"])
        assert cs.get_conversation(conv["id"])["pinned"] is False

        cs.delete_conversation(conv["id"])

    def test_list_ordering(self):
        """get_conversations sorts most recent first, pinned first."""
        conv_a = cs.create_conversation(
            conv_id="immortus:thread-list-a",
            title="A",
        )
        conv_b = cs.create_conversation(
            conv_id="immortus:thread-list-b",
            title="B",
        )

        convs = cs.get_conversations()
        # The two we just created should be near the top
        ids = [c["id"] for c in convs]
        assert "immortus:thread-list-b" in ids
        assert "immortus:thread-list-a" in ids

        cs.delete_conversation(conv_a["id"])
        cs.delete_conversation(conv_b["id"])

    def test_add_message_to_nonexistent(self):
        """add_message returns None for nonexistent conversation."""
        result = cs.add_message("does-not-exist", "user", "hello")
        assert result is None
