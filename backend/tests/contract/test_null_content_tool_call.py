"""Contract: a tool-call-only response (content=null) must not crash.

Every OpenAI-compatible provider returns ``message.content = null`` when the
model replies with tool_calls and no prose. That is the NORMAL shape of a tool
call, not an edge case.

``_msg.get("content", "")`` does not defend against it — the default only
applies when the key is ABSENT, and here it is present-and-null. The None then
reached ``parse_thinking`` and raised::

    TypeError: expected string or bytes-like object, got 'NoneType'

Observed live 2026-08-16 at DER step 5 with Brain=ollama / Tool=cohere: tool
resolution died, the step was classified permanent, and the turn never produced
the combined answer.
"""

from __future__ import annotations

import pytest

from backend.agent.inference.transport import parse_thinking


class TestParseThinkingAcceptsNull:
    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_empty_or_null_is_not_an_error(self, value):
        thinking, clean = parse_thinking(value)
        assert thinking == ""
        assert clean in ("", "   ")

    def test_normal_text_still_parses(self):
        thinking, clean = parse_thinking("<think>reasoning</think>the answer")
        assert thinking == "reasoning"
        assert "the answer" in clean

    def test_untagged_text_passes_through(self):
        thinking, clean = parse_thinking("just an answer")
        assert "just an answer" in clean


class TestNullContentExtraction:
    """The `.get(key, default)` trap that caused it."""

    def test_present_and_null_defeats_the_default(self):
        msg = {"content": None, "tool_calls": [{"id": "1"}]}
        assert msg.get("content", "") is None, (
            "if this ever returns '' the trap is gone and the guards below "
            "can be revisited"
        )
        assert (msg.get("content") or "") == "", "the `or` form is what works"

    def test_a_tool_call_with_no_text_is_a_valid_response(self):
        """content=null + tool_calls present must not be treated as empty."""
        msg = {"content": None, "tool_calls": [{"id": "1", "type": "function"}]}
        _reply = msg.get("content") or ""
        _tool_calls = msg.get("tool_calls") or []
        assert not (not _reply and not _tool_calls), (
            "a tool-call-only response was misread as an empty response"
        )
        # And the reply is now safe to parse.
        assert parse_thinking(_reply) == ("", "")
