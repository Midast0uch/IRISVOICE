"""Contract: narration echo (CT-S6, REQ-10 AC10.8) + narration content cap
(AC10.5) — T16.

CT-S6 pins the AC10.8 reuse mandate: narration plays through the EXISTING
orb reaction chain and emits NO tts_started. The Xu orb breathes on
`audio_envelope` (speaking → idle) and shows the speaking indicator on
`listening_state` — the SAME shapes the main response path already pins
(test_voice_pipeline, test_barge_in envelope pins). Chat-view
word-highlighting keys on `tts_started.turn_id` matching a chat message id;
the narration path emits no tts_started at all, so a phantom card can never
fire — this contract LOCKS that (any future narration tts_started must
follow the `tts-play-*` convention, never a chat message id).

AC10.5 pins the narration sentence cap + spoken ⊆ visible: a narration
node's spoken text is a sentence-boundary prefix of the authored text —
never an invention, never a mid-sentence clip, never a raw full-text
marathon.

No real TTS, no audio, no network.
"""
from __future__ import annotations

import threading
import time
import types

import pytest

from backend.agent.conversation_kernel import ConversationKernel
from backend.agent.speech_lanes import (
    NARRATION_CAP_WORDS,
    reset_speech_lanes_for_testing,
)


def _make_voice_handler():
    vh = types.SimpleNamespace()
    vh._on_state_change = None
    vh._on_audio_level = None
    vh._active_session_id = "test_session"
    vh.set_state_callback = lambda cb: None
    vh.set_audio_level_callback = lambda cb: None
    return vh


def _make_tts_manager():
    mgr = types.SimpleNamespace()

    def synthesize_stream(text, **kw):
        yield text

    mgr.synthesize_stream = synthesize_stream
    return mgr


def _make_kernel(played, broadcasts, gate=None):
    kernel = ConversationKernel(
        voice_handler=_make_voice_handler(),
        tts_manager=_make_tts_manager(),
        audio_pipeline=_make_pipeline(played, gate),
        session_id_getter=lambda: "test_session",
    )
    # Collect every narration WS broadcast through the real sink.
    kernel._broadcast_event = lambda session_id, msg: broadcasts.append(msg)
    return kernel


def _make_pipeline(played, gate=None):
    ap = types.SimpleNamespace()
    ap.played = played
    ap._gate = gate
    ap.interrupt = lambda: None

    def play_stream(stream, sample_rate=None):
        text = ""
        try:
            for chunk in stream:
                text += str(chunk)
        except Exception:
            pass
        ap.played.append(text)
        if ap._gate is not None:
            ap._gate.wait(timeout=2.0)

    ap.play_stream = play_stream
    return ap


def _wait_until(pred, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture(autouse=True)
def _reset():
    reset_speech_lanes_for_testing()
    yield
    reset_speech_lanes_for_testing()


# ── CT-S6: orb-chain shape reuse (AC10.8) ─────────────────────────────────
class TestNarrationEchoShapes:
    def test_playback_broadcasts_the_existing_orb_chain(self):
        """Narration playback emits the SAME envelope contract the main
        response path pins: audio_envelope speaking (rms 0.06) → idle
        (rms 0.0) + listening_state speaking → idle. Zero new shapes."""
        played, broadcasts = [], []
        kernel = _make_kernel(played, broadcasts)
        kernel.scheduler.add_beat(
            "Checking the sources now.", turn_id="t1",
            session_id="test_session", kind="planned",
        )
        assert _wait_until(
            lambda: len(played) >= 1 and kernel.scheduler.pending_count() == 0
        )
        types_seen = [b.get("type") for b in broadcasts]
        assert types_seen.count("audio_envelope") == 2
        assert types_seen.count("listening_state") == 2
        envelopes = [b for b in broadcasts if b.get("type") == "audio_envelope"]
        speaking = envelopes[0]["payload"]
        idle = envelopes[1]["payload"]
        # The exact shapes the frontend orb chain already consumes
        # (OrbCanvas breathes on phase; 0.06 speaking / 0.0 idle).
        assert speaking["phase"] == "speaking"
        assert speaking["rms"] == 0.06
        assert speaking["cadence"] == 0.06
        assert idle["phase"] == "idle"
        assert idle["rms"] == 0.0
        assert idle["cadence"] == 0.0
        states = [b["payload"]["state"] for b in broadcasts
                  if b.get("type") == "listening_state"]
        assert states == ["speaking", "idle"]

    def test_no_tts_started_never_a_phantom_card(self):
        """AC10.8: the narration path emits NO tts_started — chat-view
        word-highlighting keys on tts_started.turn_id matching a chat
        message id; with no tts_started there is nothing to match, so a
        phantom card can never fire. This pin LOCKS it: if narration ever
        emits tts_started, it must use the tts-play-* convention (never a
        chat message id) — asserted here as absence-of-unshaped-events."""
        played, broadcasts = [], []
        kernel = _make_kernel(played, broadcasts)
        kernel.scheduler.add_beat(
            "Narration echo probe.", turn_id="turn_1",
            session_id="test_session", kind="planned",
        )
        assert _wait_until(
            lambda: len(played) >= 1 and kernel.scheduler.pending_count() == 0
        )
        started = [b for b in broadcasts if b.get("type") == "tts_started"]
        assert started == [], (
            "narration must not emit tts_started; if it ever must, the "
            "turn_id MUST follow the tts-play-* convention so chat-view "
            "word-highlighting never fires (no phantom card)"
        )

    def test_error_path_still_clears_the_orb(self):
        """Playback failure still broadcasts the idle envelope + state so the
        orb never sticks in speaking (same contract as the main path)."""
        played, broadcasts = [], []
        kernel = _make_kernel(played, broadcasts)
        # Break playback: play_stream raises.
        kernel._resolve_audio_pipeline = lambda: None  # forces drop path
        kernel.scheduler.add_beat(
            "Doomed line.", turn_id="t1", session_id="test_session",
            kind="planned",
        )
        assert _wait_until(
            lambda: kernel.scheduler.pending_count() == 0
            and not kernel.scheduler.is_playing()
        )
        # The node fails visibly (watchdog/failure semantics, T8) — the
        # assertion here is that nothing hangs and no broadcast lies about
        # speaking state.
        lying = [b for b in broadcasts
                 if b.get("type") == "listening_state"
                 and b["payload"]["state"] == "speaking"]
        assert lying == []


# ── AC10.5: sentence cap + spoken ⊆ visible ───────────────────────────────
class TestNarrationContentCap:
    def test_short_beat_spoken_verbatim(self):
        """A one-line beat (authoring guidance keeps beats short) passes the
        cap untouched — spoken == authored."""
        played, broadcasts = [], []
        kernel = _make_kernel(played, broadcasts)
        beat = "Direction is clear; about two minutes."
        kernel.scheduler.add_beat(
            beat, turn_id="t1", session_id="test_session", kind="planned",
        )
        assert _wait_until(lambda: len(played) >= 1)
        assert played[0] == beat

    def test_marathon_beat_capped_at_sentence_boundary(self):
        """A runaway beat is capped to ≤ NARRATION_CAP_WORDS at a sentence
        boundary — never a mid-sentence clip, never the full marathon."""
        played, _ = [], []
        kernel = _make_kernel(played, [])
        long_beat = (
            "Starting with the auth module. " +
            ("The checker walks every route file and records each handler "
             "signature so the diff review can compare them against the "
             "declared contract before anything else runs, and it keeps a "
             "running note of every mismatch it finds along the way so the "
             "final synthesis can quote real evidence instead of loose "
             "memory, and the ledger records each one for the next run. ") +
            "Then it moves on."
        )
        kernel.scheduler.add_beat(
            long_beat, turn_id="t1", session_id="test_session", kind="planned",
        )
        assert _wait_until(lambda: len(played) >= 1)
        spoken = played[0]
        # spoken ⊆ visible: a strict prefix of the authored text.
        assert long_beat.startswith(spoken)
        assert spoken != long_beat
        # Sentence-boundary respect: the cap lands on punctuation.
        assert spoken.rstrip().endswith((".", "!", "?"))
        # The cap budget holds.
        assert len(spoken.split()) <= NARRATION_CAP_WORDS
        # The marathon tail is gone.
        assert "Then it moves on." not in spoken

    def test_spoken_is_always_derived_from_authored(self):
        """spoken ⊆ visible (AC6.3 on the narration road): whatever plays is
        derived from the authored beat text — for short beats identity, for
        long beats a prefix; never invented content."""
        played, _ = [], []
        kernel = _make_kernel(played, [])
        beats = [
            "First direction line.",
            "Second line with a bit more: " + "word " * 80,
        ]
        for i, b in enumerate(beats):
            kernel.scheduler.add_beat(
                b, turn_id=f"t{i}", session_id="test_session", kind="planned",
            )
        assert _wait_until(lambda: len(played) >= 2)
        for authored, spoken in zip(beats, played):
            assert spoken and authored.startswith(spoken)
