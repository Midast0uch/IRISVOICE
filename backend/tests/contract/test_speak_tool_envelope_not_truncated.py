"""Contract: a tool-result envelope and a long plain answer keep their full text.

Two truncation paths in ``_process_structured_response``, both observed live
2026-08-16 and fixed 2026-08-17:

1. The DER path can return a TOOL RESULT as its final output. The speak tool
   returns ``{"status": "ok", "utterance_id": ..., "spoken": text}`` — JSON with
   neither ``speak`` nor ``show``, so it was treated as plain text and
   ``_supportive_text`` excerpted the RAW JSON: ``der_response_len=887``
   persisted as 55 chars. A handler for the ``spoken`` field existed but sat
   after the ``show is None`` return and could never run.

2. ``_supportive_text`` ran on EVERY plain-text response, not only when a card
   carried the full document. Any plain answer over ~200 chars was cut to its
   first sentence with nothing else holding the rest.

User rule (2026-08-16): TTS supports long text. The text content must NEVER be
truncated, and a document render must not be REQUIRED.
"""

from __future__ import annotations

import json

from backend.agent import agent_kernel as _ak


LONG = (
    "Your system reports 32 GB of RAM and Windows 10 Pro build 19045. "
    "The dev script runs next dev on port 3000, and the backend listens on 8000. "
    "Porcupine wake-word detection is active with two keywords loaded. "
    "The audio pipeline streams over WebSocket at 16 kHz mono. "
    "Credentials are stored in the OS keyring, never on disk. "
    "The coordinate graph currently holds 47 landmarks and 459 pins. "
)


def _kernel(zone="chat"):
    k = _ak.AgentKernel.__new__(_ak.AgentKernel)
    k._last_render_emitted = False
    k._last_spoken_text = ""
    k._pacman_zone_for_turn = lambda: zone
    return k


def _run(k, response):
    return _ak.AgentKernel._process_structured_response(
        k, response, turn_id="t1", conversation_id="c1"
    )


class TestSpeakToolEnvelope:
    def test_the_whole_spoken_answer_is_displayed_not_an_excerpt(self):
        """887 chars in must not come out as 55 chars of mangled JSON."""
        envelope = json.dumps(
            {"status": "ok", "utterance_id": "spk_ab12cd34", "spoken": LONG}
        )
        assert len(envelope) > 400, "fixture must exceed the old excerpt cap"
        k = _kernel()
        out = _run(k, envelope)
        assert out == LONG, f"envelope answer truncated to {len(out)} chars"
        assert "utterance_id" not in out, "raw JSON leaked into the thread"

    def test_a_written_answer_beats_the_spoken_line_for_display(self):
        """When the envelope carries both, the thread gets the written answer
        and TTS keeps the short spoken line."""
        k = _kernel()
        out = _run(
            k,
            json.dumps({"status": "ok", "spoken": "Here's the summary.",
                        "text": LONG}),
        )
        assert out == LONG
        assert k._last_spoken_text == "Here's the summary."

    def test_the_spoken_line_reaches_tts(self):
        k = _kernel()
        _run(k, json.dumps({"status": "ok", "spoken": LONG}))
        assert k._last_spoken_text == LONG.strip()

    def test_a_stale_spoken_line_never_survives_an_envelope_turn(self):
        k = _kernel()
        k._last_spoken_text = "left over from the last answer"
        _run(k, json.dumps({"status": "cooldown"}))
        assert k._last_spoken_text == ""

    def test_a_non_envelope_json_object_is_untouched(self):
        """No `spoken` key -> not a tool envelope -> plain-text path."""
        k = _kernel()
        payload = json.dumps({"status": "ok", "rows": [1, 2, 3]})
        assert _run(k, payload) == payload


class TestPlainTextIsOnlyExcerptedWhenACardHoldsTheRest:
    def test_a_long_plain_answer_with_no_card_is_returned_in_full(self):
        k = _kernel(zone="chat")
        out = _run(k, LONG)
        assert k._last_render_emitted is False
        assert out == LONG, f"plain answer truncated to {len(out)} chars"

    def test_an_auto_rendered_answer_is_excerpted_because_the_card_has_it_all(
        self, monkeypatch
    ):
        """The reference-zone auto-render puts the full markdown on the card,
        so the bubble carries a complementary excerpt — not a duplicate."""
        emitted = {}

        class _Bus:
            def emit(self, event, data=None, **kw):
                emitted["data"] = data

        monkeypatch.setattr(
            "backend.agent.event_bus.get_event_bus", lambda: _Bus()
        )
        k = _kernel(zone="reference")
        k._store_document_data = lambda **kw: None
        out = _run(k, LONG)
        assert k._last_render_emitted is True, "reference turn rendered no card"
        assert emitted["data"]["content"] == LONG, "the card lost the full text"
        assert 0 < len(out) < len(LONG), "excerpt should complement the card"
        assert LONG.startswith(out.rstrip("…").strip()[:40])
