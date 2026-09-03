"""Contract: the vision readiness probe actually RUNS (T24, REQ-1/REQ-3).

WHY THIS FILE EXISTS. `_ensure_vision_server_running` imports httpx inside its
own body, which binds it as a LOCAL to that function. The readiness poll lives
in a DIFFERENT function, `_spawn_vision_server_now`, where httpx was never in
scope and there is no module-level import. Every poll raised NameError and the
bare `except Exception: pass` swallowed it, so the probe never executed once.

The visible symptom was not "probe broken". It was a healthy llama-server —
listening on 127.0.0.1 in ~3s, per its own log — being reported `not_ready`
300 seconds later and killed. That signature (flat log, flat CPU, live process)
is indistinguishable from the antivirus-contention failure this codebase had
already been bitten by, and it misdirected the investigation twice.

Measured 2026-08-25 with host prerequisites confirmed in effect:
    before: ttr_sec=305.61  ok=False
    after:  ttr_sec=4.01    ok=True

These tests assert the PROPERTY, not the import statement: drive the real
readiness loop against a fake server and require that it polls, and that a
programming error inside the loop is never silently absorbed.
"""
from __future__ import annotations

import sys
from unittest import mock

import pytest

from backend.tools import lfm_vl_provider as vl


class _FakeProc:
    """Alive for the whole poll — never exits, so the loop cannot short-circuit
    on the process-death branch and must reach the HTTP probe."""

    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid

    def poll(self):
        return None

    def wait(self, timeout=None):
        return None


class _Resp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


@pytest.fixture()
def _spawn_env(monkeypatch, tmp_path):
    """Patch every external the spawn path touches; record probe URLs."""
    monkeypatch.setattr(
        vl, "_find_vision_model",
        lambda *a, **k: (str(tmp_path / "m.gguf"), str(tmp_path / "mm.gguf")),
    )
    monkeypatch.setattr(vl, "_find_llama_server_binary", lambda: str(tmp_path / "llama-server.exe"))
    monkeypatch.setattr(vl, "_compute_vision_gpu_layers", lambda *a, **k: 999)
    monkeypatch.setattr(vl, "_read_free_vram_gb", lambda: (7.4, True, True))
    monkeypatch.setattr(vl.time, "sleep", lambda s: None)
    monkeypatch.setattr(vl.subprocess, "Popen", lambda *a, **k: _FakeProc())
    monkeypatch.setattr(vl, "_kill_process_tree", lambda pid: None)
    # Keep the loop short if the probe never succeeds, so a REGRESSION fails
    # fast instead of hanging the suite for five minutes.
    monkeypatch.setenv("IRIS_VISION_READY_WINDOW_S", "2")
    monkeypatch.setenv("IRIS_VISION_READY_MAX_S", "10")

    saved_pid, saved_attempt = vl._VISION_SERVER_PID, vl._spawn_attempt
    yield
    vl._VISION_SERVER_PID, vl._spawn_attempt = saved_pid, saved_attempt


def test_readiness_loop_actually_probes_the_server(_spawn_env, monkeypatch):
    """THE regression guard: the poll must issue at least one HTTP request.

    With the missing import this count was ZERO — the loop spun for the whole
    no-progress window without ever reaching the network.
    """
    import httpx

    calls: list[str] = []

    def _get(url, *a, **kw):
        calls.append(str(url))
        return _Resp(200)

    monkeypatch.setattr(httpx, "get", _get)

    vl._spawn_vision_server_now()

    probe_calls = [u for u in calls if "127.0.0.1" in u and "/models" in u]
    assert probe_calls, (
        "the readiness loop issued NO probe request. httpx is imported as a "
        "LOCAL of _ensure_vision_server_running; if _spawn_vision_server_now "
        "does not import it too, every poll raises NameError and the bare "
        f"except swallows it. Saw: {calls!r}"
    )


def test_ready_probe_targets_ipv4_explicitly(_spawn_env, monkeypatch):
    """`localhost` resolves ::1 first here and llama-server binds IPv4 only."""
    import httpx

    calls: list[str] = []
    monkeypatch.setattr(httpx, "get", lambda url, *a, **k: (calls.append(str(url)), _Resp(200))[1])

    vl._spawn_vision_server_now()

    assert calls, "no probe issued"
    assert all("127.0.0.1" in u for u in calls if "/models" in u), (
        f"every readiness probe must target 127.0.0.1 explicitly, got {calls!r}"
    )


def test_a_programming_error_in_the_loop_is_not_swallowed(_spawn_env, monkeypatch):
    """A NameError/AttributeError inside the poll must surface, not read as
    'the server is not responding yet'.

    This is the guard on the thing that HID the bug. Without it the probe can
    be broken again by any refactor and the only symptom is a slow, confident,
    wrong 'not_ready'.
    """
    import httpx

    def _boom(url, *a, **kw):
        raise NameError("name 'httpx' is not defined")

    monkeypatch.setattr(httpx, "get", _boom)

    with pytest.raises(NameError):
        vl._spawn_vision_server_now()


def test_a_connection_error_is_still_tolerated(_spawn_env, monkeypatch):
    """The narrowed except must NOT make ordinary 'not up yet' fatal — a
    connection failure is the expected case while the server is still loading.
    """
    import httpx

    def _refused(url, *a, **kw):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", _refused)

    # Returns False (never became ready) rather than raising.
    assert vl._spawn_vision_server_now() is False
