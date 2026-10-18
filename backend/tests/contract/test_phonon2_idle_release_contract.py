"""Contract: a readiness check is not user activity.

The Phonon-2 fermion server is a CPU speech engine. When it is warm it holds
~1.1 GB resident and 8 decode threads (measured 2026-10-16; its own /health
reports ``engine: cpu, threads: 8``). ``_IDLE_EXIT_S`` (20 min) is the only
thing that ever gives that back — the idle watchdog releases the server when
``time.monotonic() - _last_activity > _IDLE_EXIT_S``.

Two rules keep that policy alive, and both were broken:

  1. ALIVE IS NOT READY. ``_proc`` is the fermion launcher shim, which stays
     alive for the whole model load (90.3 s boot measured 2026-10-16) and for
     a server that never bound. Reading ``poll() is None`` as readiness made
     ``begin_utterance`` connect to a port nobody listens on (WinError 10061,
     once per utterance across the whole boot window) and made
     ``_phonon2_warm_up`` skip its spawn forever.

  2. A PROBE IS NOT ACTIVITY. ``server_ready()`` ran on every recording start
     (voice_command._phonon2_warm_up) and called ``touch()``, refreshing
     ``_last_activity``. The idle clock could therefore never advance, the
     watchdog never fired, and the server was never stopped for the lifetime
     of the app — even if the user never spoke.

Run: python -m pytest backend/tests/contract/test_phonon2_idle_release_contract.py -q
"""
from __future__ import annotations

import time

from backend.audio import phonon2_stream


class _AliveShim:
    """The fermion.exe launcher shim: alive, serving nothing."""

    def poll(self):
        return None  # alive

    def terminate(self):  # pragma: no cover - not exercised here
        pass

    def wait(self, timeout=None):  # pragma: no cover
        return 0


def _manager(healthy: bool):
    mgr = phonon2_stream._ServerManager.__new__(phonon2_stream._ServerManager)
    mgr._lock = __import__("threading").Lock()
    mgr._proc = _AliveShim()
    mgr._starting = False
    mgr._failed = 0
    mgr._disabled = False
    mgr._last_activity = time.monotonic()
    mgr._idle_thread = None
    # The probe under test: what the HTTP /health endpoint answers.
    mgr._healthy = lambda: healthy
    return mgr


# ── Rule 1: alive is not ready ──────────────────────────────────────────────

def test_server_ready_false_for_alive_but_unhealthy_process():
    """A live shim whose server does not answer is NOT ready.

    Old behavior returned True here, so the caller opened a WebSocket to a
    port nobody listened on and logged WinError 10061 once per utterance."""
    mgr = _manager(healthy=False)
    assert mgr.server_ready() is False


def test_server_ready_true_when_the_server_actually_answers():
    mgr = _manager(healthy=True)
    assert mgr.server_ready() is True


def test_ensure_does_not_claim_warm_for_alive_but_unhealthy():
    """``ensure`` must not report warm for a server that has not bound.

    Old behavior returned True, and the caller logged "Phonon-2 server warm —
    first utterance will stream" for a server that was still loading."""
    mgr = _manager(healthy=False)
    assert mgr.ensure() is False


def test_ensure_reports_warm_only_when_healthy():
    mgr = _manager(healthy=True)
    assert mgr.ensure() is True


# ── Rule 2: a probe is not activity ─────────────────────────────────────────

def test_readiness_probe_does_not_advance_the_idle_clock():
    """The exact defect: probing readiness reset the idle timer.

    ``_last_activity`` is pinned to a sentinel far in the past. If a probe
    touches it, the sentinel moves and the watchdog can never expire it."""
    mgr = _manager(healthy=True)
    mgr._last_activity = 0.0

    assert mgr.server_ready() is True
    assert mgr._last_activity == 0.0, (
        "server_ready() refreshed _last_activity; the idle watchdog can then "
        "never fire and the server holds ~1.1 GB + 8 threads forever"
    )


def test_repeated_recording_starts_still_let_the_server_go_idle():
    """End to end at the policy level: every recording start probes readiness.

    After those probes the watchdog's own comparison must still be able to
    see an idle server, or the release policy is dead code."""
    mgr = _manager(healthy=True)
    mgr._last_activity = 0.0

    for _ in range(5):  # five wake words, no speech in between
        mgr.server_ready()

    idle_for = time.monotonic() - mgr._last_activity
    assert idle_for > phonon2_stream._IDLE_EXIT_S, (
        f"server only looked idle for {idle_for:.0f}s; the watchdog releases "
        f"at {phonon2_stream._IDLE_EXIT_S:.0f}s, so it would never release"
    )
