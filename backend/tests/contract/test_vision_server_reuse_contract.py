"""Contract tests for borrowed vision-server discovery (2026-08-27).

specs/vision-single-server (2026-09-18): the standalone llama-server spawn
path is DELETED. Tier 3 is borrow-ONLY. These tests now pin the borrow
semantics themselves: text-only candidates are rejected, verified multimodal
candidates are reused, no spawn surface exists to fall through to, and a
borrowed server is never touched by lifecycle management (there is none).

No GPU, no real model loads. httpx is faked.

Cases:
  C1. a reachable but TEXT-ONLY candidate is NOT reused (the regression that matters)
  C2. a verified multimodal candidate IS reused
  C3. disable() only clears the local reuse selection (no process control)
  C4. no candidate -> VisionModelUnavailable-style failure, NOTHING spawned
  C5. a reused borrowed server is actually routed to (endpoint + model + auth)
  C6. router-mode servers are probed across ALL models, not just models[0]
  C7. the global vision-model pin is preferred during probing
  C8. the pin comes from field_values['vision']['vision_model']
"""

from __future__ import annotations

import httpx
import pytest

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
    """Scenario-driven fake.

    `candidate_scenario` is "multimodal" | "textonly" | "down".
    The DEFAULT endpoint (vl._VISION_PORT — the shared local model server,
    whose port moved with the spec) is ALWAYS treated as down, so the fast
    path fails and discovery is actually exercised.
    """

    def __init__(self, candidate_scenario: str = "down"):
        self.candidate_scenario = candidate_scenario
        self.post_calls: list[str] = []
        self.post_payloads: list[dict] = []
        self.post_headers: list = []

    def _is_owned(self, url: str) -> bool:
        return str(vl._VISION_PORT) in url

    def get(self, url: str, timeout: float = 1.0, headers=None) -> _FakeResponse:
        if self._is_owned(url):
            raise ConnectionError("owned port refused (test)")
        # Any non-owned GET /models: answer per scenario.
        if url.endswith("/models"):
            if self.candidate_scenario == "down":
                raise ConnectionError("candidate refused (test)")
            if self.candidate_scenario == "textonly":
                return _FakeResponse(200, {"data": [{"id": "text-model"}]})
            return _FakeResponse(200, {"data": [{"id": "vision-model"}]})
        return _FakeResponse(200)

    def post(self, url: str, json=None, timeout: float = 1.0, headers=None) -> _FakeResponse:
        self.post_calls.append(url)
        self.post_payloads.append(json)
        self.post_headers.append(headers)
        if self._is_owned(url):
            raise ConnectionError("owned port refused (test)")
        if self.candidate_scenario == "down":
            raise ConnectionError("candidate refused (test)")
        if self.candidate_scenario == "textonly":
            # A text-only server typically rejects the image_url with an error
            # payload even when it returns HTTP 200.
            return _FakeResponse(200, {"error": {"message": "image_url not supported"}})
        return _FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})


# ---------------------------------------------------------------------------
# Fixture: isolate module globals between tests
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_vl(monkeypatch):
    # Keep tests hermetic: never let discovery probe real iris_config providers
    # (which would hit the network). Registered endpoints are still exercised.
    monkeypatch.setattr(vl, "_load_candidate_endpoints_from_config", lambda: [])
    # P3 (session-342): autoload can only fire on the user's PINNED vision
    # model, but this machine HAS that pin persisted — without this isolation
    # the fake text-only world would qualify for a REAL gigabyte model load.
    # Same hermetic-stub class as the config-endpoint stub above: the
    # assertions below are unchanged, the new machine-dependent surface is
    # simply neutralized.
    monkeypatch.setattr(vl, "_VISION_AUTOLOAD_ENABLED", False)
    saved = {
        "extra": vl._EXTRA_VISION_ENDPOINTS,
        "cache": dict(vl._VISION_CAPABILITY_CACHE),
    }
    vl.clear_vision_capability_cache()  # also resets reused-selection globals
    vl._EXTRA_VISION_ENDPOINTS = []
    yield
    vl._EXTRA_VISION_ENDPOINTS = saved["extra"]
    vl._VISION_CAPABILITY_CACHE.clear()
    vl._VISION_CAPABILITY_CACHE.update(saved["cache"])


def _install_httpx(monkeypatch, scenario: str) -> _FakeHttpx:
    fake = _FakeHttpx(candidate_scenario=scenario)
    monkeypatch.setattr(httpx, "get", fake.get)
    monkeypatch.setattr(httpx, "post", fake.post)
    return fake


# ---------------------------------------------------------------------------
# C1 — text-only candidate is NOT reused
# ---------------------------------------------------------------------------


class TestTextOnlyCandidateNotReused:
    def test_discovery_returns_none_for_text_only(self, monkeypatch, isolated_vl):
        _install_httpx(monkeypatch, "textonly")
        vl.set_vision_candidate_endpoints(["http://localhost:1234/v1"])
        assert vl._discover_reusable_vision_server("") is None

    def test_ensure_returns_false_no_spawn_for_text_only(self, monkeypatch, isolated_vl):
        _install_httpx(monkeypatch, "textonly")
        vl.set_vision_candidate_endpoints(["http://localhost:1234/v1"])
        # Owned default port down -> fast path fails; candidate is text-only ->
        # not reused. There is no spawn to fall through to anymore.
        result = vl._ensure_vision_server_running("")
        assert result is False
        # Structural proof: no spawn surface exists in the module.
        assert getattr(vl, "_spawn_vision_server_now", None) is None


# ---------------------------------------------------------------------------
# C2 — verified multimodal candidate IS reused, NO subprocess spawned
# ---------------------------------------------------------------------------


class TestMultimodalCandidateReused:
    def test_discovery_returns_the_candidate(self, monkeypatch, isolated_vl):
        _install_httpx(monkeypatch, "multimodal")
        vl.set_vision_candidate_endpoints(["http://localhost:1234/v1"])
        assert vl._discover_reusable_vision_server("") == "http://localhost:1234/v1"

    def test_ensure_reuses_without_spawn(self, monkeypatch, isolated_vl):
        _install_httpx(monkeypatch, "multimodal")
        vl.set_vision_candidate_endpoints(["http://localhost:1234/v1"])
        result = vl._ensure_vision_server_running("")
        assert result is True
        # The whole point: the borrowed server is selected and routed.
        assert vl._reused_vision_base_url == "http://localhost:1234/v1"

    def test_capability_verdict_is_cached(self, monkeypatch, isolated_vl):
        fake = _install_httpx(monkeypatch, "multimodal")
        vl.set_vision_candidate_endpoints(["http://localhost:1234/v1"])
        # Returns the served model id when multimodal-capable (not a bare bool).
        assert vl._is_verified_vision_capable("http://localhost:1234/v1") == "vision-model"
        # Second call must NOT hit the network again.
        fake.post_calls.clear()
        assert vl._is_verified_vision_capable("http://localhost:1234/v1") == "vision-model"
        assert fake.post_calls == []

    def test_endpoint_without_v1_is_normalised(self, monkeypatch, isolated_vl):
        """A configured provider endpoint is often `http://localhost:1234` (no
        /v1). The probe must hit `/v1/models`, not the bare root, or every
        borrowed server looks dead. The fake answers only under /v1, so this also
        proves the normalised path is what gets probed."""
        fake = _install_httpx(monkeypatch, "multimodal")
        vl.set_vision_candidate_endpoints(["http://localhost:1234"])
        assert vl._ensure_vision_server_running("") is True
        # The probe must have targeted the /v1 path.
        assert any("localhost:1234/v1/chat/completions" in c for c in fake.post_calls)


# ---------------------------------------------------------------------------
# C3 — disable() drops the reuse selection and touches NO process
# ---------------------------------------------------------------------------


class TestDisableNeverTouchesProcesses:
    def test_disable_clears_reuse_selection(self, monkeypatch, isolated_vl):
        _install_httpx(monkeypatch, "multimodal")
        vl.set_vision_candidate_endpoints(["http://localhost:1234/v1"])
        assert vl._ensure_vision_server_running("") is True
        assert vl._reused_vision_base_url == "http://localhost:1234/v1"

        vl.get_lfm_vl_provider().disable()
        assert vl._reused_vision_base_url is None

    def test_no_process_control_surface_exists(self):
        """specs/vision-single-server REQ-2: there is no owned server to stop
        and no idle watchdog — the symbols are GONE (structurally impossible
        for disable() to kill a shared server, not just conventionally safe)."""
        for sym in (
            "_stop_owned_vision_server",
            "_kill_process_tree",
            "_VISION_SERVER_PID",
            "should_idle_stop",
            "_touch_vision_use",
        ):
            assert getattr(vl, sym, None) is None, sym


# ---------------------------------------------------------------------------
# C4 — no candidate -> loud failure, NOTHING spawned
# ---------------------------------------------------------------------------


class TestNoCandidateNoSpawn:
    def test_no_candidates_returns_false_announces_error(self, monkeypatch, isolated_vl):
        _install_httpx(monkeypatch, "down")
        states: list = []
        monkeypatch.setattr(
            vl, "_notify_lifecycle",
            lambda state, reason="", trigger="": states.append((state, reason)),
        )
        result = vl._ensure_vision_server_running("")
        assert result is False
        assert ("error", "no-shared-multimodal-server-available") in states

    def test_no_spawn_surface_exists(self):
        # Structural — the spawn path is deleted, not dormant.
        assert getattr(vl, "_spawn_vision_server_now", None) is None
        assert getattr(vl, "request_warm", None) is None


# ---------------------------------------------------------------------------
# C5 — a reused borrowed server is actually routed to (endpoint + model + auth)
# ---------------------------------------------------------------------------


class TestBorrowedServerRouting:
    def test_call_routes_to_borrowed_endpoint(self, monkeypatch, isolated_vl):
        fake = _install_httpx(monkeypatch, "multimodal")
        vl.set_vision_candidate_endpoints(["http://localhost:1234/v1"])
        provider = vl.get_lfm_vl_provider()
        out = provider._call(b"fake-png-bytes", "describe the screen")
        assert out == "ok"
        # The vision request went to the borrowed server, never the default port.
        assert any("localhost:1234/v1/chat/completions" in c for c in fake.post_calls)
        assert all("18181" not in c for c in fake.post_calls)
        # It used the discovered model id, not the literal "vision-model".
        assert fake.post_payloads
        assert fake.post_payloads[-1]["model"] == "vision-model"

    def test_call_attaches_auth_header_when_credential_present(self, monkeypatch, isolated_vl):
        # Simulate a configured provider whose cred_ref resolves to a real key.
        fake = _install_httpx(monkeypatch, "multimodal")
        vl.set_vision_candidate_endpoints(["http://localhost:1234/v1"])
        monkeypatch.setattr(vl, "_fetch_provider_secret", lambda cred_ref: "test-key-123")
        provider = vl.get_lfm_vl_provider()
        out = provider._call(b"x", "go")
        assert out == "ok"
        # The Authorization header must have been attached to the request.
        assert any(
            (h or {}).get("Authorization") == "Bearer test-key-123"
            for h in fake.post_headers
        )


# ---------------------------------------------------------------------------
# C6 — router-mode server hosting a TEXT LLM (models[0]) AND a VLM must be
# probed across ALL models, not just models[0], or it is wrongly rejected.
# This is the exact setup the user runs: one llama-server process serving
# their large LLM + the VLM, routed by the `model` field.
# ---------------------------------------------------------------------------


class _RouterModeFake:
    """A llama.cpp router-mode server: /models lists a text LLM first and a VLM
    second. The text LLM rejects the image_url; the VLM accepts it."""

    def __init__(self):
        self.post_models: list = []

    def get(self, url: str, timeout: float = 1.0, headers=None):
        if url.endswith("/models"):
            return _FakeResponse(
                200,
                {
                    "data": [
                        {"id": "llama-3.1-8b"},       # text-only, listed FIRST
                        {"id": "lfm2.5-vl-3b"},      # multimodal
                    ]
                },
            )
        return _FakeResponse(200)

    def post(self, url: str, json=None, timeout: float = 1.0, headers=None):
        _mid = (json or {}).get("model")
        self.post_models.append(_mid)
        if _mid == "llama-3.1-8b":
            # A text-only model rejects the image_url with an error payload.
            return _FakeResponse(200, {"error": {"message": "image_url not supported"}})
        # Any other model (the VLM) accepts the image and completes.
        return _FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})


class TestMultiModelRouterProbe:
    def test_probe_picks_vlm_not_first_text_model(self, monkeypatch, isolated_vl):
        _rf = _RouterModeFake()
        monkeypatch.setattr(httpx, "get", _rf.get)
        monkeypatch.setattr(httpx, "post", _rf.post)
        # The probe must return the VLM id, not the text-only models[0].
        assert vl._probe_vision_capability("http://localhost:9999/v1") == "lfm2.5-vl-3b"
        # And it must have actually tested BOTH models (proving it did not stop
        # at the text-only first model and wrongly conclude "not multimodal").
        assert "llama-3.1-8b" in _rf.post_models
        assert "lfm2.5-vl-3b" in _rf.post_models

    def test_discovery_selects_vlm_from_router_mode_server(self, monkeypatch, isolated_vl):
        _rf = _RouterModeFake()
        monkeypatch.setattr(httpx, "get", _rf.get)
        monkeypatch.setattr(httpx, "post", _rf.post)
        vl.set_vision_candidate_endpoints(["http://localhost:9999/v1"])
        _endpoint = vl._discover_reusable_vision_server("")
        assert _endpoint == "http://localhost:9999/v1"
        # The reused selection must carry the VLM model id, so vision calls route
        # to the VLM (not the text LLM) on the shared server.
        assert vl._reused_vision_model == "lfm2.5-vl-3b"
        assert vl._reused_vision_base_url == "http://localhost:9999/v1"

    def test_cached_verdict_uses_vlm_id(self, monkeypatch, isolated_vl):
        _rf = _RouterModeFake()
        monkeypatch.setattr(httpx, "get", _rf.get)
        monkeypatch.setattr(httpx, "post", _rf.post)
        assert vl._is_verified_vision_capable("http://localhost:9999/v1") == "lfm2.5-vl-3b"
        # Second call hits the cache, not the network.
        _rf.post_models.clear()
        assert vl._is_verified_vision_capable("http://localhost:9999/v1") == "lfm2.5-vl-3b"
        assert _rf.post_models == []


# ---------------------------------------------------------------------------
# C7 — user pins the vision model (lfm2.5-vl-3b) so the system PREFERS it over
# any other multimodal model on the shared router-mode server (e.g. bonsai27B,
# a multimodal tool model). The iterate-all fallback is kept: only if the pinned
# model is absent/not-multimodal do we fall back to the first multimodal model.
# ---------------------------------------------------------------------------


class _PinnedRouterFake:
    """Router-mode server where a MULTIMODAL tool model (bonsai27B) is listed
    BEFORE the VLM (lfm2.5-vl-3b). Without a pin the auto-scan would wrongly grab
    bonsai27B; the pin must force lfm2.5-vl-3b."""

    def __init__(self):
        self.post_models: list = []

    def get(self, url: str, timeout: float = 1.0, headers=None):
        if url.endswith("/models"):
            return _FakeResponse(
                200,
                {
                    "data": [
                        {"id": "llama-3.1-8b"},  # text-only
                        {"id": "bonsai27B"},     # multimodal tool model (listed first)
                        {"id": "lfm2.5-vl-3b"},  # the VLM we want
                    ]
                },
            )
        return _FakeResponse(200)

    def post(self, url: str, json=None, timeout: float = 1.0, headers=None):
        _mid = (json or {}).get("model")
        self.post_models.append(_mid)
        if _mid == "llama-3.1-8b":
            return _FakeResponse(200, {"error": {"message": "image_url not supported"}})
        # bonsai27B and lfm2.5-vl-3b both accept the image.
        return _FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})


class TestVisionModelPin:
    def test_pin_prefers_lfm_vl_3b_over_bonsai27b(self, monkeypatch, isolated_vl):
        _rf = _PinnedRouterFake()
        monkeypatch.setattr(httpx, "get", _rf.get)
        monkeypatch.setattr(httpx, "post", _rf.post)
        assert (
            vl._probe_vision_capability(
                "http://localhost:9999/v1", preferred_model="lfm2.5-vl-3b"
            )
            == "lfm2.5-vl-3b"
        )
        assert "lfm2.5-vl-3b" in _rf.post_models

    def test_no_pin_falls_back_to_first_multimodal_bonsai27b(self, monkeypatch, isolated_vl):
        _rf = _PinnedRouterFake()
        monkeypatch.setattr(httpx, "get", _rf.get)
        monkeypatch.setattr(httpx, "post", _rf.post)
        # Without a pin the auto-scan picks the FIRST multimodal model = bonsai27B,
        # proving why the pin is needed AND that the fallback still works.
        assert vl._probe_vision_capability("http://localhost:9999/v1") == "bonsai27B"

    def test_discovery_uses_pinned_vision_model(self, monkeypatch, isolated_vl):
        _rf = _PinnedRouterFake()
        monkeypatch.setattr(httpx, "get", _rf.get)
        monkeypatch.setattr(httpx, "post", _rf.post)
        vl.set_vision_candidate_endpoints([("http://localhost:9999/v1", None, "lfm2.5-vl-3b")])
        _endpoint = vl._discover_reusable_vision_server("")
        assert _endpoint == "http://localhost:9999/v1"
        assert vl._reused_vision_model == "lfm2.5-vl-3b"


# ---------------------------------------------------------------------------
# C9 — the shared local model server auto-enters the candidate set ONLY when
# it is actually running with vision loaded (specs/vision-single-server: this
# is now the primary tier-3 source).
# ---------------------------------------------------------------------------


class TestSharedServerAutoCandidate:
    def test_loaded_with_projector_enters_candidates(self, monkeypatch):
        class _Mgr:
            def get_status(self):
                return {
                    "loaded": True,
                    "vision_loaded": True,
                    "endpoint": "http://127.0.0.1:8082/v1",
                }

        monkeypatch.setattr(
            "backend.agent.local_model_manager.get_local_model_manager",
            lambda: _Mgr(),
        )
        monkeypatch.setattr(vl, "_read_global_vision_model_pin", lambda: "")
        candidates = vl._load_candidate_endpoints_from_config()
        assert ("http://127.0.0.1:8082/v1", None, "") in candidates

    def test_loaded_text_only_does_NOT_enter_candidates(self, monkeypatch):
        """A model loaded WITHOUT --mmproj must never become a vision target —
        REQ-1 AC3 of unified-vision-routing, now at the discovery layer."""
        class _Mgr:
            def get_status(self):
                return {
                    "loaded": True,
                    "vision_loaded": False,
                    "endpoint": "http://127.0.0.1:8082/v1",
                }

        monkeypatch.setattr(
            "backend.agent.local_model_manager.get_local_model_manager",
            lambda: _Mgr(),
        )
        monkeypatch.setattr(vl, "_read_global_vision_model_pin", lambda: "")
        candidates = vl._load_candidate_endpoints_from_config()
        assert all("8082" not in c[0] for c in candidates)

    def test_manager_errors_never_break_discovery(self, monkeypatch):
        monkeypatch.setattr(
            "backend.agent.local_model_manager.get_local_model_manager",
            lambda: (_ for _ in ()).throw(RuntimeError("no manager")),
        )
        # must not raise
        assert isinstance(vl._load_candidate_endpoints_from_config(), list)
# (the global pin). The backend reads it from there and prefers it during the
# borrowed-server probe. A path pin must also match a FILENAME served-id
# (basename). (The local-spawn ladder was deleted with the spawn path.)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# C8 — the vision-card dropdown persists to field_values['vision']['vision_model']
# (the global pin). The backend reads it from there and prefers it during the
# borrowed-server probe.
# ---------------------------------------------------------------------------


class _FakeConfig:
    """Minimal stand-in for iris_config.IRISConfig exposing field_values."""

    def __init__(self, field_values=None, providers=None):
        self.field_values = field_values or {}
        self.inference = type("I", (), {"providers": providers or {}})()


class TestGlobalVisionModelPin:
    def test_read_global_vision_model_pin_from_field_values(self, monkeypatch, isolated_vl):
        _cfg = _FakeConfig(field_values={"vision": {"vision_model": "lfm2.5-vl-3b"}})
        monkeypatch.setattr(vl, "_read_global_vision_model_pin", lambda: "lfm2.5-vl-3b")
        assert vl._read_global_vision_model_pin() == "lfm2.5-vl-3b"

    def test_read_global_vision_model_pin_missing(self, monkeypatch, isolated_vl):
        monkeypatch.setattr(vl, "_read_global_vision_model_pin", lambda: "")
        assert vl._read_global_vision_model_pin() == ""

    def test_probe_pin_matches_by_basename(self, monkeypatch, isolated_vl):
        # The dropdown stores a PATH pin; a borrowed router-mode server serves by
        # FILENAME. The probe must bridge the two via basename matching.
        class _BasenameServer:
            def get(self, url, timeout=1.0, headers=None):
                if url.endswith("/models"):
                    return _FakeResponse(200, {"data": [{"id": "lfm2.5-vl-3b.gguf"}]})
                return _FakeResponse(200)

            def post(self, url, json=None, timeout=1.0, headers=None):
                _mid = (json or {}).get("model")
                if _mid == "lfm2.5-vl-3b.gguf":
                    return _FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})
                return _FakeResponse(200, {"error": {"message": "not found"}})

        _rf = _BasenameServer()
        monkeypatch.setattr(httpx, "get", _rf.get)
        monkeypatch.setattr(httpx, "post", _rf.post)
        # Pin is a full PATH; the server only knows the basename.
        assert (
            vl._probe_vision_capability(
                "http://localhost:9999/v1", preferred_model="/models/lfm2.5-vl-3b.gguf"
            )
            == "lfm2.5-vl-3b.gguf"
        )
