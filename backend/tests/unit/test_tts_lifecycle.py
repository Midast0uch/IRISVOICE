"""Unit: TTS lifecycle (REQ-28) — lazy boot, connect prewarm, idle unload,
voice-state cache, post-synthesis compact.

Hermetic by construction: no worker subprocess is ever spawned (fake procs,
stubbed model, tmp files). The live backend + leak probe cover the real
worker; these pin the decision logic.
"""
from __future__ import annotations

import json
import types

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


def _fake_proc():
    proc = types.SimpleNamespace()
    proc.stdin_writes: list = []
    proc.wait_calls: list = []
    proc.killed = False

    class _In:
        def write(s, data):
            proc.stdin_writes.append(data)

        def flush(s):
            pass

        def close(s):
            pass

    class _Pipe:
        def close(s):
            pass

    proc.stdin, proc.stdout, proc.stderr = _In(), _Pipe(), _Pipe()
    proc.poll = lambda: None
    proc.wait = lambda timeout=None: proc.wait_calls.append(timeout)
    proc.kill = lambda: setattr(proc, "killed", True)
    return proc


# ── lazy boot + prewarm ──────────────────────────────────────────────

def test_no_worker_spawned_at_boot(_isolated_manager):
    assert _isolated_manager._proc is None
    assert _isolated_manager._ready is False


def test_reaper_thread_starts_once_per_process():
    import threading

    for _ in range(3):
        TTSManager._instance = None
        TTSManager._initialized = False
        TTSManager()
    TTSManager._instance = None
    TTSManager._initialized = False
    n = sum(1 for t in threading.enumerate() if t.name == "tts-idle-reaper")
    assert n == 1, f"expected exactly one reaper daemon, found {n}"


def test_prewarm_runs_once_and_never_raises(_isolated_manager, monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        _isolated_manager, "_load_pocket_tts",
        lambda: (calls.append(1), True),
    )
    _isolated_manager.prewarm()
    _isolated_manager.prewarm()
    assert _isolated_manager._connect_prewarm_done is True
    # Once-per-process: the loader ran exactly once despite two calls.
    import time as _t

    deadline = _t.monotonic() + 5
    while len(calls) < 1 and _t.monotonic() < deadline:
        _t.sleep(0.05)
    assert len(calls) == 1


# ── unload decision ──────────────────────────────────────────────────

def _live_manager(_isolated_manager, last_activity):
    _isolated_manager._proc = _fake_proc()
    _isolated_manager._ready = True
    _isolated_manager._last_activity = last_activity
    _isolated_manager._idle_timeout_s = 600.0
    return _isolated_manager


def test_unload_only_when_quiet_past_timeout(_isolated_manager):
    import time as _t

    m = _live_manager(_isolated_manager, _t.monotonic() - 900)
    assert m._should_unload(_t.monotonic()) is True
    m2 = _live_manager(_isolated_manager, _t.monotonic() - 10)
    assert m2._should_unload(_t.monotonic()) is False


def test_unload_disabled_by_nonpositive_timeout(_isolated_manager):
    import time as _t

    m = _live_manager(_isolated_manager, _t.monotonic() - 9999)
    m._idle_timeout_s = 0
    assert m._should_unload(_t.monotonic()) is False


def test_unload_skips_dead_or_never_active(_isolated_manager):
    import time as _t

    m = _live_manager(_isolated_manager, _t.monotonic() - 9999)
    m._ready = False
    assert m._should_unload(_t.monotonic()) is False
    m._ready = True
    m._last_activity = None
    assert m._should_unload(_t.monotonic()) is False


def test_reap_unloads_quiet_worker_gracefully(_isolated_manager):
    import time as _t

    m = _live_manager(_isolated_manager, _t.monotonic() - 900)
    proc = m._proc  # keep the handle: reap detaches it
    assert m._reap_if_idle() is True
    assert m._proc is None
    assert m._ready is False
    sent = [json.loads(w).get("action") for w in proc.stdin_writes]
    assert sent == ["shutdown"]


def test_reap_spares_active_synthesis(_isolated_manager):
    import time as _t

    m = _live_manager(_isolated_manager, _t.monotonic() - 900)
    proc = m._proc
    m._synthesis_lock.acquire()
    try:
        assert m._reap_if_idle() is False
    finally:
        m._synthesis_lock.release()
    assert m._proc is proc
    assert m._ready is True


def test_respawn_after_reap(_isolated_manager, monkeypatch):
    import time as _t

    m = _live_manager(_isolated_manager, _t.monotonic() - 900)
    assert m._reap_if_idle() is True
    spawns: list = []
    monkeypatch.setattr(
        m, "_spawn_worker", lambda: (spawns.append(1), setattr(m, "_ready", True))
    )
    assert m._ensure_worker() is True
    assert len(spawns) == 1


# ── worker voice cache + compact ─────────────────────────────────────

def test_voice_state_cache_avoids_recompute(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    import backend.audio.tts_worker as wmod

    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"fake-audio-bytes")
    monkeypatch.setattr(wmod, "REFERENCE_AUDIO", ref)
    monkeypatch.setattr(wmod, "_voice_name", "Cloned Voice")
    monkeypatch.setattr(
        wmod, "_PREDEFINED_VOICES", frozenset({"alba"}), raising=False
    )
    state = {"t": torch.zeros(4)}
    calls: list = []

    class _StubModel:
        has_voice_cloning = True

        def get_state_for_audio_prompt(self, path):
            calls.append(path)
            return dict(state)

    monkeypatch.setattr(wmod, "_model", _StubModel())
    monkeypatch.setattr(wmod, "_voice_state", None)
    monkeypatch.setattr(
        wmod, "_VOICE_CACHE_DIR", tmp_path / "cache", raising=False
    )

    wmod._load_voice_state()
    assert len(calls) == 1
    assert (tmp_path / "cache").glob("voice_state_*.pt")

    # Second load with a fresh stub must NOT recompute.
    calls.clear()
    monkeypatch.setattr(wmod, "_model", _StubModel())
    monkeypatch.setattr(wmod, "_voice_state", None)
    wmod._load_voice_state()
    assert calls == []
    assert set(wmod._voice_state) == set(state)
    assert torch.equal(wmod._voice_state["t"], state["t"])


def test_synthesize_compacts_heap_after_done(monkeypatch, capsys):
    import numpy as np

    import backend.audio.tts_worker as wmod

    class _T:
        def cpu(self):
            return self

        def numpy(self):
            return np.zeros(64, dtype=np.float32)

    class _StubModel:
        def generate_audio_stream(self, state, sentence, frames_after_eos=0):
            yield _T()

    monkeypatch.setattr(wmod, "_model", _StubModel())
    monkeypatch.setattr(wmod, "_voice_state", object())
    compacts: list = []
    monkeypatch.setattr(wmod, "_compact_heap", lambda: compacts.append(1))
    wmod._synthesize("hi", req_id=7)
    out = capsys.readouterr().out
    assert '"type": "done"' in out
    assert len(compacts) == 1


# ── long-text request splitting ──────────────────────────────────────

def _chunk_msg(n=8):
    import base64

    import numpy as np

    return {"type": "chunk",
            "data": base64.b64encode(np.zeros(n, dtype=np.float32).tobytes()).decode()}


def _scripted_manager(_isolated_manager, monkeypatch, script):
    """Drive synthesize_stream against canned worker replies.

    script: list of reply-lists, one per expected synthesize action;
    each reply-list is drained (chunk… then done) before the next action.
    """
    import json as _json

    sent: list = []
    pending = [list(replies) for replies in script]

    monkeypatch.setattr(_isolated_manager, "_ensure_worker", lambda: True)

    def _send(payload):
        sent.append(_json.loads(_json.dumps(payload)))

    def _read_line(timeout=30.0):
        assert pending, "worker spoke with no scripted action left"
        if not pending[0]:
            pending.pop(0)
            assert pending, "worker spoke with no scripted action left"
        if not pending[0]:
            raise AssertionError("empty scripted reply-list")
        msg = pending[0].pop(0)
        if not pending[0]:
            pending.pop(0)
        if isinstance(msg, dict) and msg.get("type") == "chunk":
            return dict(msg, id=0)
        if isinstance(msg, dict) and msg.get("type") == "done":
            return dict(msg, id=0, total_samples=8, duration_s=0.1)
        return msg

    monkeypatch.setattr(_isolated_manager, "_send", _send)
    monkeypatch.setattr(_isolated_manager, "_read_line", _read_line)
    return sent


def test_long_text_splits_into_bounded_sequential_requests(
    _isolated_manager, monkeypatch,
):
    text = " ".join(f"Sentence number {i} ends here." for i in range(90))
    assert len(text) > 2000
    sent = _scripted_manager(
        _isolated_manager, monkeypatch,
        [[_chunk_msg(), {"type": "done"}], [_chunk_msg(), {"type": "done"}]],
    )
    chunks = list(_isolated_manager.synthesize_stream(text))
    actions = [p.get("action") for p in sent]
    assert actions == ["synthesize", "synthesize"]
    assert all(len(p.get("text", "")) <= 2000 for p in sent)
    assert len(chunks) == 2  # one chunk per piece, same audio end to end


def test_short_text_sends_exactly_one_request(_isolated_manager, monkeypatch):
    sent = _scripted_manager(
        _isolated_manager, monkeypatch, [[_chunk_msg(), {"type": "done"}]]
    )
    chunks = list(_isolated_manager.synthesize_stream("Hello world"))
    assert [p.get("action") for p in sent] == ["synthesize"]
    assert sent[0].get("text") == "Hello world"
    assert len(chunks) == 1


def test_splitter_caps_punctuation_free_runs():
    from backend.agent.tts import TTSManager

    pieces = TTSManager._split_synthesis_text("x" * 2500)
    assert len(pieces) == 2
    assert all(len(p) <= 2000 for p in pieces)
    assert "".join(pieces) == "x" * 2500
