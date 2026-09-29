"""Unit tests: vision token filtering (REQ-3, T3; REQ-16).

AC3.1  the isolated "what's" token is removed.
AC3.2  a multi-word contextual phrase is required for "what's" prompts.
"""

from __future__ import annotations

from backend.agent.tool_decision import (
    _VISION_PHRASES,
    _VISION_TOKENS,
    _vision_relevant,
)


class TestWhatsTokenRemoved:
    def test_whats_token_removed(self):
        """AC3.1: the isolated token "what's" is GONE from _VISION_TOKENS —
        it falsely fired on factual search queries."""
        assert "what's" not in _VISION_TOKENS
        assert "whats" not in _VISION_TOKENS

    def test_factual_whats_queries_do_not_fire(self):
        """A factual "what's" query with no vision token must not trigger a
        vision candidate menu."""
        assert _vision_relevant("what's the capital of France") is False
        assert _vision_relevant("what's the weather in Seattle") is False
        assert _vision_relevant("what's 2+2") is False


class TestMultiWordVisionPhraseRequired:
    def test_multi_word_vision_phrase_required(self):
        """AC3.2: a "what's" style prompt triggers vision only through a
        multi-word contextual phrase."""
        assert _VISION_PHRASES, "the phrase list must exist"
        assert _vision_relevant("what's on screen") is True
        assert _vision_relevant("look at the screen") is True
        assert _vision_relevant("what is on my screen") is True

    def test_real_vision_tokens_still_fire(self):
        """The real vision tokens are untouched — a sighted decision is
        still earned by them."""
        assert _vision_relevant("take a screenshot") is True
        assert _vision_relevant("find the button on the image") is True
        assert _vision_relevant("read the diagram") is True
