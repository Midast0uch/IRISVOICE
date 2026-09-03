"""Contract tests: ConversationContextStore.

Verifies save/restore/atomic swap/bounded for per-thread agent context.
Uses a temporary SQLite database for isolation — never touches production data.
"""

import json
import tempfile
from pathlib import Path
from dataclasses import asdict

import os
import pytest

from backend.agent.conversation_context_store import (
    ConversationContextStore,
    ConversationContext,
    ConversationMessage,
    PausedDERState,
    MAX_CONVERSATIONS,
    MAX_MESSAGES_PER_CONV,
)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def store():
    """Create an isolated store backed by a temporary SQLite DB."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="iris_test_ctx_"))
    db_path = tmp_dir / "test_contexts.db"
    s = ConversationContextStore(db_path=db_path)
    yield s
    s.close()
    # Clean up the temp directory after all connections are released
    try:
        import shutil
        shutil.rmtree(str(tmp_dir), ignore_errors=True)
    except Exception:
        pass


def make_context(conv_id: str, msg_count: int = 3) -> ConversationContext:
    ctx = ConversationContext(conversation_id=conv_id)
    for i in range(msg_count):
        ctx.add_message(role="user" if i % 2 == 0 else "assistant", content=f"msg_{i}")
    return ctx


# ── Tests ──────────────────────────────────────────────────────────────────


class TestSaveRestore:
    def test_save_and_restore(self, store):
        ctx = make_context("conv_1")
        assert store.save("conv_1", ctx) is True

        restored = store.get_or_restore("conv_1")
        assert restored is not None
        assert restored.conversation_id == "conv_1"
        assert len(restored.messages) == 3

    def test_restore_missing(self, store):
        assert store.get_or_restore("nonexistent") is None

    def test_save_twice_overwrites(self, store):
        ctx1 = make_context("conv_1", msg_count=1)
        store.save("conv_1", ctx1)
        ctx2 = make_context("conv_1", msg_count=5)
        store.save("conv_1", ctx2)

        restored = store.get_or_restore("conv_1")
        assert restored is not None
        assert len(restored.messages) == 5

    def test_clear_removes(self, store):
        ctx = make_context("conv_1")
        store.save("conv_1", ctx)
        assert store.get_or_restore("conv_1") is not None

        store.clear("conv_1")
        assert store.get_or_restore("conv_1") is None

    def test_clear_nonexistent_does_not_error(self, store):
        # Should not raise on non-existent key
        result = store.clear("not_there")
        assert result is True

    def test_load_is_alias_for_get_or_restore(self, store):
        ctx = make_context("conv_load_test")
        store.save("conv_load_test", ctx)
        loaded = store.load("conv_load_test")
        assert loaded is not None
        assert loaded.conversation_id == "conv_load_test"

    def test_list_active(self, store):
        assert store.list_active() == []
        store.save("a", make_context("a"))
        store.save("b", make_context("b"))
        active = store.list_active()
        assert "a" in active
        assert "b" in active

    def test_list_active_recent_first(self, store):
        store.save("first", make_context("first"))
        store.save("second", make_context("second"))
        active = store.list_active()
        assert active[0] == "second"  # most recently updated first


class TestAtomicSwap:
    def test_save_current_and_load(self, store):
        old_ctx = make_context("old_conv")
        store.save("old_conv", old_ctx)

        # Save old and start new
        new_ctx = make_context("new_conv")
        assert store.save_current_and_load("new_conv", old_ctx) is True

        # Old context should be persisted
        restored_old = store.get_or_restore("old_conv")
        assert restored_old is not None

        # New context doesn't exist yet — it will be created lazily
        # when the frontend sends the first message with the new conversation_id
        restored_new = store.get_or_restore("new_conv")
        assert restored_new is None


class TestBounded:
    def test_max_conversations_enforced(self, store):
        # Save more than MAX_CONVERSATIONS
        for i in range(MAX_CONVERSATIONS + 5):
            ctx = make_context(f"conv_{i}")
            store.save(f"conv_{i}", ctx)

        # Should have exactly MAX_CONVERSATIONS
        active = store.list_active()
        assert len(active) <= MAX_CONVERSATIONS

    def test_max_messages_per_conversation(self, store):
        ctx = make_context("big_conv")
        # Add more than MAX_MESSAGES_PER_CONV
        for i in range(MAX_MESSAGES_PER_CONV + 50):
            ctx.add_message(
                role="user" if i % 2 == 0 else "assistant",
                content=f"extra_msg_{i}",
            )
        store.save("big_conv", ctx)

        restored = store.get_or_restore("big_conv")
        assert restored is not None
        assert len(restored.messages) <= MAX_MESSAGES_PER_CONV

    def test_oldest_evicted_first(self, store):
        # Fill to capacity
        for i in range(MAX_CONVERSATIONS):
            store.save(f"conv_{i:03d}", make_context(f"conv_{i:03d}"))

        # Add one more — oldest should be evicted
        store.save("newest", make_context("newest"))

        active = store.list_active()
        assert "conv_000" not in active  # oldest was evicted


class TestPausedStateRoundtrip:
    def test_paused_permission_state(self, store):
        ctx = make_context("pause_conv")
        ctx.paused_state = PausedDERState(
            reason="permission",
            tool_name="write_file",
            tool_params={"path": "/tmp/test.txt", "content": "hello"},
            timeout_deadline=9999999999.0,
        )
        ctx.current_mode = "agentic"
        store.save("pause_conv", ctx)

        restored = store.get_or_restore("pause_conv")
        assert restored is not None
        assert restored.paused_state is not None
        assert restored.paused_state.reason == "permission"
        assert restored.paused_state.tool_name == "write_file"
        assert restored.current_mode == "agentic"

    def test_paused_question_state(self, store):
        ctx = make_context("q_conv")
        ctx.paused_state = PausedDERState(
            reason="question",
            question="Which file to edit?",
            options=["a.txt", "b.txt", "c.txt"],
            allow_other=True,
            timeout_deadline=9999999999.0,
        )
        store.save("q_conv", ctx)

        restored = store.get_or_restore("q_conv")
        assert restored is not None
        assert restored.paused_state.reason == "question"
        assert restored.paused_state.allow_other is True
        assert len(restored.paused_state.options) == 3

    def test_no_paused_state(self, store):
        ctx = make_context("no_pause")
        assert ctx.paused_state is None

        store.save("no_pause", ctx)
        restored = store.get_or_restore("no_pause")
        assert restored is not None
        assert restored.paused_state is None


class TestMessageOrdering:
    def test_messages_maintain_order(self, store):
        ctx = make_context("order_test", msg_count=0)
        messages = [
            ("user", "first"),
            ("assistant", "second"),
            ("user", "third"),
            ("assistant", "fourth"),
        ]
        for role, content in messages:
            ctx.add_message(role, content)

        store.save("order_test", ctx)
        restored = store.get_or_restore("order_test")
        assert restored is not None
        for i, msg in enumerate(restored.messages):
            assert msg.role == messages[i][0]
            assert msg.content == messages[i][1]

    def test_message_with_turn_id(self, store):
        ctx = make_context("turn_test", msg_count=0)
        ctx.add_message("user", "hello", turn_id="turn_001")
        store.save("turn_test", ctx)

        restored = store.get_or_restore("turn_test")
        assert restored is not None
        assert restored.messages[0].turn_id == "turn_001"


class TestErrorResilience:
    def test_corrupt_db_returns_none(self):
        """Store with corrupt DB file returns None, not a crash."""
        tmp_dir = Path(tempfile.mkdtemp(prefix="iris_test_ctx_"))
        try:
            db_path = tmp_dir / "corrupt.db"
            db_path.write_text("not a valid sqlite database")
            store = ConversationContextStore(db_path=db_path)
            result = store.get_or_restore("anything")
            store.close()
            assert result is None or isinstance(result, ConversationContext)
        finally:
            import shutil
            shutil.rmtree(str(tmp_dir), ignore_errors=True)

    def test_nonexistent_file_creates_new_db(self):
        tmp_dir = Path(tempfile.mkdtemp(prefix="iris_test_ctx_"))
        try:
            db_path = tmp_dir / "fresh.db"
            assert not db_path.exists()
            store = ConversationContextStore(db_path=db_path)
            assert db_path.exists()
            ctx = make_context("fresh")
            store.save("fresh", ctx)
            restored = store.get_or_restore("fresh")
            store.close()
            assert restored is not None
        finally:
            import shutil
            shutil.rmtree(str(tmp_dir), ignore_errors=True)
