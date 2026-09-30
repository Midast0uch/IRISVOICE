"""Standards for startup readiness and background disk load (2026-09-30).

  S7  TTS is ready with the backend: while the worker loads, /health answers
      503 (status "starting") so no turn starts during the load; a FAILED
      load answers 200 with tts.status "error" (never waited on forever).
      Measured: a lazy load landed inside coding eval c11 (model load 61.5 s,
      pytest ~2 s -> ~110 s, zero audio); after: 0 startup timeouts in turns,
      c11 reply 213.6 s -> 116.8 s.
  S8  the git-status poll never runs back to back on a slow repo: its cache
      lifetime scales with the last run's cost (x GIT_STATUS_COST_FACTOR).
      Measured: every run hit the 5 s timeout and re-ran 5 s later, holding
      the C: hard disk for the whole time.
  S10 the Oracle model hash is read from a cache on a repeat start: load()
      read the 642 MB model twice (ORT session + sha256). Measured: ~16 s of
      _hash_model_file frames at startup on the C: hard disk, competing with
      the TTS worker load; after: 0 frames, same digest, start -> first Oracle
      decide 23-70 s -> 5.3 s (one run, model file warm).

The concurrent-spawn hang (every TTS caller silent for up to 300 s) is pinned
by test_tts_memory_envelope_behavior.py::test_concurrent_first_speak_spawns_exactly_one_worker.
"""
from __future__ import annotations

import asyncio
import json
import time
import types

import pytest

from backend.agent.tts import TTSManager


@pytest.fixture()
def fresh_tts():
    TTSManager._instance = None
    TTSManager._initialized = False
    mgr = TTSManager()
    yield mgr
    TTSManager._instance = None
    TTSManager._initialized = False


def _alive_proc():
    return types.SimpleNamespace(poll=lambda: None)


def test_s7_readiness_states(fresh_tts):
    m = fresh_tts
    assert m.readiness()["status"] == "not_started"
    m._connect_prewarm_done = True          # boot load requested, not spawned yet
    assert m.readiness()["status"] == "loading"
    m._proc = _alive_proc()                 # worker alive, no "ready" line yet
    assert m.readiness()["status"] == "loading"
    m._ready = True
    assert m.readiness()["status"] == "ready"
    m._proc, m._ready, m._load_error = None, False, "worker exited during startup"
    assert m.readiness() == {"status": "error", "error": "worker exited during startup"}
    m.config["tts_enabled"] = False
    assert m.readiness()["status"] == "disabled"


def test_s7_health_is_503_while_tts_loads_and_200_after(fresh_tts, monkeypatch):
    import backend.main as main_mod

    monkeypatch.setattr(main_mod, "get_tts_manager", lambda: fresh_tts)
    fresh_tts._connect_prewarm_done = True
    fresh_tts._proc = _alive_proc()

    loading = asyncio.run(main_mod.health_check())
    assert getattr(loading, "status_code", 200) == 503, (
        "/health must not report ready while TTS loads — a turn would start "
        "during the load (c11 2026-09-29)"
    )
    body = json.loads(loading.body)
    assert body["status"] == "starting" and body["tts"]["status"] == "loading"

    fresh_tts._ready = True
    ready = asyncio.run(main_mod.health_check())
    assert isinstance(ready, dict) and ready["tts"]["status"] == "ready"

    fresh_tts._proc, fresh_tts._ready = None, False
    fresh_tts._load_error = "worker exited during startup"
    failed = asyncio.run(main_mod.health_check())
    assert isinstance(failed, dict), "a failed TTS load must not hold /health at 503"
    assert failed["tts"]["status"] == "error"


def test_s8_git_status_cache_scales_with_cost(monkeypatch):
    import backend.api.status_snapshot as s

    calls: list = []

    def _run():
        calls.append(1)
        return {"status": [], "log": [], "dirty": False}

    monkeypatch.setattr(s, "get_git_status", _run)
    monkeypatch.setattr(
        s, "_git_status_cache", {"ts": 0.0, "value": None, "cost": 0.0}
    )
    s._cached_git_status()
    assert len(calls) == 1
    # A run that cost the full 5 s timeout: 6 s later it must NOT run again.
    s._git_status_cache["cost"] = 5.0
    s._git_status_cache["ts"] = time.monotonic() - 6
    s._cached_git_status()
    assert len(calls) == 1, (
        "git status re-ran 6 s after a 5 s run — on this repo that holds the "
        "hard disk back to back"
    )
    s._git_status_cache["ts"] = time.monotonic() - (5.0 * s.GIT_STATUS_COST_FACTOR + 1)
    s._cached_git_status()
    assert len(calls) == 2


def test_s10_oracle_model_hash_hit_reads_no_model_bytes(tmp_path, monkeypatch):
    """S10: a repeat start with an unchanged model file returns the cached
    digest without reading the file; a changed file is hashed again."""
    import builtins
    import hashlib
    import os

    import backend.agent.decision_backend_onnx as onnx_mod

    monkeypatch.setattr(
        onnx_mod, "_HASH_CACHE_PATH", tmp_path / "hash.json", raising=False
    )
    model = tmp_path / "model_int8.onnx"
    model.write_bytes(b"weights" * 4096)
    digest = hashlib.sha256(model.read_bytes()).hexdigest()

    assert onnx_mod.GlinerOnnx._hash_model_file(str(model)) == digest

    reads = []
    real_open = builtins.open

    def _spy(path, *a, **k):
        reads.append(os.path.abspath(str(path)))
        return real_open(path, *a, **k)

    monkeypatch.setattr(builtins, "open", _spy)
    assert onnx_mod.GlinerOnnx._hash_model_file(str(model)) == digest
    assert os.path.abspath(str(model)) not in reads, (
        "S10: an unchanged model file was read again to hash it"
    )

    monkeypatch.setattr(builtins, "open", real_open)
    model.write_bytes(b"swapped" * 4096)
    st = os.stat(model)
    os.utime(model, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    assert onnx_mod.GlinerOnnx._hash_model_file(str(model)) == (
        hashlib.sha256(model.read_bytes()).hexdigest()
    ), "S10: a changed model file kept the stale cached digest"
