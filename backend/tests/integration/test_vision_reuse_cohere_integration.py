"""Integration tests: vision-server discovery against a REAL configured provider.

specs/vision-single-server (2026-09-18): the local spawning scenario was
deleted with the spawn path. What remains to be proven end to end through the
REAL config path (iris_config providers, not registered endpoints):

  A. a configured provider that is TEXT-ONLY is rejected: it is not reused,
     nothing spawns, and ``_ensure_vision_server_running`` returns False with
     the lifecycle "error" announced.
  B. a configured LOCAL_OPENAI provider that IS multimodal IS reused — the
     selection lands and vision traffic routes there.

No GPU, no real model load, no real network; httpx is faked.
"""

from __future__ import annotations

import types

import httpx
import pytest

import backend.iris_config as iris_config_mod
import backend.tools.lfm_vl_provider as vl


def _seen_answer(payload) -> str:
    """What a model that SEES answers: the probe image's two colours for the
    capability probe (V3 - "200 with choices" is no longer proof), "ok" for
    any other vision request."""
    return "red, blue" if vl._PROBE_PROMPT in str(payload) else "ok"


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
    def __init__(self, multimodal_endpoints: set[str], textonly_endpoints: set[str]):
        self.multimodal_endpoints = multimodal_endpoints
        self.textonly_endpoints = textonly_endpoints
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
            return _FakeResponse(200, {"choices": [{"message": {"content": _seen_answer(json)}}]})
        if _kind == "textonly":
            return _FakeResponse(200, {"error": {"message": "image_url not supported"}})
        raise ConnectionError(f"unexpected POST {url}")


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


@pytest.fixture
def integration_harness(monkeypatch):
    monkeypatch.setattr(vl, "_reused_vision_base_url", None)
    monkeypatch.setattr(vl, "_reused_vision_auth", None)
    monkeypatch.setattr(vl, "_reused_vision_model", None)
    monkeypatch.setattr(vl, "_VISION_CAPABILITY_CACHE", {})
    monkeypatch.setattr(vl, "_lifecycle_callback", None)
    # The lifecycle debounce is module state too: an "error" emitted by an
    # earlier test < 1 s ago made this test's own "error" a dropped duplicate
    # (it passed alone, failed after test_vision_autoload_contract).
    monkeypatch.setattr(vl, "_last_lifecycle", ("", 0.0))
    monkeypatch.setattr(vl, "_load_candidate_endpoints_from_config",
                        vl._load_candidate_endpoints_from_config)
    monkeypatch.setattr(vl, "_EXTRA_VISION_ENDPOINTS", [])
    # P3 (session-342): this machine carries the owner's real pinned vision
    # model, so without this isolation a fake "nothing multimodal" world would
    # qualify for a REAL model load. Hermetic stub, same class as the
    # borrowed-state resets above; no assertion in this file changes.
    monkeypatch.setattr(vl, "_VISION_AUTOLOAD_ENABLED", False)
    captured: list[tuple] = []

    def _capture(state=None, reason=None, trigger=None):
        captured.append((state, reason, trigger))

    vl.set_vision_lifecycle_callback(_capture)
    yield captured


def test_textonly_configured_provider_rejected_nothing_spawned_definitely_unavailable(
    monkeypatch, integration_harness
):
    captured = integration_harness
    monkeypatch.setattr(
        iris_config_mod, "load_config", lambda: _fake_config_with(_cohere_provider())
    )
    fake = _FakeHttpx(multimodal_endpoints=set(), textonly_endpoints={"api.cohere.com"})
    monkeypatch.setattr(httpx, "get", fake.get)
    monkeypatch.setattr(httpx, "post", fake.post)

    # 1. The real config path is exercised: discovery probed Cohere for real.
    result = vl._ensure_vision_server_running("")
    assert any("api.cohere.com/v1/chat/completions" in c for c in fake.post_calls)
    # 2. Text-only -> NOT reused.
    assert vl._reused_vision_base_url is None
    # 3. Nothing to borrow -> unavailable, loudly.
    assert result is False
    states = [s for (s, _, _) in captured]
    assert "error" in states, states
    # 4. Structural: the deleted spawn path cannot come back silently.
    assert getattr(vl, "_spawn_vision_server_now", None) is None


def test_configured_multimodal_provider_reused(monkeypatch, integration_harness):
    captured = integration_harness
    monkeypatch.setattr(
        iris_config_mod, "load_config",
        lambda: _fake_config_with(_local_vision_provider("http://localhost:9999/v1")),
    )
    fake = _FakeHttpx(multimodal_endpoints={"localhost:9999"}, textonly_endpoints=set())
    monkeypatch.setattr(httpx, "get", fake.get)
    monkeypatch.setattr(httpx, "post", fake.post)

    result = vl._ensure_vision_server_running("")

    assert result is True
    assert vl._reused_vision_base_url == "http://localhost:9999/v1"
    assert any("localhost:9999/v1/chat/completions" in c for c in fake.post_calls)
    states = [s for (s, _, _) in captured]
    assert "warm" in states
