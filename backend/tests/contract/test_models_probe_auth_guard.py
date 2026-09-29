"""CONTRACT PIN: the `/models` probe never runs without a credential
(2026-09-26).

WHY THIS EXISTS
---------------
`IRISGateway._handle_get_available_models` used to build the request headers
conditionally but then send the request UNCONDITIONALLY:

    headers = {}
    if openai_api_key:
        headers["Authorization"] = f"Bearer {openai_api_key}"
    async with httpx.AsyncClient(...) as c:
        r = await c.get(models_url, headers=headers)      # <-- always ran

With no key and the default base URL that is a guaranteed unauthenticated call
to a remote provider. Measured live:

    GET https://api.openai.com/v1/models  ->  HTTP/1.1 401 Unauthorized
    (.iris-logs/live/today.txt, 2026-08-30 09:04:02)

Every model-list refresh paid the request AND up to a 5s connect timeout to
learn nothing. The guard is: no key -> no request; serve the provider catalog.

WHAT IS PINNED
--------------
1. NO KEY  -> ZERO outbound HTTP. `httpx.AsyncClient` is replaced by a class
   that raises on construction, so any attempt to probe fails this test rather
   than merely being asserted absent.
2. KEY PRESENT -> the probe STILL RUNS. The guard must not disable the
   authenticated path; this is the over-guarding pin.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple

from backend.iris_gateway import IRISGateway


# ── fakes ────────────────────────────────────────────────────────────────────

class _FakeWSManager:
    def __init__(self):
        self.sent: List[Tuple[str, Dict[str, Any]]] = []

    async def send_to_client(self, client_id, msg):
        self.sent.append((client_id, msg))

    async def broadcast_to_session(self, session_id, msg, exclude_clients=None):
        pass

    async def broadcast(self, msg):
        pass


class _SessionState:
    def __init__(self, values: Dict[Tuple[str, str], Any]):
        self._v = values

    def get_field_value(self, section, key, default=None):
        return self._v.get((section, key), default)


class _StateManager:
    def __init__(self, values: Dict[Tuple[str, str], Any]):
        self._ss = _SessionState(values)

    async def _get_session_state_manager(self, session_id):
        return self._ss


class _Kernel:
    _swarm_enabled = False


def _gateway(values) -> Tuple[IRISGateway, _FakeWSManager]:
    ws = _FakeWSManager()
    gw = IRISGateway(ws_manager=ws, state_manager=_StateManager(values))
    return gw, ws


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _no_kernel(monkeypatch):
    """The swarm short-circuit must not fire; make the kernel lookup inert."""
    try:
        import backend.agent.agent_kernel as ak
    except Exception:  # pragma: no cover — the handler swallows this too
        return
    monkeypatch.setattr(ak, "get_agent_kernel", lambda session_id: _Kernel(),
                        raising=False)


def _models_of(ws: _FakeWSManager) -> List[Dict[str, Any]]:
    assert ws.sent, "the handler must always answer the client"
    return ws.sent[-1][1]["payload"]["models"]


# ── 1. no key -> no outbound request ─────────────────────────────────────────

class _ForbiddenClient:
    """Records construction. The handler's own `except Exception` swallows a
    raised error, so an exception is NOT a proof — counting constructions is.
    Any construction is the failure this test exists to catch."""

    constructions: List[Dict[str, Any]] = []

    def __init__(self, *a, **k):
        _ForbiddenClient.constructions.append({"args": a, "kwargs": k})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):
        return _FakeResponse()


class TestNoKeyMakesNoRequest:
    def test_no_key_skips_the_probe_entirely(self, monkeypatch):
        _ForbiddenClient.constructions = []
        gw, ws = _gateway({})  # no api_key, no api_base_url -> default OpenAI
        _no_kernel(monkeypatch)
        monkeypatch.setattr(
            "backend.iris_gateway.httpx.AsyncClient", _ForbiddenClient
        )

        _run(gw._handle_get_available_models(
            "s1", "c1", {"payload": {"model_provider": "api"}},
        ))

        assert _ForbiddenClient.constructions == [], (
            "an unauthenticated probe was attempted — no API key is configured, "
            "so the request is a guaranteed 401 against the provider"
        )

        models = _models_of(ws)
        assert models, (
            "with the probe skipped the client must still receive the provider "
            "catalog, otherwise the dropdown empties"
        )
        assert all(m.get("source") for m in models)

    def test_no_key_guard_holds_for_any_remote_base_url(self, monkeypatch):
        """The guard keys on the CREDENTIAL, not on which provider the URL
        points at — a custom base URL without a key is the same 401."""
        _ForbiddenClient.constructions = []
        gw, ws = _gateway({
            ("model_selection", "api_base_url"): "https://api.cerebras.ai/v1",
        })
        _no_kernel(monkeypatch)
        monkeypatch.setattr(
            "backend.iris_gateway.httpx.AsyncClient", _ForbiddenClient
        )

        _run(gw._handle_get_available_models(
            "s1", "c1", {"payload": {"model_provider": "api"}},
        ))

        assert _ForbiddenClient.constructions == [], (
            "a custom remote base URL without a key is still unauthenticated"
        )
        assert _models_of(ws), "the catalog fallback must serve the client"


# ── 2. key present -> the probe still runs (no over-guarding) ───────────────

class _FakeResponse:
    status_code = 200

    def json(self):
        return {"data": [{"id": "gpt-4o"}, {"id": "llava-v1.5-7b"}]}


class _FakeClient:
    calls: List[Dict[str, Any]] = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):
        _FakeClient.calls.append({"url": url, "headers": dict(headers or {})})
        return _FakeResponse()


class TestKeyPresentStillProbes:
    def test_key_present_probes_with_bearer_header(self, monkeypatch):
        _FakeClient.calls = []
        gw, ws = _gateway({})
        _no_kernel(monkeypatch)
        monkeypatch.setattr(
            "backend.iris_gateway.httpx.AsyncClient", _FakeClient
        )

        _run(gw._handle_get_available_models(
            "s1", "c1",
            {"payload": {"model_provider": "api", "api_key": "sk-test-key"}},
        ))

        assert len(_FakeClient.calls) == 1, (
            "a configured key must still reach the provider — the guard must "
            "not disable the authenticated path"
        )
        call = _FakeClient.calls[0]
        assert call["url"].endswith("/models")
        assert call["headers"].get("Authorization") == "Bearer sk-test-key"

        ids = [m["id"] for m in _models_of(ws)]
        assert "gpt-4o" in ids
        assert "llava-v1.5-7b" not in ids, (
            "vision-only models stay out of the reasoning/tool dropdowns"
        )
