"""
Tests for iris_gateway.py patches (PR 2 of the Parakeet ASR plan).

Tests:
  - _text_response helper returns unique turn_id per call
  - _text_response includes all expected keys
  - _text_response respects caller-passed turn_id
  - _text_response appends optional fields (thinking, suggestions)

Integration tests for the WS router (voice_result, voice_audio_chunk)
belong in tests/e2e/test_voice_to_chat.py (PR 4).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ---- Test Plan ----
# The _text_response helper is a @staticmethod on IrisGateway.  To test it
# we instantiate the class once with mocks for the required positional
# __init__ arguments, then call the helper directly.


@pytest.fixture
def gateway():
    """
    Minimal IrisGateway instance with enough mocked internals to call
    _text_response without side effects.
    """
    from backend.iris_gateway import IRISGateway
    gw = IRISGateway.__new__(IRISGateway)
    gw._logger = MagicMock()
    gw._main_loop = MagicMock()
    return gw


class TestTextResponseHelper:
    """Verifies the _text_response static method on IrisGateway."""

    def test_returns_correct_type(self, gateway):
        msg = gateway._text_response("hello", "user")
        assert msg["type"] == "text_response"

    def test_includes_turn_id(self, gateway):
        msg = gateway._text_response("hello", "user")
        assert "turn_id" in msg
        assert isinstance(msg["turn_id"], str)
        assert len(msg["turn_id"]) > 0

    def test_turn_id_is_unique_per_call(self, gateway):
        uuids = {gateway._text_response("x", "user")["turn_id"] for _ in range(10)}
        assert len(uuids) == 10

    def test_text_and_sender_round_trip(self, gateway):
        msg = gateway._text_response("test text", "assistant")
        assert msg["text"] == "test text"
        assert msg["sender"] == "assistant"

    def test_passed_turn_id_is_used(self, gateway):
        msg = gateway._text_response("x", "user", turn_id="my-id")
        assert msg["turn_id"] == "my-id"

    def test_passed_turn_id_overrides_auto(self, gateway):
        msg = gateway._text_response("x", "user", turn_id="override-id")
        assert msg["turn_id"] == "override-id"
        # The default has length 12 (UUID hex), our override is custom
        assert msg["turn_id"] == "override-id"

    def test_thinking_field_is_included(self, gateway):
        msg = gateway._text_response("x", "assistant", thinking="chain of thought")
        assert msg.get("thinking") == "chain of thought"

    def test_thinking_is_absent_when_not_provided(self, gateway):
        msg = gateway._text_response("x", "assistant")
        assert "thinking" not in msg

    def test_suggestions_field_is_included(self, gateway):
        suggestions = [{"text": "yes"}, {"text": "no"}]
        msg = gateway._text_response("x", "assistant", suggestions=suggestions)
        assert msg.get("suggestions") == suggestions

    def test_extra_kwargs_are_included(self, gateway):
        msg = gateway._text_response("x", "user", extra_data={"a": 1})
        assert msg.get("extra_data") == {"a": 1}

    def test_function_ignores_none_thinking(self, gateway):
        msg = gateway._text_response("x", "assistant", thinking=None)
        assert "thinking" not in msg

    def test_function_ignores_none_suggestions(self, gateway):
        msg = gateway._text_response("x", "assistant", suggestions=None)
        assert "suggestions" not in msg
