"""Contract (specs/reply-surface-contract REQ-3, task T8 — CT-4): on a card
turn the BUBBLE is the agent's ``speak`` line — never the card body, never an
excerpt invented by the kernel, never empty while a speak line exists.

The card owns the artifact; the bubble carries the conversational line. All
four seam exits are driven against the REAL ``_process_structured_response``:

1. ``show`` + ``speak`` + render    -> bubble == speak
2. ``show`` + ``speak`` + emit fail -> full show content falls back into bubble
3. ``show`` + no ``speak`` + render -> short supportive excerpt (not the body)
4. ``show`` + no ``speak`` + fail   -> full show content (only copy)

BT-2 (behavioral) shares these fixtures.
"""

from __future__ import annotations

import json

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.event_bus import IRISStreamEvent


CONTENT = (
    "# Quarterly plan\n\n"
    "## Q1\n\n"
    "- Ship the renderer\n"
    "- Land the contract tests\n\n"
    "## Q2\n\n"
    "| Task | Owner |\n|---|---|\n| TTS lane | kernel |\n"
)
SPEAK = "Here is the quarterly plan — Q1 ships the renderer, Q2 lands tests."


class _Bus:
    """Records DOCUMENT_RENDER payloads; can simulate an emit failure."""

    def __init__(self, fail: bool = False):
        self.renders = []
        self.fail = fail

    def emit(self, event, data=None, **kw):
        if self.fail:
            raise RuntimeError("simulated transport failure")
        if event == IRISStreamEvent.DOCUMENT_RENDER:
            self.renders.append(data)


@pytest.fixture
def kernel_and_bus(monkeypatch):
    def _make(fail: bool = False):
        k = AgentKernel.__new__(AgentKernel)
        k._last_render_emitted = False
        k._last_spoken_text = ""
        monkeypatch.setattr(k, "_pacman_zone_for_turn", lambda: "trusted-zone",
                            raising=False)
        monkeypatch.setattr(k, "_store_document_data", lambda **kw: None,
                            raising=False)
        bus = _Bus(fail=fail)
        monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: bus)
        return k, bus

    return _make


def _card_turn(k, speak=SPEAK, content=CONTENT):
    payload = {"show": {"format": "markdown", "content": content}}
    if speak is not None:
        payload["speak"] = speak
    return AgentKernel._process_structured_response(
        k, json.dumps(payload), turn_id="t1", conversation_id="c1"
    )


class TestBubbleIsTheSpeakLine:
    def test_bubble_is_exactly_the_speak_line(self, kernel_and_bus):
        k, bus = kernel_and_bus()
        out = _card_turn(k)
        assert len(bus.renders) == 1, "card must render on a show turn"
        assert out == SPEAK, "bubble must be the agent's speak line"
        assert k._last_spoken_text == SPEAK, "TTS lane lost the speak line"

    def test_bubble_never_duplicates_the_card_body(self, kernel_and_bus):
        k, bus = kernel_and_bus()
        out = _card_turn(k)
        body = bus.renders[0]["content"]
        assert body == CONTENT
        assert out != body
        assert body not in out, "the card body leaked into the bubble"

    def test_full_body_lives_on_the_card_not_in_the_bubble(self, kernel_and_bus):
        k, bus = kernel_and_bus()
        out = _card_turn(k)
        assert len(out) < len(CONTENT), (
            "the bubble carried the document body — duplication"
        )


class TestCardExitFallbacks:
    def test_emit_failure_returns_the_full_show_content(self, kernel_and_bus):
        """When the card cannot emit, the bubble is the only copy — it must
        carry the FULL show content (the seam strips outer whitespace on this
        exit — pre-existing behavior), never an excerpt, and TTS keeps speak."""
        k, bus = kernel_and_bus(fail=True)
        out = _card_turn(k)
        assert bus.renders == []
        assert out == CONTENT.strip(), "emit failure must not discard the document"
        assert k._last_spoken_text == SPEAK

    def test_no_speak_line_gets_a_supportive_excerpt(self, kernel_and_bus):
        """`show` without `speak`: the bubble gets a short supportive excerpt
        so the thread is not empty — never the full body, never raw JSON."""
        k, bus = kernel_and_bus()
        out = _card_turn(k, speak=None)
        assert len(bus.renders) == 1
        assert out, "the bubble must not be empty when content exists"
        assert len(out) < len(CONTENT), (
            "without a speak line the bubble is a derived excerpt, not the body"
        )
        assert "{" not in out[:1], "raw JSON leaked into the bubble"

    def test_no_speak_and_emit_failure_keeps_the_full_document(
        self, kernel_and_bus
    ):
        k, bus = kernel_and_bus(fail=True)
        out = _card_turn(k, speak=None)
        assert bus.renders == []
        assert out == CONTENT, "the last copy of the document was dropped"
