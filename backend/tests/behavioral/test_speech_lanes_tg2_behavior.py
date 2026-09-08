"""Behavioral: TG-2 gate — barge kill+fresh, ephemeral narration, lock absence.

Drives the REAL ConversationKernel lane path (EventBus utterance events ->
_on_utterance_start -> lane scheduler -> _play_lane_node -> _speak_utterance)
with mocked TTS/pipeline and asserts the emergent lane properties that TG-2
must prove behaviorally (REQ-4/REQ-5/REQ-6/REQ-7):

  * BT-S1 barge kill+fresh: barge-in cancels running + all pending, the new
    turn starts clean (REQ-4 AC4.1, REQ-5 AC5.4).
  * BT-S4 ephemeral narration: narration nodes are never persisted (design.md
    D7) — persist=False; replies/alerts persist=True.
  * REQ-7 AC7.1 lock absence: the narration lock is gone; serialization is the
    scheduler's single worker.

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


# ── BT-S1: barge kill + fresh turn (REQ-4 AC4.1, REQ-5 AC5.4) ──────────────
class TestBargeKillFresh:
    def test_barge_in_kills_running_and_pending_fresh_turn(self):
        played = []
        gate = threading.Event()
        kernel, ap = _make_kernel(played, gate=gate)
        # First narration starts playing (held on the gate).
        _emit_utterance(kernel, "running narration", turn_id="t1")
        assert _wait_until(lambda: len(played) >= 1)
        # Pending narration queued behind it.
        _emit_utterance(kernel, "pending narration", turn_id="t1")
        # Barge-in: kill running + all pending, fresh turn.
        kernel._scheduler.barge_in(turn_id="t2", session_id="test_session")
        gate.set()
        assert _wait_until(lambda: not kernel._scheduler.is_playing())
        # Only the running narration played; pending was killed unspoken.
        assert "pending narration" not in played
        assert kernel._scheduler.pending_count() == 0
        # Fresh turn: a new narration is admitted and plays cleanly.
        _emit_utterance(kernel, "fresh turn narration", turn_id="t2")
        assert _wait_until(lambda: "fresh turn narration" in played)
        kernel._scheduler.stop()

    def test_barge_in_reopens_gate_immediately(self):
        """Barge-in reopens the half-duplex mic gate synchronously (REQ-7
        AC7.2) so the new turn's recording starts capturing immediately."""
        calls = []
        vh = _make_voice_handler()
        tts = _make_tts()
        ap = _make_pipeline([])
        gate = threading.Event()
        ap._gate = gate
        kernel = ConversationKernel(
            voice_handler=vh,
            tts_manager=_make_tts_manager(tts),
            audio_pipeline=ap,
            session_id_getter=lambda: "test_session",
        )
        # Wire a gate spy onto the kernel's scheduler.
        kernel._scheduler._gate = lambda a: calls.append(a)
        _emit_utterance(kernel, "running", turn_id="t1")
        assert _wait_until(lambda: kernel._scheduler.is_playing())
        kernel._scheduler.barge_in(turn_id="t2", session_id="test_session")
        assert calls[-1] is False  # gate reopened immediately on barge-in
        gate.set()
        kernel._scheduler.stop()


# ── BT-S4: ephemeral narration absent from history (design.md D7) ─────────
class TestEphemeralNarration:
    def test_narration_never_persisted_reply_persists(self):
        """Narration nodes are ephemeral (persist=False); replies/alerts
        persist (persist=True). The lane engine never writes narration to
        history."""
        from backend.agent.speech_lanes import Situation, build_node, route

        kernel, ap = _make_kernel([])
        # Narration: ephemeral.
        n_sit = Situation(
            trigger_label=NARRATION, source="test", content_shape="conversation"
        )
        n_node = build_node(
            n_sit, route(n_sit), turn_id="t1", session_id="s1",
            content={"kind": "text", "text": "ephemeral"},
        )
        assert n_node.persist is False
        # Reply: persisted.
        r_sit = Situation(
            trigger_label=REPLY, source="test", content_shape="conversation"
        )
        r_node = build_node(
            r_sit, route(r_sit), turn_id="t1", session_id="s1",
            content={"kind": "text", "text": "reply"},
        )
        assert r_node.persist is True
        kernel._scheduler.stop()


# ── REQ-7 AC7.1: narration lock removed ────────────────────────────────────
class TestLockAbsence:
    def test_narration_lock_removed(self):
        """The narration lock is gone (REQ-7 AC7.1); serialization is the
        scheduler's single worker. The module must not expose the lock or its
        accessor."""
        import backend.agent.conversation_kernel as ck

        assert not hasattr(ck, "_NARRATION_PLAYBACK_LOCK")
        assert not hasattr(ck, "narration_playback_lock")