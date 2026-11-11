"""Contract: restarting a WEDGED TTS worker never hangs (2026-11-11 incident).

A wedged worker is alive and silent. The tts-stdout / tts-stderr threads sit in
a blocking read on its pipes, and a buffered pipe's close() takes the lock that
read holds - so the old `_restart_worker` (close the pipes, THEN kill) blocked in
close() forever. Live, 2026-11-11 09:57:15 UTC (backend pid 18764): "Restarting
TTS worker after crash" was never followed by "Spawning Pocket-TTS subprocess
worker", /health stayed 503 {"tts": "loading"} until the backend was closed, and
every later utterance was skipped as "audio device busy for 60s".

The worker here is a REAL child process that never writes (a sleep), with the
manager's own reader threads attached - the exact state of the incident. Only
the respawn is stubbed: loading the model is not what this contract is about.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time

import pytest

from backend.agent.tts import TTSManager

# A restart of a dead-or-wedged worker must hand over to the respawn in well
# under this. The old code blocked until the child exited (60 s here).
_RESTART_BOUND_S = 10.0


@pytest.fixture()
def mgr():
    TTSManager._instance = None
    TTSManager._initialized = False
    m = TTSManager()
    yield m
    TTSManager._instance = None
    TTSManager._initialized = False


def _wedged_worker(m: TTSManager) -> subprocess.Popen:
    """Spawn a silent live child and attach the manager's reader threads to it,
    as `_spawn_worker` does."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    threading.Thread(
        target=m._read_stdout, args=(proc.stdout, m._lines), daemon=True,
        name="tts-stdout-test",
    ).start()
    threading.Thread(
        target=m._drain_stderr, args=(proc.stderr,), daemon=True,
        name="tts-stderr-test",
    ).start()
    time.sleep(0.3)  # let both readers enter their blocking read
    return proc


def test_restart_of_wedged_worker_kills_it_and_respawns_without_hanging(mgr):
    proc = _wedged_worker(mgr)
    mgr._proc, mgr._ready = proc, True
    spawned = threading.Event()
    mgr._spawn_worker = spawned.set  # the respawn itself is out of scope

    t = threading.Thread(target=mgr._restart_worker, daemon=True)
    try:
        t.start()
        t.join(_RESTART_BOUND_S)
        assert not t.is_alive(), (
            "_restart_worker hung on a wedged worker (pipes closed before kill)"
        )
        assert spawned.is_set(), "the restart never reached the respawn"
        assert proc.poll() is not None, "the wedged worker was not killed"
        assert mgr._proc is None and mgr._ready is False
        assert proc.stdout.closed and proc.stderr.closed, (
            "the dead worker's pipes were left open (handle leak per restart)"
        )
    finally:
        proc.kill()  # releases the old code's blocked close() so the run ends
        t.join(_RESTART_BOUND_S)


def test_restart_leaves_pipes_open_when_kill_does_not_end_the_worker(mgr):
    """The explicit exception path: a worker still alive after kill keeps its
    pipes (closing them would hang the same way) and the respawn still runs."""
    closed: list = []

    class _Pipe:
        def __init__(self, name):
            self.name = name

        def close(self):
            closed.append(self.name)

    class _Unkillable:
        pid = 4242
        stdin, stdout, stderr = _Pipe("stdin"), _Pipe("stdout"), _Pipe("stderr")

        def kill(self):
            pass

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired("tts_worker", timeout)

    mgr._proc, mgr._ready = _Unkillable(), True
    spawned = threading.Event()
    mgr._spawn_worker = spawned.set

    mgr._restart_worker()

    assert closed == [], "pipes of a live worker were closed (that close blocks)"
    assert spawned.is_set()
    assert mgr._proc is None and mgr._ready is False
