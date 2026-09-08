"""Behavioral: T4 narration path migrates through the lane scheduler.

Drives the REAL ConversationKernel narration path (EventBus utterance events
-> _on_utterance_start -> lane scheduler -> _play_lane_node -> _speak_utterance)
with mocked TTS/pipeline. Asserts the emergent lane properties:

  * BT-S2 subsumption: a REPLY admitted while NARRATION is pending cancels the
    pending narration unspoken (REQ-4 AC4.2).
  * BT-S3 turn boundary: NARRATION dies at turn end; REPLY survives (REQ-5
    AC5.1/AC5.2).

No real TTS, no audio, no network — the play path is a fake that records.
"""
from __future__ import annotations

import threading
import time
import types

import pytest

from backend.agent.conversation_kernel import ConversationKernel
from backend.agent.speech_lanes import (
    NARRATION,
    REPLY,
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
    tts = types.SimpleNamespace()
    tts.stop_calls = []
    tts.stop = lambda: tts.stop_calls.append(True)
    return tts


def _make_pipeline(played):
    """Fake pipeline: records played text; blocks on a gate when told."""
    ap = types.SimpleNamespace()
    ap.played = played
    ap._gate = None
    ap.interrupt = lambda: None

    def play_stream(stream, sample_rate=None):
        # stream is a generator from synthesize_stream; drain it to get text.
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


def _make_tts_manager(tts):
    """TTSManager mock whose synthesize_stream yields the text once."""
    mgr = types.SimpleNamespace()
    mgr._tts = tts

    def synthesize_stream(text, **kw):
        yield text

    mgr.synthesize_stream = synthesize_stream
    return mgr


def _make_kernel(played, gate=None):
    vh = _make_voice_handler()
    tts = _make_tts()
    ap = _make_pipeline(played)
    ap._gate = gate
    kernel = ConversationKernel(
        voice_handler=vh,
        tts_manager=_make_tts_manager(tts),
        audio_pipeline=ap,
        session_id_getter=lambda: "test_session",
    )
    return kernel, ap


def _emit_utterance(kernel, text, turn_id="t1", interrupt=False):
    """Emit an utterance:start event through the kernel's handler."""
    payload = types.SimpleNamespace(
        data={"text": text, "turn_id": turn_id, "interrupt": interrupt}
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


# ── BT-S2: subsumption ────────────────────────────────────────────────────
class TestSubsumption:
    def test_reply_cancels_pending_narration(self):
        played = []
        gate = threading.Event()
        kernel, ap = _make_kernel(played, gate=gate)
        # First narration starts playing (held on the gate).
        _emit_utterance(kernel, "first narration", turn_id="t1")
        assert _wait_until(lambda: len(played) >= 1)
        # Second narration queued behind it.
        _emit_utterance(kernel, "second narration", turn_id="t1")
        # A reply is admitted -> pending narration subsumed.
        kernel._scheduler.admit(_reply_node(kernel, "the reply", "t1"))
        gate.set()
        assert _wait_until(lambda: len(played) >= 2)
        # Only the first narration and the reply played; the second narration
        # was subsumed (never spoken).
        assert "second narration" not in played
        assert "the reply" in played
        kernel._scheduler.stop()


# ── BT-S3: turn boundary ──────────────────────────────────────────────────
class TestTurnBoundary:
    def test_narration_dies_reply_survives(self):
        played = []
        kernel, ap = _make_kernel(played)
        _emit_utterance(kernel, "narration", turn_id="t1")
        kernel._scheduler.admit(_reply_node(kernel, "reply", "t1"))
        # Turn t1 ends: narration cancelled, reply survives.
        kernel._scheduler.cancel_turn("t1")
        assert _wait_until(lambda: len(played) >= 1)
        assert "reply" in played
        assert "narration" not in played
        kernel._scheduler.stop()


# ── T6 (REQ-4 AC4.2): reply subsumes pending narration ────────────────────
class TestReplySubsumption:
    def test_reply_subsume_narration_cancels_pending(self):
        played = []
        gate = threading.Event()
        kernel, ap = _make_kernel(played, gate=gate)
        # First narration starts playing (held on the gate).
        _emit_utterance(kernel, "first narration", turn_id="t1")
        assert _wait_until(lambda: len(played) >= 1)
        # Second narration queued behind it.
        _emit_utterance(kernel, "second narration", turn_id="t1")
        # A reply is admitted via the T6 path (subsume_narration) -> pending
        # narration cancelled unspoken.
        kernel.subsume_narration(turn_id="t1", session_id="test_session")
        gate.set()
        assert _wait_until(lambda: not kernel._scheduler.is_playing())
        # Only the first narration played; the second was subsumed.
        assert "second narration" not in played
        kernel._scheduler.stop()

    def test_subsume_narration_keeps_running_until_sentence_end(self):
        played = []
        gate = threading.Event()
        kernel, ap = _make_kernel(played, gate=gate)
        _emit_utterance(kernel, "running narration", turn_id="t1")
        assert _wait_until(lambda: len(played) >= 1)
        # Subsume while the first is still playing: it finishes (gate held),
        # only queued narration dies.
        kernel.subsume_narration(turn_id="t1", session_id="test_session")
        gate.set()
        assert _wait_until(lambda: not kernel._scheduler.is_playing())
        assert "running narration" in played  # finished its sentence
        kernel._scheduler.stop()


def _reply_node(kernel, text, turn_id):
    from backend.agent.speech_lanes import Situation, build_node, route

    situation = Situation(trigger_label=REPLY, source="test", content_shape="conversation")
    return build_node(
        situation,
        route(situation),
        turn_id=turn_id,
        session_id="test_session",
        content={"kind": "text", "text": text},
    )