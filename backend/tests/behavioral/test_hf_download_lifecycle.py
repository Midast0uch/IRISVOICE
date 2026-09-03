"""Behavioral — cli-workspace-unification T12 (REQ-9 AC7/AC8).

Drives the FULL HF download lifecycle through the real worker
(`backend.main._hf_download_job`) with only the network layer mocked,
asserting EMERGENT properties of the design's error-handling contract:

  - success   -> atomic promote (.part renamed), auto-rescan fired
  - cancel    -> partial REMOVED, never left for a later scan to offer
  - failure   -> partial REMOVED, error surfaced in the job row

The WS broadcast layer is captured (never hits a real socket). No live web.
"""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

import backend.main as main_mod


PAYLOAD = b"GGUF" * (1 << 18)  # 1 MiB of fake weight bytes


class _FakeStreamResp:
    status_code = 200
    headers = {"content-length": str(len(PAYLOAD))}

    def __init__(self, chunks, fail_after=None):
        self._chunks = chunks
        self._fail_after = fail_after
        self._n = 0

    async def aiter_bytes(self, size):
        for c in self._chunks:
            if self._fail_after is not None and self._n >= self._fail_after:
                raise ConnectionError("disk full / network dropped")
            self._n += 1
            yield c


class _StreamCtx:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *a):
        return False


class _FakeClient:
    instances = []

    def __init__(self, *a, **kw):
        self._resp = None
        _FakeClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, headers=None):
        return _StreamCtx(self._resp)


class _CapturingWS:
    def __init__(self):
        self.frames = []

    async def broadcast(self, message):
        self.frames.append(message)


@pytest.fixture()
def hf_env(tmp_path, monkeypatch):
    """Tmp models dir + captured WS + injectable stream response."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    ws = _CapturingWS()

    class _FakeMgr:
        effective_models_dir = models_dir
        scanned = 0

        def scan_models(self):
            type(self).scanned += 1
            return []

    monkeypatch.setattr("backend.ws_manager.get_websocket_manager", lambda: ws)
    monkeypatch.setattr(
        "backend.agent.local_model_manager.get_local_model_manager", lambda: _FakeMgr()
    )
    return {
        "models_dir": models_dir,
        "ws": ws,
        "mgr_cls": _FakeMgr,
        "set_response": lambda resp: setattr(_FakeClient, "_next_resp", resp),
    }


def _install_client(monkeypatch):
    """Patch httpx.AsyncClient so each new client gets the queued response."""
    def factory(*a, **kw):
        c = _FakeClient(*a, **kw)
        c._resp = getattr(_FakeClient, "_next_resp", None)
        return c

    monkeypatch.setattr("httpx.AsyncClient", factory)


def test_success_promotes_atomically_and_rescans(hf_env, monkeypatch):
    _install_client(monkeypatch)
    half = len(PAYLOAD) // 2
    hf_env["set_response"](_FakeStreamResp([PAYLOAD[:half], PAYLOAD[half:]]))

    dest = hf_env["models_dir"] / "model.Q4_K_M.gguf"
    job = {"status": "queued", "cancel": False}
    asyncio.run(main_mod._hf_download_job("j1", "org/repo", "model.Q4_K_M.gguf", dest, job))

    assert job["status"] == "done"
    assert dest.read_bytes() == PAYLOAD              # full weight under its REAL name
    assert not list(hf_env["models_dir"].glob("*.part"))  # no temp residue
    assert hf_env["mgr_cls"].scanned == 1            # REQ-9 AC8: auto-rescan fired
    assert any(f.get("pct") == 100.0 for f in hf_env["ws"].frames)


def test_cancel_removes_partial_file(hf_env, monkeypatch):
    _install_client(monkeypatch)
    half = len(PAYLOAD) // 2

    original_aiter = None

    # A stream that flips the cancel flag after the first chunk — simulates
    # the user pressing Cancel mid-download.
    class _CancellingResp(_FakeStreamResp):
        async def aiter_bytes(self, size):
            it = iter(self._chunks)
            yield next(it)
            parent_job["cancel"] = True
            for c in it:
                yield c

    parent_job = {"status": "queued", "cancel": False}
    hf_env["set_response"](_CancellingResp([PAYLOAD[:half], PAYLOAD[half:]]))

    dest = hf_env["models_dir"] / "cancelled.gguf"
    asyncio.run(main_mod._hf_download_job("j2", "org/repo", "cancelled.gguf", dest, parent_job))

    assert parent_job["status"] == "cancelled"
    assert not dest.exists(), "partial must never survive under its real name"
    assert not list(hf_env["models_dir"].glob("*.part")), "partial .part must be deleted"
    assert any(f.get("cancelled") for f in hf_env["ws"].frames)


def test_failure_removes_partial_and_surfaces_error(hf_env, monkeypatch):
    _install_client(monkeypatch)
    quarter = len(PAYLOAD) // 4
    hf_env["set_response"](_FakeStreamResp([PAYLOAD[:quarter], PAYLOAD[quarter:]], fail_after=1))

    dest = hf_env["models_dir"] / "doomed.gguf"
    job = {"status": "queued", "cancel": False}
    asyncio.run(main_mod._hf_download_job("j3", "org/repo", "doomed.gguf", dest, job))

    assert job["status"] == "failed"
    assert "disk full" in job["error"]
    assert not dest.exists()
    assert not list(hf_env["models_dir"].glob("*.part"))
    assert any(f.get("error") for f in hf_env["ws"].frames)


def test_http_error_status_fails_cleanly(hf_env, monkeypatch):
    _install_client(monkeypatch)

    class _NotFound(_FakeStreamResp):
        status_code = 404
        headers = {}

    hf_env["set_response"](_NotFound([]))
    dest = hf_env["models_dir"] / "missing.gguf"
    job = {"status": "queued", "cancel": False}
    asyncio.run(main_mod._hf_download_job("j4", "org/repo", "missing.gguf", dest, job))

    assert job["status"] == "failed"
    assert "404" in job["error"]
    assert not dest.exists()
