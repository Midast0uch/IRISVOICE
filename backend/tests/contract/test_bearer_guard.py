"""Contract tests for the Bearer fail-closed guard (specs/local-model-lifecycle-sync
REQ-1) and provider health truth (REQ-2).

CT-4 — `ApiHttpxTransport` never emits `Authorization: Bearer ` (empty value);
       an empty key omits the header entirely instead of crashing httpx with
       `Illegal header value b'Bearer '`.
CT-5 — `InferenceRouter.health_check` reports `{ok:false, reason:"missing_api_key"}`
       for an API provider with no stored credential, and `_build_transport`
       raises `ProviderNotReadyError` BEFORE building a transport.

These pin the boundary so a future edit that reintroduces an unconditional
`f"Bearer {key}"` fails here immediately.
"""

from __future__ import annotations

import pytest

from backend.agent.exceptions import ProviderNotReadyError
from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import InferenceRouter
from backend.agent.inference.transport import ApiHttpxTransport


def _make_router() -> InferenceRouter:
    reg = ProviderRegistry()
    reg.add(
        ProviderInstance(
            id="cerebras",
            label="Cerebras",
            kind=ProviderKind.API,
            model="gemma-4-31b",
            api_base_url="https://api.cerebras.ai/v1",
        )
    )
    router = InferenceRouter.__new__(InferenceRouter)
    object.__setattr__(router, "_registry", reg)
    object.__setattr__(router, "_roles", RoleBindingTable(reg))
    object.__setattr__(router, "_default_role", "reasoning")
    object.__setattr__(router, "_transports", {})
    object.__setattr__(router, "_inprocess_mgr", None)
    router.bind_role("reasoning", "cerebras")
    return router


class TestBearerNeverEmpty:
    """CT-4: ApiHttpxTransport must never send `Authorization: Bearer `."""

    def test_empty_key_omits_authorization_header(self, monkeypatch):
        """An empty api_key must NOT produce an Authorization header at all —
        httpx rejects `Bearer ` as an illegal header value."""
        captured = {}

        def _fake_stream(self, url, headers, body, model, messages, chunk_callback, reasoning_callback=None):
            captured["headers"] = headers
            return ("", "", [])

        monkeypatch.setattr(ApiHttpxTransport, "_stream", _fake_stream)
        t = ApiHttpxTransport(
            api_base_url="https://api.cerebras.ai/v1", api_key=""
        )
        t.generate("gemma-4-31b", [{"role": "user", "content": "hi"}], chunk_callback=lambda s: None)
        assert "Authorization" not in captured["headers"], (
            f"empty key must omit Authorization, got {captured['headers']}"
        )

    def test_whitespace_key_omits_authorization_header(self, monkeypatch):
        """A whitespace-only key is treated as missing — no header."""
        captured = {}

        def _fake_stream(self, url, headers, body, model, messages, chunk_callback, reasoning_callback=None):
            captured["headers"] = headers
            return ("", "", [])

        monkeypatch.setattr(ApiHttpxTransport, "_stream", _fake_stream)
        t = ApiHttpxTransport(
            api_base_url="https://api.cerebras.ai/v1", api_key="   "
        )
        t.generate("gemma-4-31b", [{"role": "user", "content": "hi"}], chunk_callback=lambda s: None)
        assert "Authorization" not in captured["headers"]

    def test_real_key_sets_bearer_header(self, monkeypatch):
        """A real key still produces `Bearer <key>` (stripped of whitespace)."""
        captured = {}

        def _fake_stream(self, url, headers, body, model, messages, chunk_callback, reasoning_callback=None):
            captured["headers"] = headers
            return ("", "", [])

        monkeypatch.setattr(ApiHttpxTransport, "_stream", _fake_stream)
        t = ApiHttpxTransport(
            api_base_url="https://api.cerebras.ai/v1", api_key="  sk-test-123  "
        )
        t.generate("gemma-4-31b", [{"role": "user", "content": "hi"}], chunk_callback=lambda s: None)
        assert captured["headers"]["Authorization"] == "Bearer sk-test-123"


class TestProviderHealth:
    """CT-5: API provider with no credential is NOT ready."""

    def test_health_check_reports_missing_api_key(self, monkeypatch):
        router = _make_router()
        monkeypatch.setattr(
            "backend.agent.inference.router.get_secret", lambda pid: None
        )
        result = router.health_check_provider("reasoning")
        assert result["ok"] is False
        assert result["reason"] == "missing_api_key"
        assert "cerebras" in result["provider"]

    def test_build_transport_raises_provider_not_ready(self, monkeypatch):
        router = _make_router()
        monkeypatch.setattr(
            "backend.agent.inference.router.get_secret", lambda pid: None
        )
        inst = router.resolve("reasoning")
        with pytest.raises(ProviderNotReadyError) as excinfo:
            router._build_transport(inst)
        assert excinfo.value.details["reason"] == "missing_api_key"
        assert excinfo.value.code.value == 1005

    def test_health_check_ok_when_key_present(self, monkeypatch):
        router = _make_router()
        monkeypatch.setattr(
            "backend.agent.inference.router.get_secret", lambda pid: "sk-real-key"
        )
        result = router.health_check_provider("reasoning")
        assert result["ok"] is True
        assert "reason" not in result
