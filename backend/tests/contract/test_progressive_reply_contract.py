"""Contract (specs/reply-surface-contract REQ-13, task T19 — CT-11).

The progressive-reply contract on the REAL kernel:

1. The agent's `speak` line is the FIRST streamed chunk; the `show` body is
   never in the text stream (it renders via DOCUMENT_RENDER).
2. The DOCUMENT_RENDER payload carries a `partial` discriminator and a stable
   `document_id` (the partial channel the frontend updates in place).
3. Every streamed text delta is a `text` part of its turn, and the part
   envelope carries `turn_id` (REQ-13 AC6; the retired chat_chunk frame
   carried it by hand — the turn protocol files it by construction).
4. Time-to-card is recorded on the turn's TurnMetrics (`card_ms`).
"""

from __future__ import annotations

import json

import backend.agent.agent_kernel as _ak_mod
from backend.agent.agent_kernel import AgentKernel
from backend.utils.observability import TurnMetrics


class _Bus:
    def __init__(self):
        self.events = []

    def emit(self, event, data=None, **kw):
        self.events.append((event, data))


def _kernel(monkeypatch):
    k = AgentKernel.__new__(AgentKernel)
    k._last_render_emitted = False
    k._last_spoken_text = ""
    monkeypatch.setattr(k, "_pacman_zone_for_turn", lambda: "chat",
                        raising=False)
    monkeypatch.setattr(k, "_store_document_data", lambda **kw: None,
                        raising=False)
    bus = _Bus()
    monkeypatch.setattr("backend.agent.event_bus.get_event_bus", lambda: bus)
    return k, bus


class TestSpeakStreamsFirst:
    def test_speak_is_the_first_chunk_and_the_body_never_streams_as_text(
        self, monkeypatch
    ):
        k, bus = _kernel(monkeypatch)
        body = "# Doc\n\n" + ("document body text. " * 40)
        payload = json.dumps({
            "speak": "Here is the document — on the card.",
            "show": {"format": "markdown", "content": body},
        })
        chunks = []
        k._emit_reply_progressively(
            payload, "t-prog", chunk_callback=chunks.append
        )
        assert chunks and chunks[0] == "Here is the document — on the card."
        assert chunks[-1] == "", "the force-flush sentinel must be last"
        assert all("document body text." not in c for c in chunks), (
            "the show body leaked into the text stream"
        )
        assert '"show"' not in "".join(chunks), (
            "the structured JSON envelope leaked into the text stream"
        )

    def test_plain_text_streams_as_one_full_chunk(self, monkeypatch):
        k, bus = _kernel(monkeypatch)
        text = "A perfectly plain reply, streamed in one go."
        chunks = []
        k._emit_reply_progressively(text, "t-plain", chunks.append)
        assert chunks == [text, ""]

    def test_show_without_speak_streams_no_duplicate_text(self, monkeypatch):
        k, bus = _kernel(monkeypatch)
        payload = json.dumps({"show": {"format": "markdown", "content": "body"}})
        chunks = []
        k._emit_reply_progressively(payload, "t-nospeak", chunks.append)
        assert chunks == [""], "only the flush sentinel — the card carries all"

    def test_a_chunk_failure_never_kills_the_turn(self, monkeypatch):
        k, bus = _kernel(monkeypatch)

        def _boom(_chunk):
            raise RuntimeError("stream transport down")

        k._emit_reply_progressively("hello", "t-boom", chunk_callback=_boom)


class TestCardRenderPayloadSemantics:
    def test_document_render_carries_stable_id_and_partial_flag(
        self, monkeypatch
    ):
        """REQ-13 AC5: the seam's emit is the FINAL (non-partial) emit, and it
        carries the stable document_id the partial channel will key on."""
        k, bus = _kernel(monkeypatch)
        k._active_turn_metrics = TurnMetrics(turn_id="t-card-ms")
        out = AgentKernel._process_structured_response(
            k,
            json.dumps({
                "speak": "s",
                "show": {"format": "markdown", "content": "# Doc\n\nbody"},
            }),
            turn_id="t-card-ms",
            conversation_id="c",
        )
        assert out == "s"
        renders = [d for _e, d in bus.events if d and "document_id" in d]
        assert len(renders) == 1
        assert renders[0]["document_id"], "stable document_id required"
        assert renders[0]["partial"] is False, "this path is the final emit"
        assert k._active_turn_metrics.card_ms is not None, (
            "time-to-card not recorded (REQ-13 AC4)"
        )

    def test_turn_metrics_log_line_carries_card_ms(self):
        m = TurnMetrics(turn_id="t")
        m.mark_card()
        assert m.card_ms is not None
        assert "card_ms=" in m.to_log_line()


class TestStreamedTextPartCarriesTurnId:
    def test_every_streamed_text_part_carries_turn_id(self):
        """REQ-13 AC6: the frontend attaches a streamed delta to its turn, so
        EVERY streamed text delta — text path and voice path — must carry the
        turn's id. The retired chat_chunk frame carried turn_id by hand; a
        turn part carries it by construction (the emitter files the part under
        its turn). Both gateway chunk callbacks route their deltas through
        _turn.text (guarded in test_turn_outcome_persists_contract)."""
        from backend.agent.turn_protocol import TurnEmitter

        wire = []
        em = TurnEmitter(wire.append, turn_id="t-stream", conversation_id="conv-s")
        em.start()
        em.text("Hel")
        em.text("lo")
        em.end("ok", text="Hello", speak="Hello")
        parts = [m for m in wire if m["type"] == "turn.part"]
        assert [m["payload"]["part"]["type"] for m in parts] == ["text", "text"]
        for m in parts:
            assert m["payload"]["turn_id"] == "t-stream", (
                "a streamed text part without turn_id would be dropped by the "
                "frontend"
            )
