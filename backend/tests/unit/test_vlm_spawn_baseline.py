"""Wave 0 baselines (T0a + T0b) — NOW THE POST-CHANGE CONTRACT GUARDS.

specs/vision-browser-stage REQ-1/REQ-2/REQ-3 changed exactly the behaviors
this file originally pinned against UNCHANGED code. Per the baseline rule,
this file was edited EXACTLY ONCE — by T1/T2/T3, which flipped each
assertion from "documents the race/debt" to "guards the fix":

  T0a -> REQ-1/REQ-2 guards:
    - Concurrent `_ensure_vision_server_running` callers coalesce onto ONE
      spawn (was: one Popen per caller).
    - The failure cleanup kills ONLY the attempt's own process tree; an
      unowned listener on the port is never touched (was: port-scan kill).

  T0b -> REQ-3 guards:
    - The spawn is DIRECT (argv[0] IS the llama-server binary) — no launcher
      interpreter prefix.
    - A failed start resets `_VISION_SERVER_PID` and logs `ttr_sec`
      (unchanged observable contract).

No subprocess, no GPU, no network: every external dependency is monkeypatched.
"""

import logging
import sys
import threading

import pytest

from backend.tools import lfm_vl_provider as vl

FAKE_MODEL_PATH = "C:/models/LFM2.5-VL-3B/model.gguf"
FAKE_MMPROJ_PATH = "C:/models/LFM2.5-VL-3B/mmproj-model.gguf"
FAKE_BINARY = "C:/fake/llama-server.exe"


class _RaisingHttpxGet:
    """Health checks always report DOWN -> every caller enters the spawn path.

    Records every probe URL so the IPv4 half of the REQ-3 contract is actually
    asserted rather than only described in a docstring.
    """

    def __init__(self):
        self.urls = []

    def __call__(self, *args, **kwargs):
        if args:
            self.urls.append(str(args[0]))
        raise ConnectionError("no server listening (test double)")


class _FakeProc:
    """Fake Popen handle: already-exited so the readiness loop takes the
    'exited during start' edge on the first poll and returns quickly."""

    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return 1


@pytest.fixture()
def _patched_env(monkeypatch):
    """Patch everything the spawn path touches; record Popen/kill calls."""
    monkeypatch.setattr(vl, "_find_vision_model", lambda *a, **k: (FAKE_MODEL_PATH, FAKE_MMPROJ_PATH))
    monkeypatch.setattr(vl, "_find_llama_server_binary", lambda: FAKE_BINARY)
    monkeypatch.setattr(vl, "_compute_vision_gpu_layers", lambda *a, **k: 999)
    # Hermetic VRAM read: the real one shells out to nvidia-smi, whose
    # subprocess.run would be intercepted by the Popen patch below.
    monkeypatch.setattr(vl, "_read_free_vram_gb", lambda: (7.4, True, True))
    monkeypatch.setattr(vl.time, "sleep", lambda seconds: None)
    # Progress-aware readiness: shrink the no-progress window so failure
    # paths resolve instantly instead of spinning the real 120s.
    monkeypatch.setenv("IRIS_VISION_READY_WINDOW_S", "1")

    import httpx as _httpx
    _probe = _RaisingHttpxGet()
    monkeypatch.setattr(_httpx, "get", _probe)

    recorded = {
        "popen": [], "tree_kills": [], "coalesced_logs": [],
        "probe_urls": _probe.urls,
    }

    class _RecordingHandler(logging.Handler):
        def emit(self, record):
            msg = record.getMessage()
            if "coalesced waiter" in msg:
                recorded["coalesced_logs"].append(msg)

    handler = _RecordingHandler()
    _logger = logging.getLogger("backend.tools.lfm_vl_provider")
    _logger.addHandler(handler)
    _saved_level = _logger.level
    _logger.setLevel(logging.INFO)  # the coalesce line logs at INFO

    def _fake_popen(args, **kwargs):
        recorded["popen"].append(args)
        return _FakeProc(pid=4000 + len(recorded["popen"]))

    def _fake_tree_kill(pid):
        recorded["tree_kills"].append(pid)

    monkeypatch.setattr(vl.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(vl, "_kill_process_tree", _fake_tree_kill)

    # Save/restore the module-global PID bookkeeping each test mutates.
    saved_pid = vl._VISION_SERVER_PID
    saved_attempt = vl._spawn_attempt
    yield recorded
    vl._VISION_SERVER_PID = saved_pid
    vl._spawn_attempt = saved_attempt
    _logger.setLevel(_saved_level)
    _logger.removeHandler(handler)


# ── REQ-1 guard: single-flight spawn ────────────────────────────────────────

def test_concurrent_callers_spawn_exactly_once(_patched_env):
    """REQ-1 AC3: two concurrent callers against a cold server produce ONE
    spawn; the second coalesces onto the in-flight attempt and shares its
    result. (Baseline asserted == 2 Popens; T1 flipped it to == 1.)"""
    recorded = _patched_env
    barrier = threading.Barrier(2, timeout=5)
    results = []

    def _caller():
        barrier.wait()
        results.append(vl._ensure_vision_server_running())

    threads = [threading.Thread(target=_caller) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 2, "both callers must complete"
    assert results[0] == results[1], "waiter shares the leader's outcome"
    assert len(recorded["popen"]) == 1, (
        f"REQ-1: exactly ONE spawn for N concurrent callers "
        f"(got {len(recorded['popen'])})"
    )
    assert recorded["coalesced_logs"], (
        "REQ-1 AC4: the waiter logs that it joined the in-flight spawn"
    )


def test_failure_cleanup_kills_only_own_process_tree(_patched_env):
    """REQ-2 AC1/AC2: a failed attempt kills ONLY its own process tree. No
    port scan runs; an unowned listener on the vision port survives.
    (Baseline asserted the fake 'stray' 9999 WAS killed; T2 flipped it.)"""
    recorded = _patched_env

    result = vl._ensure_vision_server_running()

    assert result is False
    assert recorded["tree_kills"] == [4001], (
        "cleanup kills exactly this attempt's own pid (the first spawned proc)"
    )


# ── REQ-3 guard: direct detached spawn ──────────────────────────────────────

def test_spawn_is_direct_and_probe_is_ipv4(_patched_env):
    """REQ-3 (FINAL, evidence-driven 2026-08-23): direct detached spawn is the
    default — the launcher produced 0KB stderr logs and zero successful loads,
    while direct mode loaded + listened in ~3s once the PROBE was fixed. The
    probe must target 127.0.0.1 explicitly: `localhost` resolves ::1 first on
    this machine and llama-server binds IPv4 only — that probe bug, not any
    load hang, is what killed healthy servers. (Baseline edited three times
    for T3; every flip is documented in tasks.md.)"""
    recorded = _patched_env

    vl._ensure_vision_server_running()

    assert recorded["popen"], "spawn attempted"
    argv = recorded["popen"][0]
    # REPORTABLE TEST EDIT (T15, 2026-08-24): this assertion and this test's
    # NAME were the last two places still pinning the LAUNCHER WRAPPER. The
    # T3 re-land updated this file's module docstring ("The spawn is DIRECT —
    # argv[0] IS the llama-server binary"), this section header, REQ-3
    # "Verified (CORRECTED)" and tasks.md (IRIS_VISION_SPAWN_WRAPPER DELETED),
    # but left the assert body and the name behind — a half-applied edit, not
    # a code regression. The wrapper theory is FALSIFIED: the launcher produced
    # 0KB stderr logs and zero successful loads, direct mode loads and listens
    # in ~3s. Flipped to guard the shipped behavior.
    assert argv[0] == FAKE_BINARY, (
        "REQ-3: the spawn is DIRECT — argv[0] IS the llama-server binary, "
        "with no launcher interpreter prefix"
    )
    assert argv[0] != sys.executable, "no interpreter wrapper in front of it"
    # The other half of the name, now actually asserted: `localhost` resolves
    # ::1 first on this host and llama-server binds IPv4 only, so a probe that
    # does not target 127.0.0.1 explicitly reports a healthy server as dead and
    # kills it. That probe bug — not any load hang — is what broke this path.
    assert recorded["probe_urls"], "the readiness path probes the server"
    assert all("127.0.0.1" in u for u in recorded["probe_urls"]), (
        f"every probe targets IPv4 explicitly, never localhost "
        f"(got {recorded['probe_urls']})"
    )


def test_failed_start_resets_pid_and_logs_ttr(caplog, _patched_env):
    """Unchanged observable contract (T0b): a failed start clears
    `_VISION_SERVER_PID` and the warning carries `ttr_sec`."""
    recorded = _patched_env
    vl._VISION_SERVER_PID = None  # clean slate

    with caplog.at_level(logging.WARNING, logger="backend.tools.lfm_vl_provider"):
        result = vl._ensure_vision_server_running()

    assert result is False
    assert vl._VISION_SERVER_PID is None, "failed start resets the tracked pid"
    warning_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "ttr_sec" in warning_text, (
        "time-to-ready measurement must survive every spawn-mechanism change"
    )




