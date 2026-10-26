"""The wake word opens the pipeline only when STT hears the name (2026-10-25).

Live 2026-10-25 21:58-22:30: background noise opened the pipeline (chime +
recording) before the in-take confirm rejected it, and the owner's normal
"Hey Iris" never fired - its runs above the bar were 1-3 chunks, the streak gate
needs 4, so only a drawn-out "heyyyy iris" got through. The first real open then
failed because the confirm used a cold whisper while Phonon-2 was warm.

These pin the seam: AudioEngine asks the judge before anything opens, a near
miss is judged too, and the take reuses the verdict instead of a second STT.
"""
from __future__ import annotations

import threading
import time

import numpy as np

from backend.audio.engine import AudioEngine
from backend.audio.voice_command import VoiceCommandHandler


class _Detector:
    wake_phrase = "Hey Iris"

    def __init__(self, fire=False, near=False):
        self._fire, self._near = fire, near

    def process_frame(self, _pcm):
        hit, self._fire = self._fire, False
        return hit, ("Hey Iris" if hit else None)

    def take_near_miss(self):
        hit, self._near = self._near, False
        return hit


def _engine(detector, judge):
    eng = object.__new__(AudioEngine)  # no mic, no pipeline
    eng._wake_word_enabled = True
    eng._wake_detector_initialized = True
    eng._wake_detector = detector
    eng._tts_active = False
    opened = threading.Event()
    eng._on_wake_word_detected = lambda _w: opened.set()
    eng.set_wake_judge(judge)
    return eng, opened


def _frames(eng, n=60):
    for _ in range(n):
        eng._process_audio_frame(np.full(320, 0.05, dtype=np.float32))


def test_background_noise_that_fires_the_detector_opens_nothing():
    eng, opened = _engine(_Detector(fire=True), lambda clip: (False, "Now, Miss, Miss, Miss"))
    _frames(eng)
    assert not opened.wait(1.5), "a fire the judge rejected opened the pipeline"
    assert eng.take_wake_verdict() is None


def test_a_short_hey_iris_that_only_near_misses_opens_the_pipeline():
    eng, opened = _engine(_Detector(near=True), lambda clip: (len(clip) > 0, "Hey, Iris."))
    _frames(eng)
    assert opened.wait(3.0), "a near miss the judge confirmed did not open the pipeline"
    assert eng.take_wake_verdict() == "Hey, Iris."
    assert eng.take_wake_verdict() is None, "the verdict is taken once"


def test_the_take_reuses_the_pre_open_verdict_without_a_second_stt():
    class _Eng:
        pipeline = object()

        def register_frame_listener(self, _fn):
            pass

        def take_wake_verdict(self):
            return "Hey, Iris."

        def take_wake_clip(self):
            raise AssertionError("the take transcribed the clip again")

    h = VoiceCommandHandler(_Eng())
    t0 = time.monotonic()
    v = h._begin_wake_confirm()
    assert v["done"].is_set() and v["ok"] and v["heard"] == "Hey, Iris."
    assert time.monotonic() - t0 < 0.5


def test_the_judge_refuses_while_a_take_records():
    class _Eng:
        pipeline = object()

        def register_frame_listener(self, _fn):
            pass

    h = VoiceCommandHandler(_Eng())
    h.is_recording = True
    ok, heard = h._judge_wake_clip(np.zeros(16000, dtype=np.float32))
    assert not ok and "busy" in heard


def test_the_judge_decodes_one_short_pass():
    """Live 2026-10-25: the full decode retried every temperature on noise - median 3.7 s, max 67 s before a chime."""
    class _Eng:
        pipeline = object()

        def register_frame_listener(self, _fn):
            pass

    seen = {}

    class _W:
        def transcribe(self, _clip, **kw):
            seen.update(kw)
            return [], None

    h = VoiceCommandHandler(_Eng())
    h._whisper = _W()
    h._judge_wake_clip(np.zeros(16000, dtype=np.float32))
    assert seen.get("temperature") == 0.0, seen
    assert 0 < seen.get("max_new_tokens", 0) <= 32, seen
