"""Unit tests for /api/chat Pydantic models and thread ID generation.

Associated implementation: backend/api/chat.py
Run with: python -m pytest backend/tests/test_chat_models.py -v
"""

import pytest
from pydantic import ValidationError
from backend.api.chat import (
    ChatRequest,
    ChatResponse,
    ChatError,
    ThreadInfo,
    ForkRequest,
)


class TestChatRequest:
    """Validates the ChatRequest model."""

    def test_valid_request(self):
        req = ChatRequest(text="Hello world")
        assert req.text == "Hello world"
        assert req.thread_id is None
        assert req.turn_id is None
        assert req.from_voice is False

    def test_with_all_fields(self):
        req = ChatRequest(
            text="Test message",
            thread_id="immortus:thread-test-abcd",
            turn_id="turn-123",
            from_voice=True,
        )
        assert req.text == "Test message"
        assert req.thread_id == "immortus:thread-test-abcd"
        assert req.turn_id == "turn-123"
        assert req.from_voice is True

    def test_empty_text_raises(self):
        with pytest.raises(ValidationError):
            ChatRequest(text="")

    def test_whitespace_text_raises(self):
        with pytest.raises(ValidationError):
            ChatRequest(text="   \n  ")

    def test_missing_text_raises(self):
        with pytest.raises(ValidationError):
            ChatRequest()


class TestChatResponse:
    """Validates the ChatResponse model."""

    def test_required_fields(self):
        resp = ChatResponse(
            content="Hello!",
            turn_id="abc-123",
            thread_id="immortus:thread-test-abcd",
            session_id="immortus:thread-test-abcd",
        )
        assert resp.content == "Hello!"
        assert resp.turn_id == "abc-123"
        assert resp.thread_id == resp.session_id

    def test_optional_fields_default(self):
        resp = ChatResponse(
            content="Hi",
            turn_id="t1",
            thread_id="immortus:thread-xxxx",
            session_id="immortus:thread-xxxx",
        )
        assert resp.thinking == ""
        assert resp.model == ""
        assert resp.timing_ms == 0

    def test_all_fields(self):
        resp = ChatResponse(
            content="Full response",
            thinking="Chain of thought...",
            turn_id="t1",
            thread_id="immortus:thread-full",
            session_id="immortus:thread-full",
            model="gpt-4",
            timing_ms=1234,
        )
        assert resp.thinking == "Chain of thought..."
        assert resp.model == "gpt-4"
        assert resp.timing_ms == 1234


class TestChatError:
    """Validates the ChatError model."""

    def test_error_fields(self):
        err = ChatError(error="Something failed", turn_id="t1", code="INTERNAL_ERROR")
        assert err.error == "Something failed"
        assert err.turn_id == "t1"
        assert err.code == "INTERNAL_ERROR"


class TestForkRequest:
    """Validates the ForkRequest model."""

    def test_valid_request(self):
        req = ForkRequest(message_id="msg-001")
        assert req.message_id == "msg-001"
        assert req.title is None

    def test_with_title(self):
        req = ForkRequest(message_id="msg-002", title="forked analysis")
        assert req.title == "forked analysis"

    def test_empty_message_id_raises(self):
        with pytest.raises(ValidationError):
            ForkRequest(message_id="")


class TestThreadIdGeneration:
    """Validates thread_id format matches ImmortusBrain."""

    def test_format(self):
        from backend.agent.immortus import generate_thread_id

        tid = generate_thread_id(prefix="swarm", suffix="abcd1234")
        assert tid == "immortus:thread-swar-1234"

    def test_prefix_truncated_to_4(self):
        from backend.agent.immortus import generate_thread_id

        tid = generate_thread_id(prefix="abcdef", suffix="test1234")
        assert tid == "immortus:thread-abcd-1234"

    def test_suffix_last_4(self):
        from backend.agent.immortus import generate_thread_id

        tid = generate_thread_id(prefix="test", suffix="verylongsuffixhere")
        assert tid.endswith("-here")

    def test_default_suffix_is_random(self):
        from backend.agent.immortus import generate_thread_id

        tid1 = generate_thread_id(prefix="test")
        tid2 = generate_thread_id(prefix="test")
        # Different random suffixes
        assert tid1 != tid2

    def test_default_prefix_is_anon(self):
        from backend.agent.immortus import generate_thread_id

        tid = generate_thread_id(suffix="abcd1234")
        assert tid.startswith("immortus:thread-anon-")

    def test_matches_immortus_brain(self):
        """The shared helper produces the same format as ImmortusBrain.

        Verifies format compatibility by inspecting the source — the
        shared ``generate_thread_id()`` function is used by both the REST
        endpoint and ``ImmortusBrain._assign_thread_id()``.
        """
        from backend.agent.immortus import generate_thread_id
        from backend.agent.immortus.brain import ImmortusBrain

        helper_tid = generate_thread_id(prefix="swarm", suffix="abcd1234")
        # ImmortusBrain._assign_thread_id now calls generate_thread_id() —
        # verify the format match directly
        assert helper_tid == "immortus:thread-swar-1234"
        assert helper_tid.count("-") == 2  # immortus:thread-XXXX-XXXX
        # Verify ImmortusBrain delegates to the shared function
        import inspect

        source = inspect.getsource(ImmortusBrain._assign_thread_id)
        assert "generate_thread_id" in source, (
            "ImmortusBrain._assign_thread_id() must delegate to "
            "generate_thread_id() to prevent format drift"
        )
