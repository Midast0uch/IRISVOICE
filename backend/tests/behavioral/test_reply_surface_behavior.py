"""Behavioral (specs/reply-surface-contract, task T10 — BT-1..BT-5, BT-9, BT-10).

Full-turn drives through the REAL ``_process_structured_response`` seam on a
real kernel, asserting emergent reply-surface behavior:

- BT-1:  a 1500-char plain answer -> plain bubble IN FULL, no card.
- BT-2:  a ``show`` artifact -> card + the supportive speak line, TTS = speak.
- BT-3:  TTS = ``speak`` on every lane that defines one; plain turns leave
         the spoken lane empty for the gateway's prepare_spoken_text fallback.
- BT-4:  (retired, reply-surface audit Phase A) the backend phrase test that
         demoted an "I found nothing" `show` to plain text is deleted: a `show`
         is a card, and the model decides what to keep.
- BT-5:  a non-empty websearch synthesis WITHOUT ``show`` still renders no
         card (old auto-render deleted) — the plain answer is the surface.
- BT-9:  the reply completes unchanged with the decision engine stopped.
- BT-10: the same reply twice -> same surface (deterministic lanes).

Each gap decomposes to its contract test (BT-1 -> CT-3, BT-2 -> CT-4,
BT-9/BT-10 -> CT-10/CT-12).
"""

from __future__ import annotations

import json

import pytest

from backend.agent.agent_kernel import AgentKernel
from backend.agent.event_bus import IRISStreamEvent


class _Bus:
    def __init__(self):
        self.renders = []

    def emit(self, event, data=None, **kw):
        if event == IRISStreamEvent.DOCUMENT_RENDER:
            self.renders.append(data)


@pytest.fixture
def turn(monkeypatch):
    """Drive one reply through the real seam; return (out, kernel, bus)."""

    def _turn(response: str, zone: str = "chat"):
        k = AgentKernel.__new__(AgentKernel)
        k._last_render_emitted = False
        k._last_spoken_text = ""
        monkeypatch.setattr(k, "_pacman_zone_for_turn", lambda: zone,
                            raising=False)
        monkeypatch.setattr(k, "_store_document_data", lambda **kw: None,
                            raising=False)
        bus = _Bus()
        monkeypatch.setattr("backend.agent.event_bus.get_event_bus",
                            lambda: bus)
        out = AgentKernel._process_structured_response(
            k, response, turn_id="t-bt", conversation_id="c-bt"
        )
        return out, k, bus

    return _turn


# BT-1 fixture: a substantial CONVERSATIONAL answer (no show payload).
LONG_ANSWER = (
    "Your system has 32 GB of RAM installed and Windows 11 Pro build 26100. "
    "The dev server runs next dev on port 3000 with Turbopack enabled. "
    "The backend listens on 8000 and serves the websocket bridge. "
    "Porcupine wake-word detection is active with two keywords loaded. "
) * 8  # ~1500+ chars

SHOW_PAYLOAD = json.dumps({
    "speak": "I wrote the report — it's on the card.",
    "show": {
        "format": "markdown",
        "content": "# Report\n\nFull body of the artifact lives here.\n",
    },
})


def test_bt1_long_plain_answer_stays_a_full_bubble_with_no_card(turn):
    out, k, bus = turn(LONG_ANSWER, zone="reference")
    assert out == LONG_ANSWER, "the bubble lost text on a plain lane"
    assert bus.renders == [], "a card appeared without a show payload"
    assert k._last_render_emitted is False


def test_bt2_show_artifact_renders_a_card_plus_supportive_line(turn):
    out, k, bus = turn(SHOW_PAYLOAD)
    assert len(bus.renders) == 1, "the artifact did not render"
    assert bus.renders[0]["content"].startswith("# Report")
    assert out == "I wrote the report — it's on the card.", (
        "the bubble must carry the supportive speak line, not the body"
    )


def test_bt3_tts_gets_the_speak_line_on_every_lane_that_has_one(turn):
    # Card lane: speak -> _last_spoken_text.
    _, k_card, _ = turn(SHOW_PAYLOAD)
    assert k_card._last_spoken_text == "I wrote the report — it's on the card."
    # Plain lane: no speak exists; the spoken lane stays EMPTY so the
    # gateway's prepare_spoken_text fallback (iris_gateway.py:5897-5899)
    # derives TTS from the bubble — lanes stay independent (REQ-8).
    _, k_plain, _ = turn(LONG_ANSWER)
    assert k_plain._last_spoken_text == ""
    # Speak-tool envelope lane: spoken -> both display and TTS.
    envelope = json.dumps({"status": "ok", "spoken": "Done — reports saved."})
    out3, k_env, _ = turn(envelope)
    assert out3 == "Done — reports saved."
    assert k_env._last_spoken_text == "Done — reports saved."


def test_bt5_web_synthesis_without_show_still_renders_no_card(turn):
    """The pre-spec length/zone auto-render is gone: a substantial plain
    synthesis after web capture is plain text, the answer in full (the format
    question that used to follow it is deleted too)."""
    synthesis = (
        "## Findings\n\nThe crawl found three relevant pages. "
        "(Based on captured web evidence.) " * 6
    )
    out, k, bus = turn(synthesis, zone="reference")
    assert out == synthesis
    assert bus.renders == [], "web synthesis without show must not fabricate"
    assert k._last_render_emitted is False


def test_bt9_reply_completes_with_the_decision_engine_stopped(
    turn, monkeypatch
):
    """Engine unavailable/mid-restart: the reply lane is unaffected."""

    def _explode():
        raise RuntimeError("decision engine stopped")

    monkeypatch.setattr(
        "backend.agent.decision_engine.get_decision_engine", _explode
    )
    out, k, bus = turn(LONG_ANSWER, zone="reference")
    assert out == LONG_ANSWER
    assert bus.renders == []
    out2, k2, bus2 = turn(SHOW_PAYLOAD)
    assert len(bus2.renders) == 1, "card turns must also survive engine loss"


def test_bt10_same_reply_twice_same_surface(turn):
    for response in (LONG_ANSWER, SHOW_PAYLOAD):
        first = turn(response, zone="reference")
        second = turn(response, zone="reference")
        assert first[0] == second[0], "bubble drifted between runs"
        assert [len(t[2].renders) for t in (first, second)] == [
            len(first[2].renders)
        ] * 2, "card count drifted between runs"
