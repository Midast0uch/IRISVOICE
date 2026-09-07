"""BT-15 (vision-goal-directed-search REQ-28, T41): TTS memory-envelope behavior.

AC28.2 mechanism: repeated speaks reuse the ONE warm worker (no duplicate
  spawn — the live "worker reused" property, hermetic version).
Respawn-race edge: concurrent first-speaks while the worker is down spawn
  EXACTLY ONE worker; every caller queues behind readiness (singleflight via
  _proc_lock — pinned here, not built here).
Idle-unload cycle: reap-then-speak respawns exactly one worker through the
  REAL spawn path (beyond the unit suite, which stubs _spawn_worker).

Hermetic by construction: a fake Popen with scripted ready lines — no model,
no subprocess, no sleeps beyond a 0.5 s simulated load. Real-worker bytes
(AC28.1/28.2/28.4 gates) are covered by the T41 live re-measure, not here.
"""
from __future__ import annotations

import subprocess
import threading
import time

import pytest

from backend.agent import tts as tts_mod
from backend.agent.tts import TTSManager


@pytest.fixture(autouse=True)
def _isolated_manager():
    TTSManager._instance = None
    TTSManager._initialized = False
    mgr = TTSManager()
    yield mgr
    TTSManager._instance = None
    TTSManager._initialized = False


class _ParkedStream:
    """Stdout/stderr stand-in: yields scripted lines, then parks the reader
    daemon (harmless — daemon threads die with the test process)."""

    def __init__(self, lines, delay_s=0.0):
        self._lines = list(lines)
        self._delay_s = delay_s

    def __iter__(self):
        if self._delay_s:
            time.sleep(self._delay_s)
        yield from self._lines
        threading.Event().wait(60)

    def close(self):
        pass


class _FakePopen:
    """Popen double: slow-ready (0.5 s) simulates model load under contention."""

    instances: list = []

    def __init__(self, *args, **kwargs):
        type(self).instances.append(self)
        self._alive = True

        class _In:
            def write(self, data):
                pass

            def flush(self):
                pass

            def close(self):
                pass

        self.stdin = _In()
        self.stdout = _ParkedStream(['{"status": "ready"}\n'], delay_s=0.5)
        self.stderr = _ParkedStream([])

    def poll(self):
        return None if self._alive else 0

    def wait(self, timeout=None):
        self._alive = False
        return 0

    def kill(self):
        self._alive = False


@pytest.fixture(autouse=True)
def _fake_popen(monkeypatch):
    _FakePopen.instances = []
    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(tts_mod.subprocess, "Popen", _FakePopen)
    yield
    _FakePopen.instances = []


def test_concurrent_first_speak_spawns_exactly_one_worker(_isolated_manager):
    """Respawn-race edge: 4 threads speaking with no worker up → ONE Popen,
    every caller returns ready (queued behind readiness, AC28.3 shape)."""
    results: list = []

    def _speak():
        results.append(_isolated_manager._ensure_worker())

    threads = [threading.Thread(target=_speak) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads), "spawn threads must all finish"
    assert results == [True] * 4
    assert len(_FakePopen.instances) == 1, (
        f"singleflight violated: {len(_FakePopen.instances)} workers spawned"
    )
    assert _isolated_manager._ready is True


def test_repeated_speaks_reuse_warm_worker(_isolated_manager):
    """AC28.2 mechanism: 10 sequential speaks → 1 spawn total, always ready."""
    for _ in range(10):
        assert _isolated_manager._ensure_worker() is True
    assert len(_FakePopen.instances) == 1


def test_reap_then_speak_respawns_exactly_one_worker(_isolated_manager):
    """Idle-unload cycle end to end: reap the quiet worker, next speak
    respawns exactly one worker through the real spawn path."""
    assert _isolated_manager._ensure_worker() is True
    assert len(_FakePopen.instances) == 1
    _isolated_manager._last_activity = time.monotonic() - 9999
    _isolated_manager._idle_timeout_s = 60.0
    assert _isolated_manager._reap_if_idle() is True
    assert _isolated_manager._proc is None
    assert _isolated_manager._ensure_worker() is True
    assert len(_FakePopen.instances) == 2
    assert _isolated_manager._ready is True
