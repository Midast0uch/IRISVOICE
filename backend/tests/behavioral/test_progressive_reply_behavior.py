"""Behavioral (specs/reply-surface-contract REQ-13, task T19 — BT-8).

One real reply turn, driven the way the DER path runs it:

  helper speak-first stream -> seam (card render) -> bubble = speak

asserting the emergent outcomes: the user hears the speak line before the
card exists; the card renders exactly once, in place-keying shape; and the
turn's metrics show ttft BEFORE the card (time-to-first-token strictly
earlier-or-equal to time-to-card).
"""

from __future__ import annotations

import json

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.event_bus import IRISStreamEvent
from backend.utils.observability import TurnMetrics


class _Bus:
    def __init__(self):
        self.events = []

    def emit(self, event, data=None, **kw):
        if event == IRISStreamEvent.DOCUMENT_RENDER:
            self.events.append(data)


@pytest.fixture
def turn(monkeypatch):
    def _turn(response: str):
        k = AgentKernel.__new__(AgentKernel)
        k._last_render_emitted = False
        k._last_spoken_text = ""
        monkeypatch.setattr(k, "_pacman_zone_for_turn", lambda: "reference",
                            raising=False)
        monkeypatch.setattr(k, "_store_document_data", lambda **kw: None,
                            raising=False)
        bus = _Bus()
        monkeypatch.setattr("backend.agent.event_bus.get_event_bus",
                            lambda: bus)
        metrics = TurnMetrics(turn_id="t-bt8")
        k._active_turn_metrics = metrics
        chunks = []
        # DER-path order: progressive emit, then the seam.
        k._emit_reply_progressively(response, "t-bt8", chunk_callback=chunks.append)
        metrics.mark_first_token()
        out = AgentKernel._process_structured_response(
            k, response, turn_id="t-bt8", conversation_id="c-bt8"
        )
        return out, k, bus, metrics, chunks

    return _turn


def test_bt8_speak_first_card_second_bubble_is_speak(turn):
    speak = "The report is on the card."
    body = "# Report\n\n" + ("Body paragraph. " * 30)
    response = json.dumps({
        "speak": speak,
        "show": {"format": "markdown", "content": body},
    })
    out, k, bus, metrics, chunks = turn(response)
    assert chunks[0] == speak, "the speak line is the first thing streamed"
    assert len(bus.events) == 1, "exactly one card"
    assert out == speak, "the bubble is the speak line"
    assert metrics.ttft_ms is not None and metrics.card_ms is not None
    assert metrics.ttft_ms <= metrics.card_ms, (
        "the card rendered before the first token"
    )


def test_bt8_plain_turn_streams_full_text_never_partial(turn):
    text = "A plain answer that flows straight to the bubble."
    out, k, bus, metrics, chunks = turn(text)
    assert chunks[0] == text
    assert bus.events == []
    assert out == text
    assert metrics.card_ms is None, "no card -> no time-to-card"
