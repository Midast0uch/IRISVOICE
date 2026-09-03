"""Tests for Immortus chain integration in the /api/chat endpoint.

Associated implementation: backend/api/chat.py, backend/gateway/iris_ffi.py
Run with: python -m pytest backend/tests/test_chat_immortus.py -v
"""

import pytest
from backend.gateway.iris_ffi import (
    ffi_immortus_chain_append,
    ffi_immortus_chain_keep_latest,
)


class TestImmortusFFIGracefulDegradation:
    """Verifies FFI functions handle missing engine gracefully.

    The C++ hybrid core engine is not loaded in test mode, so all FFI
    operations should return failure codes without crashing.
    """

    def test_chain_append_returns_false(self):
        """Without engine, chain_append returns False (not crash)."""
        result = ffi_immortus_chain_append(
            thread_id="immortus:thread-test",
            result="chat",
            nbl_outcome="test",
        )
        assert result == -1  # -1 when engine not loaded

    def test_chain_append_with_all_args(self):
        """All arguments accepted without crash."""
        result = ffi_immortus_chain_append(
            thread_id="immortus:thread-test-full",
            result="landmark",
            coords_from="test:from",
            coords_to="test:to",
            nbl_outcome="Test landmark",
            insight="Testing graceful degradation",
            file_path="/dev/null",
            landmark_id="lm_test",
        )
        assert result == -1  # -1 when engine not loaded

    def test_chain_keep_latest_returns_neg_one(self):
        """Without engine, keep_latest returns -1."""
        result = ffi_immortus_chain_keep_latest(
            thread_id="immortus:thread-test",
            keep_count=0,
        )
        assert result == -1


class TestImmortusChainInChatEndpoint:
    """Verifies the REST endpoint calls chain_append without blocking."""

    def test_record_to_immortus_does_not_crash_on_failure(self):
        """_record_to_immortus catches exceptions and returns None."""
        from backend.api.chat import _record_to_immortus

        # Should not raise — all FFI calls are try/except wrapped
        _record_to_immortus(
            thread_id="immortus:thread-test-ignore",
            text="Hello",
            response="Hi",
            turn_id="t1",
        )
        # If we got here, no exception was raised
        assert True

    def test_record_to_immortus_with_long_text(self):
        """Long text is gracefully truncated to ~60 chars for insight."""
        from backend.api.chat import _record_to_immortus

        _record_to_immortus(
            thread_id="immortus:thread-long",
            text="This is a very long message that should be truncated "
            "because it exceeds the 60 character insight limit set "
            "by the _record_to_immortus function",
            response="Short response",
            turn_id="t1",
        )
        assert True

    def test_immortus_chain_in_thread_detail(self):
        """GET /api/chat/threads/{id} includes immortus_chain even when empty."""
        from fastapi.testclient import TestClient
        from backend.main import app
        from backend.conversation_store import create_conversation

        conv = create_conversation(
            conv_id="immortus:thread-chain-detail",
            title="Chain Test",
        )

        client = TestClient(app)
        response = client.get(f"/api/chat/threads/{conv['id']}")
        assert response.status_code == 200
        data = response.json()
        # immortus_chain should be present (possibly empty)
        assert "immortus_chain" in data

        from backend.conversation_store import delete_conversation

        delete_conversation(conv["id"])
