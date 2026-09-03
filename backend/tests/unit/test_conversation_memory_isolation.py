"""
Unit test for per-conversation ConversationMemory isolation.

Regression guard for the cross-thread contamination bug: a NEW conversation
must NOT inherit message history from another thread in the same session.
Previously ConversationMemory was keyed only by session_id, so every thread
in a session shared one conversation.json (the leak reported against
specs/session-conversation-switching).
"""
import os

import pytest

from backend.agent.memory import ConversationMemory


def test_per_conversation_isolation_no_leak(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    s, c1, c2 = "sessX", "convA", "convB"

    mem1 = ConversationMemory(session_id=s, conversation_id=c1, max_messages=10)
    mem2 = ConversationMemory(session_id=s, conversation_id=c2, max_messages=10)

    # Distinct storage paths — the core of the fix.
    assert mem1.session_storage_path != mem2.session_storage_path
    assert str(mem1.session_storage_path).endswith(os.path.join("conversations", c1))
    assert str(mem2.session_storage_path).endswith(os.path.join("conversations", c2))

    # Both start empty.
    assert mem1.messages == []
    assert mem2.messages == []

    # Seed convA with a message and persist.
    mem1.add_message(role="user", content="secret from convA")

    # A freshly constructed convB must NOT see convA's message (no leakage).
    mem2b = ConversationMemory(session_id=s, conversation_id=c2, max_messages=10)
    assert mem2b.messages == [], "new conversation leaked another thread's history"

    # A freshly constructed convA MUST still see its own persisted message.
    mem1b = ConversationMemory(session_id=s, conversation_id=c1, max_messages=10)
    assert len(mem1b.messages) == 1
    assert mem1b.messages[0].content == "secret from convA"


def test_session_level_store_backward_compat(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    # No conversation_id -> legacy session-level path (unchanged behavior).
    mem = ConversationMemory(session_id="sessY", max_messages=10)
    assert str(mem.session_storage_path).endswith(os.path.join("sessions", "sessY"))
    assert "conversations" not in str(mem.session_storage_path)
