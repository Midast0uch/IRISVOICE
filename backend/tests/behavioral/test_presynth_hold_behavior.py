"""Behavioral: hybrid pre-synthesis hold (REQ-10, T14) — BT-S8.
Drives the REAL manager hold store (fake worker transport), the REAL worker
hold action (stubbed model), the REAL scheduler lifecycle, and the REAL
kernel playback hook (fake TTS + pipeline), asserting the pre-synthesis
lifecycle:

  * played-from-hold (buffer consumed, no re-synthesis)
  * fell back (no buffer → on-admission synthesis, never a dropped beat)
  * cancelled-waste (every non-play exit frees; race discards)
  * lowest-priority (hold never queues ahead of lane synthesis)
  * buffer bounds (sentence cap + per-turn cap)

Proving tests for tasks.md T14 (matrix rows AC10.6/AC10.7).
"""
from __future__ import annotations

import base64
import io
import json
import threading
import time
import types as _t
from contextlib import redirect_stdout
from unittest.mock import MagicMock

import numpy as np

from backend.agent.speech_lanes import (
    NARRATION,
    SpeechObservability,
    SpeechScheduler,
)


def _wait_until(pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def _b64(arr):
    return base64.b64encode(np.asarray(arr, dtype=np.float32).tobytes()).decode()


# ── Worker hold action (stubbed model) ────────────────────────────────────
class _FakeTensor:
    def __init__(self, arr):
        self._arr = arr

    def cpu(self):
        return self

    def numpy(self):
        return self._arr


class _FakeModel:
    def __init__(self, chunks):
        self._chunks = chunks

    def generate_audio_stream(self, voice_state, sentence, frames_after_eos=0):
        for c in self._chunks:
            yield _FakeTensor(c)


class TestWorkerHoldAction:
    def test_hold_returns_single_message_with_stream_bytes(self):
        import backend.audio.tts_worker as w

        w._model = _FakeModel([np.ones(100, dtype=np.float32) * 0.5])
        w._voice_state = object()
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                w._synthesize_and_hold("Hello there.", 7)
            msgs = [json.loads(l) for l in buf.getvalue().strip().splitlines()]
            assert [m.get("type") for m in msgs] == ["held"]
            held = msgs[0]
            assert held["id"] == 7
            audio = np.frombuffer(base64.b64decode(held["data"]), dtype=np.float32)
            assert len(audio) == held["samples"] > 100  # audio + trailing

            buf2 = io.StringIO()
            with redirect_stdout(buf2):
                w._synthesize("Hello there.", 8)
            stream = [json.loads(l) for l in buf2.getvalue().strip().splitlines()]
            total = stream[-1]["total_samples"]
            assert [m.get("type") for m in stream][:-1] == ["chunk"] * (
                len(stream) - 1
            )
            # Same bytes whether streamed or held.
            assert total == held["samples"]
        finally:
            w._model, w._voice_state = None, None

    def test_hold_without_model_errors(self):
        import backend.audio.tts_worker as w

        w._model, w._voice_state = None, None
        buf = io.StringIO()
        with redirect_stdout(buf):
            w._synthesize_and_hold("Hi.", 9)
        msgs = [json.loads(l) for l in buf.getvalue().strip().splitlines()]
        assert msgs[0]["type"] == "error"


# ── Manager hold store (fake transport) ───────────────────────────────────
def _make_manager():
    from backend.agent.tts import TTSManager

    mgr = TTSManager.__new__(TTSManager)
    mgr._proc = MagicMock()
    mgr._proc.poll.return_value = None
    mgr._ready = True
    mgr._synthesis_lock = threading.Lock()
    # T15 (AC10.14) added the narration-toggle gate on holds — the real
    # __init__ sets it True (tts.py:213). This fixture bypasses __init__, so
    # it must carry the same default or every hold is refused for the wrong
    # reason (AttributeError swallowed → None).
    mgr._holds_accepted = True
    mgr._held = {}
    mgr._held_turn_counts = {}
    mgr._dead_hold_keys = set()
    return mgr


def _wire_fake_transport(mgr, audio):
    """Worker answers synthesize_and_hold with `audio` for the sent id."""
    sent: list = []
    mgr._send = lambda payload: sent.append(payload)

    def _read_line(timeout=None):
        req_id = sent[-1]["id"]
        return {
            "type": "held",
            "id": req_id,
            "data": _b64(audio),
            "samples": len(audio),
        }

    mgr._read_line = _read_line
    mgr._synthesis_deadline = lambda text: time.monotonic() + 30.0
    return sent


class TestManagerHoldStore:
    def test_presynth_store_take_take_empty(self):
        mgr = _make_manager()
        audio = np.ones(240, dtype=np.float32)
        _wire_fake_transport(mgr, audio)
        key = mgr.presynthesize_hold("t1", "Checking sources.")
        assert key and key.startswith("hold:t1:")
        got = mgr.take_held(key)
        assert isinstance(got, np.ndarray) and (got == audio).all()
        assert mgr.take_held(key) is None  # consumed — fallback after

    def test_hold_never_blocks_on_busy_lock(self):
        """AC10.6 lowest-priority: a busy synthesis lock refuses fast."""
        mgr = _make_manager()
        audio = np.ones(240, dtype=np.float32)
        _wire_fake_transport(mgr, audio)
        assert mgr._synthesis_lock.acquire(blocking=False)
        try:
            t0 = time.monotonic()
            assert mgr.presynthesize_hold("t1", "Line.") is None
            assert time.monotonic() - t0 < 2.0
        finally:
            mgr._synthesis_lock.release()

    def test_hold_refused_when_worker_not_ready(self):
        mgr = _make_manager()
        mgr._ready = False  # never spawns for background work
        assert mgr.presynthesize_hold("t1", "Line.") is None

    def test_sentence_cap_and_turn_cap(self):
        mgr = _make_manager()
        audio = np.ones(240, dtype=np.float32)
        _wire_fake_transport(mgr, audio)
        assert mgr.presynthesize_hold("t1", "x" * 301) is None
        keys = [mgr.presynthesize_hold("t1", f"Line {i}.") for i in range(6)]
        assert all(keys)
        assert mgr.presynthesize_hold("t1", "One more.") is None

    def test_free_counts_waste_and_dead_race(self):
        mgr = _make_manager()
        audio = np.ones(240, dtype=np.float32)
        _wire_fake_transport(mgr, audio)
        key = mgr.presynthesize_hold("t1", "Line.")
        assert mgr.free_held(key) is True  # waste counted
        assert mgr.take_held(key) is None
        assert mgr.free_held("hold:t1:1") is False  # nothing stored yet
        # A completion racing ahead of its free discards instead of storing.
        assert mgr._store_hold("t1", "Late.", audio) == "hold:t1:1"
        assert mgr.take_held("hold:t1:1") is None
        assert "hold:t1:1" not in mgr._dead_hold_keys

    def test_free_turn_sweeps(self):
        mgr = _make_manager()
        audio = np.ones(240, dtype=np.float32)
        _wire_fake_transport(mgr, audio)
        mgr.presynthesize_hold("t1", "One.")
        mgr.presynthesize_hold("t1", "Two.")
        mgr.presynthesize_hold("t2", "Other.")
        assert mgr.free_turn_held("t1") == 2
        assert mgr.take_held("hold:t2:0") is not None


# ── Scheduler free-on-exit + kernel playback hook ─────────────────────────
class TestHoldLifecycle:
    def test_cancel_frees_held_buffer(self):
        freed: list = []
        sched = SpeechScheduler(
            play=lambda node: None,
            observability=SpeechObservability(),
            auto_start=False,
        )
        sched.set_audio_free_callback(freed.append)
        try:
            from backend.agent.speech_lanes import KIND_PLANNED

            beat = sched.add_beat(
                "Pending.", turn_id="t1", session_id="s1",
                kind=KIND_PLANNED, audio_ref="hold:t1:0",
            )
            assert sched.cancel_beat(beat, turn_id="t1", session_id="s1") is True
            assert freed == ["hold:t1:0"]
        finally:
            sched.stop()

    def test_barge_frees_held_buffers(self):
        freed: list = []
        hold = threading.Event()
        sched = SpeechScheduler(
            play=lambda node: hold.wait(timeout=30.0),
            observability=SpeechObservability(),
            auto_start=True,
        )
        sched.set_audio_free_callback(freed.append)
        try:
            sched.add_beat(
                "Queued.", turn_id="t1", session_id="s1", audio_ref="hold:t1:3"
            )
            assert _wait_until(lambda: sched.is_playing())
            sched.barge_in(turn_id="t2", session_id="s1")
            assert "hold:t1:3" in freed
        finally:
            hold.set()
            sched.stop()

    def test_playback_consumes_hold_without_resynthesis(self):
        """Played-from-hold: held audio plays, synthesize_stream untouched."""
        from backend.agent.conversation_kernel import ConversationKernel

        held_audio = np.ones(480, dtype=np.float32)
        tts = MagicMock()
        tts.take_held = MagicMock(return_value=held_audio)
        tts.synthesize_stream = MagicMock(
            side_effect=AssertionError("must not synthesize")
        )
        pipeline = MagicMock()
        played: list = []
        pipeline.play_stream = lambda stream, sample_rate: played.append(
            list(stream)
        )
        kernel = ConversationKernel(
            voice_handler=MagicMock(),
            tts_manager=tts,
            audio_pipeline=pipeline,
            session_id_getter=lambda: "sess-1",
            broadcast_event=lambda sid, msg: None,
        )
        kernel._tts_manager = tts
        kernel._audio_pipeline = pipeline
        kernel._speak_utterance("Hello.", interrupt=False, audio_ref="hold:t1:0")
        tts.take_held.assert_called_once_with("hold:t1:0")
        assert len(played) == 1 and (played[0][0] == held_audio).all()

    def test_playback_falls_back_without_hold(self):
        """Fell back: no buffer → normal on-admission synthesis path."""
        from backend.agent.conversation_kernel import ConversationKernel

        tts = MagicMock()
        tts.take_held = MagicMock(return_value=None)
        tts.synthesize_stream = MagicMock(return_value=iter([np.ones(10)]))
        pipeline = MagicMock()
        kernel = ConversationKernel(
            voice_handler=MagicMock(),
            tts_manager=tts,
            audio_pipeline=pipeline,
            session_id_getter=lambda: "sess-1",
            broadcast_event=lambda sid, msg: None,
        )
        kernel._tts_manager = tts
        kernel._audio_pipeline = pipeline
        kernel._speak_utterance("Hello.", interrupt=False, audio_ref="hold:t1:9")
        tts.synthesize_stream.assert_called_once_with("Hello.")


class TestPlannedBeatsTrigger:
    def test_beats_admitted_with_hold_refs_when_idle(self):
        from backend.agent.agent_kernel import AgentKernel

        admitted: list = []

        class _FakeScheduler:
            def is_playing(self):
                return False

            def admit(self, node):
                admitted.append(node)

            def add_beat(self, text, *, turn_id, session_id, kind,
                         audio_ref=None):
                import types as _t

                node = _t.SimpleNamespace(
                    content={"kind": "text", "text": text},
                    audio_ref=audio_ref,
                )
                admitted.append(node)
                return f"id-{text[:4]}"

        fake_kernel = _t.SimpleNamespace(scheduler=_FakeScheduler())
        holds: dict = {}

        class _FakeTTS:
            def presynthesize_hold(self, turn_id, text):
                key = f"hold:{turn_id}:{text[:4]}"
                holds[key] = text
                return key

            def free_held(self, key):
                return holds.pop(key, None) is not None

        k = AgentKernel.__new__(AgentKernel)
        plan = _t.SimpleNamespace(
            beats=["First.", "Second beat here.", "Third beat here."]
        )
        from unittest.mock import patch

        with patch(
            "backend.agent.conversation_kernel.get_conversation_kernel",
            return_value=fake_kernel,
        ), patch(
            "backend.agent.tts.get_tts_manager", return_value=_FakeTTS()
        ):
            k._admit_planned_beats(plan, turn_id="t1", session_id="s1")
        assert len(admitted) == 2  # beats 2..N (first speaks immediately)
        assert admitted[0].audio_ref == "hold:t1:Seco"
        assert len(holds) == 2

    def test_lane_busy_skips_presynth_but_admits(self):
        """Lowest-priority: a playing lane means buffers wait — beats still
        admit (fallback at play), presynth refused."""
        from backend.agent.agent_kernel import AgentKernel
        import types as _types

        admitted: list = []

        class _BusyScheduler:
            def is_playing(self):
                return True

            def add_beat(self, text, *, turn_id, session_id, kind,
                         audio_ref=None):
                admitted.append((text, audio_ref))
                return "id-x"

        class _RefusingTTS:
            def presynthesize_hold(self, turn_id, text):
                raise AssertionError("must not presynthesize while busy")

        k = AgentKernel.__new__(AgentKernel)
        plan = _t.SimpleNamespace(beats=["First.", "Second."])
        from unittest.mock import patch

        with patch(
            "backend.agent.conversation_kernel.get_conversation_kernel",
            return_value=_t.SimpleNamespace(scheduler=_BusyScheduler()),
        ), patch(
            "backend.agent.tts.get_tts_manager", return_value=_RefusingTTS()
        ):
            k._admit_planned_beats(plan, turn_id="t1", session_id="s1")
        assert admitted == [("Second.", None)]  # admitted, bufferless
