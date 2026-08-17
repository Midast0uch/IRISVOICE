"""Contract: the displayed/persisted answer is never the spoken short form.

`speak` and `show` are two RENDERINGS of one answer, not a short version that
replaces it. TTS gets the short line; the chat message gets the full text.

Observed live 2026-08-16: a 1492-char answer was persisted as 201 chars
(`der_response_len=1492` / `persisted assistant turn (len=201)`). The user saw
the full reply stream in and then collapse to a summary, because
`_process_structured_response` returned `speak` and the caller persisted that as
the assistant message.

A card is OPTIONAL presentation. It must never be the only place the content
exists.
"""

from __future__ import annotations

import json

import pytest

from backend.agent import agent_kernel as _ak


def _kernel():
    k = _ak.AgentKernel.__new__(_ak.AgentKernel)
    k._last_render_emitted = False
    k._last_spoken_text = ""
    return k


FULL = (
    "# System report\n\n"
    "| Item | Value |\n|---|---|\n| RAM | 32 GB |\n| OS | Windows 10 |\n\n"
    "The `dev` script runs `next dev -H 0.0.0.0`.\n"
) * 3
SHORT = "Here's what I gathered from the system and project files."


def _structured(monkeypatch, k, show):
    """Drive the REAL _process_structured_response with a given show payload."""
    monkeypatch.setattr(
        "backend.agent.structured_response.parse_structured_response",
        lambda _r: (SHORT, show),
    )
    monkeypatch.setattr(k, "_store_document_data", lambda **kw: None,
                        raising=False)
    return _ak.AgentKernel._process_structured_response(
        k, json.dumps({"speak": SHORT, "show": show or {}}),
        turn_id="t1", conversation_id="c1",
    )


class TestContentLivesInExactlyOnePlace:
    # REMOVED 2026-08-16: two tests that asserted "a `show` payload always
    # renders a card". That stopped being the contract — a card is now only for
    # an artifact turn, because rendering one for ordinary conversation is what
    # discarded the answer. Both branches are covered properly, against the real
    # function, by TestCardsAreForArtifactsNotConversation below; keeping a
    # weakened version of the old precondition here would have asserted the bug.

    def test_the_spoken_line_is_kept_separately_for_tts(self, monkeypatch):
        k = _kernel()
        monkeypatch.setattr(
            "backend.agent.structured_response.parse_structured_response",
            lambda _r: (SHORT, {"format": "markdown", "content": FULL}),
        )
        monkeypatch.setattr(k, "_store_document_data", lambda **kw: None,
                            raising=False)
        monkeypatch.setattr(_ak.AgentKernel, "_emit_document_render",
                            lambda *a, **kw: None, raising=False)

        _ak.AgentKernel._process_structured_response(
            k, json.dumps({"speak": SHORT, "show": {"content": FULL}}),
            turn_id="t1", conversation_id="c1",
        )
        assert k._last_spoken_text.strip() == SHORT.strip(), (
            "TTS lost the agent's own spoken line"
        )

    def test_a_stale_spoken_line_is_cleared_each_turn(self, monkeypatch):
        """A previous turn's speak must never be spoken for this one."""
        k = _kernel()
        k._last_spoken_text = "left over from the last answer"
        monkeypatch.setattr(
            "backend.agent.structured_response.parse_structured_response",
            lambda _r: ("", None),
        )
        _ak.AgentKernel._process_structured_response(
            k, "a plain text answer", turn_id="t", conversation_id="c",
        )
        assert k._last_spoken_text == "", "stale spoken text survived the turn"

    def test_plain_text_is_returned_unchanged(self, monkeypatch):
        """No structured JSON -> the text passes through in full."""
        k = _kernel()
        monkeypatch.setattr(
            "backend.agent.structured_response.parse_structured_response",
            lambda _r: ("", None),
        )
        monkeypatch.setattr(k, "_pacman_zone_for_turn", lambda: "chat",
                            raising=False)
        text = "A perfectly ordinary answer that should not be shortened."
        out = _ak.AgentKernel._process_structured_response(
            k, text, turn_id="t", conversation_id="c",
        )
        assert out == text

    def test_empty_response_stays_empty(self):
        k = _kernel()
        assert _ak.AgentKernel._process_structured_response(
            k, "", turn_id="t", conversation_id="c"
        ) == ""


class TestCardsAreForArtifactsNotConversation:
    """A card is for content stored to be reopened later — web results,
    generated markdown, plans, code. An ordinary answer is conversation and
    belongs in the thread as text.

    This is the case that kept truncating: the agent emitted a `show` payload
    for a plain "here is your system info" answer, the card branch returned the
    short spoken line to avoid duplication, and the real 1787-char answer was
    discarded (persisted as 201).
    """

    def _run(self, monkeypatch, zone):
        k = _kernel()
        monkeypatch.setattr(
            "backend.agent.structured_response.parse_structured_response",
            lambda _r: (SHORT, {"format": "markdown", "content": FULL}),
        )
        monkeypatch.setattr(k, "_store_document_data", lambda **kw: None,
                            raising=False)
        monkeypatch.setattr(k, "_pacman_zone_for_turn", lambda: zone,
                            raising=False)
        out = _ak.AgentKernel._process_structured_response(
            k, json.dumps({"speak": SHORT, "show": {"content": FULL}}),
            turn_id="t", conversation_id="c",
        )
        return k, out

    def test_conversational_turn_keeps_the_full_text_and_renders_no_card(
        self, monkeypatch
    ):
        k, out = self._run(monkeypatch, "chat")
        assert k._last_render_emitted is False, (
            "a conversational answer was turned into a document card"
        )
        assert FULL.strip() in out, (
            f"the answer was truncated to {len(out)} chars on a turn with no card"
        )

    def test_reference_turn_renders_a_card_and_does_not_duplicate_inline(
        self, monkeypatch
    ):
        k, out = self._run(monkeypatch, "reference")
        assert k._last_render_emitted is True, (
            "stored/reference content should render a card"
        )
        assert out.strip() == SHORT.strip()
        assert FULL.strip() not in out, "artifact duplicated into the thread"

    def test_the_spoken_line_survives_either_way(self, monkeypatch):
        for zone in ("chat", "reference"):
            k, _ = self._run(monkeypatch, zone)
            assert k._last_spoken_text.strip() == SHORT.strip(), (
                f"TTS lost the agent's spoken line on a {zone} turn"
            )
