"""Integration tests: vision-server discovery against a REAL configured provider.

These exercise the production code path that reads candidates from
``iris_config.load_config().inference.providers`` (NOT the unit-test shortcut of
registering endpoints directly), so they prove the discovery wiring the user
asked for actually fires off the persisted config.

Scenario A (primary, per user direction): Cohere is configured as an API provider
with a key. Cohere is TEXT-ONLY, so the multimodal probe must REJECT it and the
provider must fall through to spawning the local LFM VLM 3B — fast and seamless
(no 6-minute wait; the real subprocess launch is intercepted). The spawn emits the
REQ-5 lifecycle "spawning" label that the browser overlay renders.

Scenario B (complement): a configured LOCAL_OPENAI provider that IS multimodal is
reused instead of spawning — proving the config-sourced path drives reuse too.

No GPU, no real model load, no real network. subprocess.Popen and httpx are
monkeypatched; the spawn argv (model) and lifecycle events are captured.
"""

from __future__ import annotations

import subprocess
import types

import httpx
import pytest

import backend.iris_config as iris_config_mod
import backend.tools.lfm_vl_provider as vl


# ---------------------------------------------------------------------------
# Fake httpx
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data: dict | None = None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("fake", request=None, response=self)


class _FakeHttpx:
    """Answers per endpoint kind. The IRIS-owned port (18181) is down on its
    FIRST GET (so the fast path fails and discovery is exercised) and up on
    later GETs (so the readiness poll succeeds quickly)."""

    def __init__(self, multimodal_endpoints: set[str], textonly_endpoints: set[str]):
        self.multimodal_endpoints = multimodal_endpoints
        self.textonly_endpoints = textonly_endpoints
        self.owned_get_count = 0
        self.get_calls: list[str] = []
        self.post_calls: list[str] = []

    def _kind(self, url: str) -> str | None:
        for e in self.multimodal_endpoints:
            if e in url:
                return "multimodal"
        for e in self.textonly_endpoints:
            if e in url:
                return "textonly"
        return None

    def get(self, url: str, timeout: float = 1.0, headers=None) -> _FakeResponse:
        self.get_calls.append(url)
        if "18181" in url:
            self.owned_get_count += 1
            if self.owned_get_count == 1:
                raise ConnectionError("owned port down (fast path)")
            return _FakeResponse(200, {"data": [{"id": "vision-model"}]})
        _kind = self._kind(url)
        if _kind == "multimodal":
            return _FakeResponse(200, {"data": [{"id": "vision-model"}]})
        if _kind == "textonly":
            return _FakeResponse(200, {"data": [{"id": "text-model"}]})
        raise ConnectionError(f"unexpected GET {url}")

    def post(self, url: str, json=None, timeout: float = 1.0, headers=None) -> _FakeResponse:
        self.post_calls.append(url)
        _kind = self._kind(url)
        if _kind == "multimodal":
            return _FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})
        if _kind == "textonly":
            return _FakeResponse(200, {"error": {"message": "image_url not supported"}})
        raise ConnectionError(f"unexpected POST {url}")


# ---------------------------------------------------------------------------
# Fake subprocess.Popen — captures the spawn argv, returns an alive fake proc
# ---------------------------------------------------------------------------


class _FakePopen:
    def __init__(self, argv, **_kw):
        self.argv = list(argv)
        self.pid = 99999
        _FakePopen.spawned.append(self.argv)

    spawned: list[list[str]] = []

    def poll(self):
        return None  # alive -> readiness poll proceeds


# ---------------------------------------------------------------------------
# Config builders
# ---------------------------------------------------------------------------


def _cohere_provider() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id="cohere",
        label="Cohere",
        kind="API",
        model="command-r-plus",
        purpose="chat",
        endpoint="https://api.cohere.com/v1",
        cred_ref="cohere-test-key",
        model_path="",
    )


def _local_vision_provider(endpoint: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id="local-vision",
        label="Local Vision",
        kind="LOCAL_OPENAI",
        model="",
        purpose="chat",
        endpoint=endpoint,
        cred_ref="",
        model_path="",
    )


def _fake_config_with(*providers: types.SimpleNamespace):
    _inference = types.SimpleNamespace(providers={p.id: p for p in providers})
    return types.SimpleNamespace(inference=_inference)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def integration_harness(monkeypatch):
    # Reset discovery / spawn / lifecycle state.
    monkeypatch.setattr(vl, "_VISION_SERVER_PID", None)
    monkeypatch.setattr(vl, "_spawn_attempt", None)
    monkeypatch.setattr(vl, "_reused_vision_base_url", None)
    monkeypatch.setattr(vl, "_reused_vision_auth", None)
    monkeypatch.setattr(vl, "_reused_vision_model", None)
    monkeypatch.setattr(vl, "_VISION_CAPABILITY_CACHE", {})
    monkeypatch.setattr(vl, "_lifecycle_callback", None)

    # Stub the heavy / blocking parts of the real spawn so the test is fast and
    # hermetic, while the REAL spawn argv construction and lifecycle emission run.
    monkeypatch.setattr(vl, "_find_llama_server_binary", lambda: "/fake/llama-server.exe")
    monkeypatch.setattr(
        vl,
        "_find_vision_model",
        lambda vram_state=None: (
            "/fake/models/lfm2.5-vl-3b.gguf",
            "/fake/models/mmproj.gguf",
        ),
    )
    monkeypatch.setattr(vl, "_read_free_vram_gb", lambda: (8.0, True, False))
    monkeypatch.setattr(vl, "_compute_vision_gpu_layers", lambda *a, **k: 0)
    monkeypatch.setattr(vl, "_estimate_vision_footprint_gb", lambda *a, **k: 1.0)
    monkeypatch.setattr(vl, "_probe_av_latency", lambda *a, **k: 0.0)
    monkeypatch.setattr(vl, "_proc_cpu_seconds", lambda *a, **k: 0.0)

    _FakePopen.spawned = []
    monkeypatch.setattr(subprocess, "Popen", _FakePopen)

    captured: list[tuple] = []

    def _capture(state=None, reason=None, trigger=None):
        captured.append((state, reason, trigger))

    vl.set_vision_lifecycle_callback(_capture)

    yield captured


# ---------------------------------------------------------------------------
# Scenario A — Cohere (text-only) configured -> local LFM VLM 3B spawns
# ---------------------------------------------------------------------------


class TestCohereConfiguredFallsThroughToLocalSpawn:
    def test_cohere_text_only_rejected_then_local_vlm_spawns_with_label(
        self, monkeypatch, integration_harness
    ):
        captured = integration_harness
        # Real config path: Cohere is a configured API provider with a key.
        monkeypatch.setattr(
            iris_config_mod,
            "load_config",
            lambda: _fake_config_with(_cohere_provider()),
        )
        fake = _FakeHttpx(multimodal_endpoints=set(), textonly_endpoints={"api.cohere.com"})
        monkeypatch.setattr(httpx, "get", fake.get)
        monkeypatch.setattr(httpx, "post", fake.post)

        # Exercise the full production flow.
        result = vl._ensure_vision_server_running("")

        # 1. Discovery actually probed the configured Cohere provider (real config path).
        assert any("api.cohere.com/v1/chat/completions" in c for c in fake.post_calls), (
            "discovery never probed the configured Cohere provider"
        )
        # 2. Cohere is text-only -> NOT reused (no borrowed selection).
        assert vl._reused_vision_base_url is None
        # 3. The local LFM VLM 3B was spawned (owned PID set, spawn argv captured).
        assert result is True
        assert vl._VISION_SERVER_PID is not None
        assert _FakePopen.spawned, "no local llama-server spawn occurred"
        _argv = _FakePopen.spawned[0]
        assert "-m" in _argv
        _model_idx = _argv.index("-m") + 1
        assert "lfm2.5-vl-3b.gguf" in _argv[_model_idx], (
            f"local spawn did not use the LFM VLM 3B model: {_argv[_model_idx]}"
        )
        # 4. The REQ-5 lifecycle "spawning" label was emitted for the browser overlay.
        _states = [s for (s, _, _) in captured]
        assert "spawning" in _states, f"no 'spawning' lifecycle label emitted: {_states}"
        assert "warm" in _states, f"spawn never reached 'warm': {_states}"


# ---------------------------------------------------------------------------
# Scenario B — configured multimodal provider IS reused (no local spawn)
# ---------------------------------------------------------------------------


class TestConfiguredMultimodalProviderReused:
    def test_local_openai_multimodal_provider_reused_without_spawn(
        self, monkeypatch, integration_harness
    ):
        captured = integration_harness
        monkeypatch.setattr(
            iris_config_mod,
            "load_config",
            lambda: _fake_config_with(_local_vision_provider("http://localhost:9999/v1")),
        )
        fake = _FakeHttpx(multimodal_endpoints={"localhost:9999"}, textonly_endpoints=set())
        monkeypatch.setattr(httpx, "get", fake.get)
        monkeypatch.setattr(httpx, "post", fake.post)

        result = vl._ensure_vision_server_running("")

        # Reused: no local spawn, no owned PID, borrowed endpoint selected.
        assert result is True
        assert _FakePopen.spawned == [], "a local spawn happened when reuse should occur"
        assert vl._VISION_SERVER_PID is None
        assert vl._reused_vision_base_url == "http://localhost:9999/v1"
        # Discovery probed the configured provider.
        assert any("localhost:9999/v1/chat/completions" in c for c in fake.post_calls)
