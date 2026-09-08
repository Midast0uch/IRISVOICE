"""Behavioral: filler gap-filler exception (REQ-10 AC10.13, T16 — BT-S9).

Drives the REAL ConversationKernel utterance path and the REAL
SpeechScheduler with a fake pipeline. The canned fillers survive only as an
exception path:

  * silence gate: a filler fires only when speech would otherwise be silent —
    nothing playing AND nothing pending (a pending beat means the first beat
    is ready, so no filler is needed).
  * no-consecutive-repeat: the filler picker never picks the same phrase
    twice in a row.
  * subsumption-on-beat-arrival: a real beat arriving cancels QUEUED fillers
    unspoken; the PLAYING filler finishes its sentence (AC4.4) and the beat
    plays after it.
  * no merge into filler: a reactive finding never folds into a queued
    filler ("One moment.; <finding>" must never exist); the filler is
    cancelled and the reactive line plays as its own line.

No real TTS, no audio, no network — the play path is a fake that records.
"""
from __future__ import annotations

import threading
import time
import types

import pytest

from backend.agent.conversation_kernel import ConversationKernel
from backend.agent.speech_lanes import (
    FILLER_PHRASES,
    NARRATION,
    filler_allowed,
    pick_filler,
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


def _make_tts():
    return types.SimpleNamespace()


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


def _make_tts_manager():
    mgr = types.SimpleNamespace()

    def synthesize_stream(text, **kw):
        yield text

    mgr.synthesize_stream = synthesize_stream
    return mgr


def _make_kernel(played, gate=None):
    kernel = ConversationKernel(
        voice_handler=_make_voice_handler(),
        tts_manager=_make_tts_manager(),
        audio_pipeline=_make_pipeline(played, gate),
        session_id_getter=lambda: "test_session",
    )
    return kernel


def _emit_filler_utterance(kernel, text, turn_id="t1"):
    """Emit a filler the way SpeakTool does: UTTERANCE_START through the real
    kernel handler — the node lands as NARRATION, source="speak_tool"."""
    payload = types.SimpleNamespace(
        data={"text": text, "turn_id": turn_id, "interrupt": False}
    )
    kernel._on_utterance_start(payload)


def _wait_until(pred, timeout=2.0):
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


# ── AC10.13 clause 1: fires only in the silent gap ────────────────────────
class TestSilenceGate:
    def test_idle_scheduler_allows_filler(self):
        """Silent lanes (nothing playing, nothing pending) → filler allowed."""
        kernel = _make_kernel(played=[])
        assert filler_allowed(kernel.scheduler) is True

    def test_playing_speech_blocks_filler(self):
        """Speech would NOT otherwise be silent while a node plays → skip."""
        gate = threading.Event()
        played = []
        kernel = _make_kernel(played, gate)
        _emit_filler_utterance(kernel, "Earlier line.", turn_id="t1")
        assert _wait_until(kernel.scheduler.is_playing)
        assert filler_allowed(kernel.scheduler) is False
        gate.set()

    def test_pending_beat_blocks_filler(self):
        """A pending (unspoken) narration beat means the first beat is ready
        — the gap the filler exists to cover is gone → skip."""
        played = []
        kernel = _make_kernel(played)
        # A queued (not playing) filler keeps the lane non-silent.
        _emit_filler_utterance(kernel, "Queued line.", turn_id="t1")
        deadline = time.time() + 2.0
        while time.time() < deadline and kernel.scheduler.pending_count() == 0:
            time.sleep(0.01)
        if kernel.scheduler.is_playing():
            # It started playing already — still not silent.
            pass
        assert filler_allowed(kernel.scheduler) is False

    def test_no_scheduler_legacy_path_decides(self):
        """No lane engine (scheduler=None) → legacy path decides (True)."""
        assert filler_allowed(None) is True


# ── AC10.13 clause 2: never the same phrase twice consecutively ───────────
class TestNoConsecutiveRepeat:
    def test_picker_never_repeats_consecutively(self):
        picks = [pick_filler() for _ in range(200)]
        assert all(p in FILLER_PHRASES for p in picks)
        for prev, cur in zip(picks, picks[1:]):
            assert prev != cur, f"consecutive repeat: {prev!r}"

    def test_picker_stays_inside_the_table(self):
        picks = {pick_filler() for _ in range(50)}
        assert picks <= set(FILLER_PHRASES)
        assert len(picks) >= 2  # rotation actually happens


# ── AC10.13 clause 3: subsumed on beat arrival ────────────────────────────
class TestSubsumptionOnBeatArrival:
    def test_playing_filler_finishes_then_beat_plays(self):
        """A real beat arriving while the filler PLAYS does not cut it —
        the filler finishes its sentence (AC4.4) and the beat plays after."""
        gate = threading.Event()
        played = []
        kernel = _make_kernel(played, gate)
        _emit_filler_utterance(kernel, "One moment.", turn_id="t1")
        assert _wait_until(kernel.scheduler.is_playing)
        beat_id = kernel.scheduler.add_beat(
            "Checking the auth module now.", turn_id="t1", session_id="test_session",
            kind="planned",
        )
        gate.set()
        assert _wait_until(
            lambda: len(played) >= 2 and kernel.scheduler.pending_count() == 0,
            timeout=3.0,
        )
        assert played[0] == "One moment."  # filler finished its sentence
        assert played[1] == "Checking the auth module now."
        assert beat_id

    def test_queued_filler_dies_when_beat_arrives(self):
        """A QUEUED filler (behind a playing node) is cancelled unspoken the
        moment a real beat arrives — the gap it covered no longer exists."""
        gate = threading.Event()
        played = []
        kernel = _make_kernel(played, gate)
        _emit_filler_utterance(kernel, "First filler.", turn_id="t1")
        assert _wait_until(kernel.scheduler.is_playing)
        # This one queues behind the playing node.
        _emit_filler_utterance(kernel, "Second filler.", turn_id="t1")
        assert _wait_until(lambda: kernel.scheduler.pending_count() >= 1)
        kernel.scheduler.add_beat(
            "Found the bug.", turn_id="t1", session_id="test_session",
            kind="reactive",
        )
        gate.set()
        assert _wait_until(
            lambda: len(played) >= 2 and kernel.scheduler.pending_count() == 0,
            timeout=3.0,
        )
        assert "First filler." in played  # playing filler finished
        assert "Second filler." not in played  # queued filler subsumed
        assert "Found the bug." in played  # the real beat still speaks

    def test_reactive_never_merges_into_a_filler(self):
        """A reactive finding must not fold into a queued filler — the line
        "One moment.; <finding>" must never exist. The filler is cancelled
        and the reactive line plays as its own line."""
        gate = threading.Event()
        played = []
        kernel = _make_kernel(played, gate)
        _emit_filler_utterance(kernel, "One moment.", turn_id="t1")
        assert _wait_until(kernel.scheduler.is_playing)
        _emit_filler_utterance(kernel, "Just a second.", turn_id="t1")
        assert _wait_until(lambda: kernel.scheduler.pending_count() >= 1)
        kernel.scheduler.admit_reactive(
            "Tests are green.", turn_id="t1", session_id="test_session",
        )
        gate.set()
        assert _wait_until(
            lambda: len(played) >= 2 and kernel.scheduler.pending_count() == 0,
            timeout=3.0,
        )
        joined = " | ".join(played)
        assert "One moment." in played  # playing filler finished
        assert "Just a second." not in played  # queued filler subsumed
        assert "Tests are green." in played
        assert ";" not in joined  # no merged "filler; finding" line

    def test_second_filler_is_not_subsumed_by_filler(self):
        """Only REAL beats subsume fillers — a filler arriving behind another
        filler still plays (the silence-gate caller prevents this upstream;
        the scheduler itself does not invent a filler-vs-filler rule)."""
        gate = threading.Event()
        played = []
        kernel = _make_kernel(played, gate)
        _emit_filler_utterance(kernel, "First filler.", turn_id="t1")
        assert _wait_until(kernel.scheduler.is_playing)
        _emit_filler_utterance(kernel, "Second filler.", turn_id="t1")
        gate.set()
        assert _wait_until(
            lambda: len(played) >= 2 and kernel.scheduler.pending_count() == 0,
            timeout=3.0,
        )
        assert "First filler." in played
        assert "Second filler." in played
