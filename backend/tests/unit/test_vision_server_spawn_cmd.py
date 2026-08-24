"""T4 (REQ-6) — vision server spawn no longer stalls on llama.cpp auto-fit.

`--fit on` is llama.cpp b9591's default and was measured stalling 12-36
minutes on MoE models. That was fixed for the MAIN model loader in commit
e9d2fc89 (`local_model_manager._build_server_cmd`, pinned by
`test_build_server_cmd_baseline.py`). The vision server spawn in
`backend/tools/lfm_vl_provider.py:_ensure_vision_server_running` is a
SEPARATE code path that never carried the fix — this test pins that it now
does, mirroring `_build_server_cmd`'s flags/ordering conventions.

No subprocess, no GPU, no real llama-server binary, no network: every
external dependency `_ensure_vision_server_running` touches is monkeypatched
so only the argv construction is exercised. `time.sleep` is patched to a
no-op and the fake spawned process reports itself as already-exited on the
first readiness poll, so the function returns almost immediately regardless
of the (patched) `httpx` transport.
"""

import sys

from backend.tools import lfm_vl_provider as vl

FAKE_MODEL_PATH = "C:/models/LFM2.5-VL-3B/model.gguf"
FAKE_MMPROJ_PATH = "C:/models/LFM2.5-VL-3B/mmproj-model.gguf"
FAKE_BINARY = "C:/fake/llama-server.exe"
FAKE_NGL = 999


class _RaisingHttpxGet:
    """Stand-in for httpx.get that always raises -> health checks report down."""

    def __call__(self, *args, **kwargs):
        raise ConnectionError("no server listening (test double)")


class _FakeProc:
    """Fake Popen handle: reports itself as already-exited (code 1) so the
    readiness loop takes the 'exited during start' edge path on the very
    first iteration instead of looping for real time."""

    def __init__(self, pid=4242):
        self.pid = pid

    def poll(self):
        return 1  # non-None == already exited


def _patch_common(monkeypatch):
    """Everything _ensure_vision_server_running touches besides argv build."""
    monkeypatch.setattr(vl, "_find_vision_model", lambda *a, **k: (FAKE_MODEL_PATH, FAKE_MMPROJ_PATH))
    monkeypatch.setattr(vl, "_find_llama_server_binary", lambda: FAKE_BINARY)
    # AC2 requires --n-gpu-layers come from the EXISTING _compute_vision_gpu_
    # layers — stub IT (not a second computation) so the test controls the
    # value and proves the spawn path calls through to it.
    monkeypatch.setattr(vl, "_compute_vision_gpu_layers", lambda *a, **k: FAKE_NGL)
    # T3 (specs/vision-browser-stage): netstat PID adoption is GONE —
    # `_resolve_listener_pid` was deleted with it, so its patch line is too.
    monkeypatch.setattr(vl, "_kill_pid", lambda pid: None)
    monkeypatch.setattr(vl, "_kill_process_tree", lambda pid: None)
    monkeypatch.setattr(vl, "_read_free_vram_gb", lambda: (7.4, True, True))
    monkeypatch.setattr(vl.time, "sleep", lambda seconds: None)
    # Progress-aware readiness: shrink the no-progress window so failure
    # paths resolve instantly instead of spinning the real 120s.
    monkeypatch.setenv("IRIS_VISION_READY_WINDOW_S", "1")
    # _ensure_vision_server_running does `import httpx` locally on every
    # call, so patching the real httpx module (not a `vl.httpx` attribute,
    # which does not exist at module scope) is what takes effect.
    import httpx as _httpx
    monkeypatch.setattr(_httpx, "get", _RaisingHttpxGet())


def test_spawn_cmd_has_fit_off_and_explicit_sizing(monkeypatch, tmp_path):
    """AC1/AC2: --fit off, --ctx-size, --n-gpu-layers, --batch-size are all
    passed explicitly instead of relying on llama.cpp's auto-fit."""
    _patch_common(monkeypatch)

    captured = {}

    def _fake_popen(args, **kwargs):
        captured["args"] = args
        return _FakeProc()

    monkeypatch.setattr(vl.subprocess, "Popen", _fake_popen)

    result = vl._ensure_vision_server_running()

    assert result is False  # fake proc "exits" immediately -> start fails
    assert "args" in captured, "subprocess.Popen was never called"

    full_argv = captured["args"]
    assert FAKE_BINARY in full_argv
    cmd = full_argv[full_argv.index(FAKE_BINARY):]  # strip the launcher prefix

    assert "--fit" in cmd
    assert cmd[cmd.index("--fit") + 1] == "off"

    assert "--ctx-size" in cmd
    assert cmd[cmd.index("--ctx-size") + 1] == str(vl._VISION_CTX_SIZE)

    assert "--n-gpu-layers" in cmd
    assert cmd[cmd.index("--n-gpu-layers") + 1] == str(FAKE_NGL)

    assert "--batch-size" in cmd
    assert cmd[cmd.index("--batch-size") + 1] == str(vl._VISION_BATCH_SIZE)

    # Old short-flag forms must be gone, not merely supplemented.
    assert "-c" not in cmd
    assert "-ngl" not in cmd


def test_spawn_cmd_ngl_comes_from_existing_estimator_not_recomputed(monkeypatch):
    """AC2 scope guard: the spawn path must call the EXISTING
    _compute_vision_gpu_layers exactly once and use ITS return value for
    --n-gpu-layers, never a second, independently-computed number."""
    _patch_common(monkeypatch)

    calls = []
    monkeypatch.setattr(
        vl,
        "_compute_vision_gpu_layers",
        lambda *a, **k: calls.append(a) or 77,
    )

    captured = {}

    def _fake_popen(args, **kwargs):
        captured["args"] = args
        return _FakeProc()

    monkeypatch.setattr(vl.subprocess, "Popen", _fake_popen)

    vl._ensure_vision_server_running()

    assert calls == [(FAKE_MODEL_PATH, FAKE_MMPROJ_PATH)]
    cmd = captured["args"]
    assert cmd[cmd.index("--n-gpu-layers") + 1] == "77"


def test_process_exit_during_start_surfaces_stderr_not_generic_timeout(monkeypatch, caplog):
    """Edge case: if the server process exits during start, the warning must
    name the exit and read the log tail, not report a bare timeout."""
    import logging

    _patch_common(monkeypatch)
    monkeypatch.setattr(vl, "_read_log_tail", lambda path, max_lines=20: "FATAL: bad --mmproj path")

    def _fake_popen(args, **kwargs):
        return _FakeProc()

    monkeypatch.setattr(vl.subprocess, "Popen", _fake_popen)

    with caplog.at_level(logging.WARNING, logger="backend.tools.lfm_vl_provider"):
        result = vl._ensure_vision_server_running()

    assert result is False
    warning_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "exited_during_start" in warning_text or "exited during start" in warning_text
    assert "FATAL: bad --mmproj path" in warning_text
    assert "did not become ready" not in warning_text




