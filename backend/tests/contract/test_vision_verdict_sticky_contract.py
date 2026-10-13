"""Contract tests for vision verdict stickiness (2026-10-13, live g04).

A POSITIVE capability verdict (a proven multimodal server) no longer expires on
the TTL; only a NEGATIVE verdict expires. A failed vision call drops the proven
verdict of the reused server. Reason: re-proving a positive verdict every 300 s
sent a 1x1-PNG probe to the shared one-slot d1 server inside a turn; it held the
slot 13.6 s and the node's Oracle tool_choice decision waited 9.8 s.

No network, no model load. httpx is faked; every module global is monkeypatched.

Cases:
  S1. a proven server is NOT probed again after the TTL (positive sticks)
  S2. a negative (None) verdict still expires after the TTL
  S3. a failed vision call drops the proven verdict and the reuse selection
"""

from __future__ import annotations

import time

import httpx
import pytest

import backend.tools.vision_provider as vl


class _Resp:
    def __init__(self, status_code: int = 200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}

    def json(self):
        return self._json


class _Server:
    """Fake OpenAI-compatible server. `sees` = model ids that really see the
    image; every other model answers 200 + "ok" (drops the image)."""

    def __init__(self, models, sees=()):
        self.models = models
        self.sees = set(sees)
        self.posted: list = []

    def get(self, url, timeout=1.0, headers=None):
        if url.endswith("/models"):
            return _Resp(200, {"data": [{"id": m} for m in self.models]})
        return _Resp(200)

    def post(self, url, json=None, timeout=1.0, headers=None):
        model = (json or {}).get("model")
        self.posted.append(model)
        text = "red, blue" if model in self.sees else "ok"
        return _Resp(200, {"choices": [{"message": {"content": text}}]})


_URL = "http://127.0.0.1:8082/v1"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(vl, "_reused_vision_base_url", None)
    monkeypatch.setattr(vl, "_reused_vision_auth", None)
    monkeypatch.setattr(vl, "_reused_vision_model", None)
    monkeypatch.setattr(vl, "_VISION_CAPABILITY_CACHE", {})
    monkeypatch.setattr(vl, "_EXTRA_VISION_ENDPOINTS", [])
    monkeypatch.setattr(vl, "_VISION_AUTOLOAD_ENABLED", False)
    monkeypatch.setattr(vl, "_lifecycle_callback", None)


def _install(monkeypatch, server):
    monkeypatch.setattr(httpx, "get", server.get)
    monkeypatch.setattr(httpx, "post", server.post)


# ── S1: a proven server keeps its verdict past the TTL ──────────────────────


def test_a_proven_server_is_not_probed_again_after_the_ttl(monkeypatch):
    server = _Server(["m"], sees={"m"})
    _install(monkeypatch, server)
    assert vl._is_verified_vision_capable(_URL) == "m"
    assert server.posted == ["m"]
    monkeypatch.setattr(vl, "_CAPABILITY_TTL_S", 0.0)
    assert vl._is_verified_vision_capable(_URL) == "m"
    assert server.posted == ["m"]  # no second image sent to the shared server


# ── S2: a negative verdict still expires ────────────────────────────────────


def test_a_negative_verdict_still_expires(monkeypatch):
    server = _Server(["m"])
    _install(monkeypatch, server)
    assert vl._is_verified_vision_capable(_URL) is None
    assert server.posted == ["m"]
    monkeypatch.setattr(vl, "_CAPABILITY_TTL_S", 0.0)
    server.sees.add("m")  # the server loaded a projector meanwhile
    assert vl._is_verified_vision_capable(_URL) == "m"
    assert server.posted == ["m", "m"]  # the negative verdict was re-probed


# ── S3: a failed vision call drops the proven verdict ───────────────────────


def test_a_failed_vision_call_drops_the_verdict(monkeypatch):
    monkeypatch.setattr(vl, "_reused_vision_base_url", _URL)
    monkeypatch.setattr(vl, "_reused_vision_model", "m")
    monkeypatch.setattr(vl, "_VISION_CAPABILITY_CACHE", {(_URL, ""): ("m", time.monotonic())})
    # The reused server answers /models (fast path keeps it), but the vision POST fails.
    monkeypatch.setattr(httpx, "get", lambda url, timeout=1.0, headers=None: _Resp(200))

    def _refuse(url, json=None, timeout=1.0, headers=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _refuse)

    out = vl.LFMVLProvider()._call(b"\x89PNG\r\n\x1a\n", "q")

    assert out.startswith("Vision unavailable"), out
    assert all(k[0] != _URL for k in vl._VISION_CAPABILITY_CACHE)
    assert vl._reused_vision_base_url is None
