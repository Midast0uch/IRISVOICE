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


class _Stop(Exception):
    """Fake CallbackStop."""


class _Stream:
    """Fake OutputStream: start() drains the buffer through the callback on
    the calling thread (the owned-stream pattern, 2026-10-23) and counts the
    active device use under the lock. The CONTRACT is unchanged: only one
    utterance on the device at a time."""

    def __init__(self, dev, samplerate=None, channels=1, dtype=None,
                 device=None, blocksize=None, callback=None):
        self._dev = dev
        self._cb = callback

    def start(self):
        with self._dev.lock:
            self._dev.active += 1
            self._dev.calls += 1
            self._dev.max_active = max(self._dev.max_active, self._dev.active)
        out = np.zeros((4096, 1), dtype=np.float32)
        try:
            while True:
                self._cb(out, 4096, None, None)
        except _Stop:
            pass
        with self._dev.lock:
            self._dev.active -= 1

    def stop(self):
        pass

    def close(self):
        pass


class _Device:
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.calls = 0
        self.lock = threading.Lock()
        self.OutputStream = lambda **kw: _Stream(self, **kw)
        self.CallbackStop = _Stop

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
