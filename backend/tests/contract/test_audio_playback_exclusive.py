"""Only one utterance uses the audio device at a time (2026-10-01).

The backend died with an access violation in python314.dll; the faulthandler
stack showed sounddevice.stop() inside sd.play() on one thread while a SECOND
play thread for the same utterance was still streaming. sd.play() keeps one
process-global stream and stops it first, so two threads playing at once broke
each other's stream in native code. Two sessions speaking at once, or the
speech watchdog failing a wedged node while its thread still runs, both did it.
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import numpy as np

from backend.audio import pipeline as pl


class _Device:
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.calls = 0
        self.lock = threading.Lock()

    def play(self, data, samplerate=None, device=None, blocking=True):
        with self.lock:
            self.active += 1
            self.calls += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)
        with self.lock:
            self.active -= 1


def _pipeline():
    p = pl.AudioPipeline.__new__(pl.AudioPipeline)
    p._native_available = False
    p._native_player = None
    p.output_device = None
    p.sample_rate = 24000
    return p


def test_concurrent_plays_never_overlap(monkeypatch):
    dev = _Device()
    monkeypatch.setattr(pl, "_sd", lambda: dev)
    p = _pipeline()
    chunk = np.zeros(2400, dtype=np.float32)

    def stream():
        p.play_stream(iter([chunk, chunk]))

    def single():
        p.play_audio(chunk)

    threads = [threading.Thread(target=f) for f in (stream, single, stream, single)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert dev.calls == 4
    assert dev.max_active == 1, "two utterances used the audio device at once"


def test_a_busy_device_skips_instead_of_hanging(monkeypatch):
    monkeypatch.setattr(pl, "_PLAYBACK_WAIT_S", 0.1)
    dev = _Device()
    monkeypatch.setattr(pl, "_sd", lambda: dev)
    p = _pipeline()
    assert pl._PLAYBACK_LOCK.acquire(timeout=1)
    try:
        t0 = time.perf_counter()
        p.play_audio(np.zeros(240, dtype=np.float32))
        assert time.perf_counter() - t0 < 1.0
        assert dev.calls == 0
    finally:
        pl._PLAYBACK_LOCK.release()
