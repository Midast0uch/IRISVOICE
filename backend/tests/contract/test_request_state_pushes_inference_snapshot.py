"""Anti-drift contract: `_handle_request_state` (the WS `request_state` path
the frontend sends on EVERY open and reconnect) must emit the SAME inference
snapshot key set as every other emission site.

Root cause pinned (2026-08-12, pin_05511443f03b): the Provider/Model cards
depended on the frontend's one-shot mount-time REST fetch, which raced
backend startup and left the dropdowns empty until a manual refresh — the WS
never carried the inference snapshot on connect.  The fix pushes
`role_bindings_updated` (full `build_inference_snapshot`) inside
`_handle_request_state`, so this test drives the REAL handler and asserts:

  1. a `role_bindings_updated` message IS sent to the client on request_state,
  2. its payload key set is EXACTLY what `build_inference_snapshot` returns
     (same builder → parity holds by construction; this test pins it anyway
     so a future change that diverges the site fails immediately),
  3. with NO kernel present (peek returns None), the payload is still the
     full key set (empty providers, static provider_presets/model_catalog) —
     the "dropdown populates before first kernel" guarantee.

`_handle_request_state` never constructs a kernel: it uses
`peek_active_kernel`, so this test also asserts construction-free reads.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

import pytest

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import InferenceRouter
from backend.agent.inference.snapshot import build_inference_snapshot
from backend.iris_gateway import IRISGateway


class _FakeWSManager:
    """Records send_to_client / broadcast calls like the real manager's
    per-client and per-session fan-out."""

    def __init__(self):
        self.sent: List[Tuple[str, Dict[str, Any]]] = []
        self.broadcasts: List[Tuple[Optional[str], Dict[str, Any]]] = []

    async def send_to_client(self, client_id, msg):
        self.sent.append((client_id, msg))

    async def broadcast_to_session(self, session_id, msg):
        self.broadcasts.append((session_id, msg))

    async def flush_pending(self, session_id, client_id):
        pass


class _FakeState:
    """Minimal stand-in for the session state object _handle_request_state
    reads: exposes field_values (dict of dicts) and model_dump()."""

    def __init__(self, field_values: Optional[Dict[str, Dict[str, Any]]] = None):
        self.field_values: Dict[str, Dict[str, Any]] = field_values or {}

    def model_dump(self) -> Dict[str, Any]:
        return {"field_values": self.field_values}


class _FakeStateManager:
    def __init__(self, state: Optional[_FakeState] = None):
        self._state = state or _FakeState()

    async def get_state(self, session_id):
        return self._state


class _FakeKernel:
    def __init__(self, router: Optional[InferenceRouter]):
        self._router = router


def _make_router() -> InferenceRouter:
    reg = ProviderRegistry()
    reg.add(ProviderInstance(id="cerebras", label="Cerebras", kind=ProviderKind.API,
                              model="gemma-4-31b", api_base_url="https://api.cerebras.ai/v1"))
    router = InferenceRouter.__new__(InferenceRouter)
    object.__setattr__(router, "_registry", reg)
    object.__setattr__(router, "_roles", RoleBindingTable(reg))
    object.__setattr__(router, "_default_role", "reasoning")
    object.__setattr__(router, "_transports", {})
    object.__setattr__(router, "_inprocess_mgr", None)
    return router


@pytest.fixture
def loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestRequestStatePushesInferenceSnapshot:
    def test_request_state_emits_role_bindings_updated_with_full_key_set(
        self, loop, monkeypatch
    ):
        """request_state must deliver the FULL build_inference_snapshot key set
        to the client, not just initial_state."""
        router = _make_router()
        ws = _FakeWSManager()
        gw = IRISGateway(ws_manager=ws, state_manager=_FakeStateManager())
        gw._main_loop = loop

        # _handle_request_state does a LOCAL `from backend.agent.agent_kernel
        # import peek_active_kernel` at call time — patch the source module.
        monkeypatch.setattr(
            "backend.agent.agent_kernel.peek_active_kernel",
            lambda session_id: _FakeKernel(router),
        )
        # load_field_values is imported into iris_gateway's namespace at
        # module import (`from .iris_config import ... load_field_values`).
        monkeypatch.setattr("backend.iris_config.load_field_values", lambda: {})

        loop.run_until_complete(
            gw._handle_request_state("session_iris", "iris")
        )

        emitted = [m for (_, m) in ws.sent if m.get("type") == "role_bindings_updated"]
        assert emitted, (
            f"request_state must emit role_bindings_updated, got types: "
            f"{[m.get('type') for (_, m) in ws.sent]}"
        )
        payload = emitted[0]["payload"]

        rest_payload = build_inference_snapshot(router)
        assert set(payload.keys()) == set(rest_payload.keys()), (
            f"request_state role_bindings_updated keys {sorted(payload.keys())} "
            f"!= build_inference_snapshot keys {sorted(rest_payload.keys())}"
        )
        # The fields the Provider dropdown + ModelSwitcher need must be present.
        assert "providers" in payload
        assert "provider_presets" in payload
        assert "model_catalog" in payload
        assert "role_bindings" in payload

    def test_request_state_with_no_kernel_still_emits_full_key_set(
        self, loop, monkeypatch
    ):
        """Before the first kernel exists, request_state must STILL deliver the
        full key set (empty providers, static presets/catalog) — the guarantee
        that the dropdown populates even when the mount fetch raced startup.
        peek_active_kernel returning None must be handled, not crash."""
        ws = _FakeWSManager()
        gw = IRISGateway(ws_manager=ws, state_manager=_FakeStateManager())
        gw._main_loop = loop

        monkeypatch.setattr(
            "backend.agent.agent_kernel.peek_active_kernel",
            lambda session_id: None,
        )
        monkeypatch.setattr("backend.iris_config.load_field_values", lambda: {})

        loop.run_until_complete(
            gw._handle_request_state("session_iris", "iris")
        )

        emitted = [m for (_, m) in ws.sent if m.get("type") == "role_bindings_updated"]
        assert emitted, "request_state must emit role_bindings_updated even with no kernel"
        payload = emitted[0]["payload"]

        rest_payload = build_inference_snapshot(None)
        assert set(payload.keys()) == set(rest_payload.keys()), (
            f"no-kernel payload keys {sorted(payload.keys())} != "
            f"build_inference_snapshot(None) keys {sorted(rest_payload.keys())}"
        )
        # provider_presets is STATIC data — the Provider dropdown must populate
        # from it even before any router exists.
        assert len(payload.get("provider_presets", [])) > 0
        assert payload.get("providers") == []

    def test_request_state_never_constructs_a_kernel(self, loop, monkeypatch):
        """Read-only paths must never pay kernel-construction cost (measured
        71.81s cold). peek_active_kernel is the ONLY kernel access — if the
        handler called get_agent_kernel/get_active_kernel instead, this test
        fails loudly."""
        import backend.agent.agent_kernel as ak_module

        ws = _FakeWSManager()
        gw = IRISGateway(ws_manager=ws, state_manager=_FakeStateManager())
        gw._main_loop = loop

        calls: Dict[str, int] = {"peek": 0, "construct": 0}

        def _fake_peek(session_id):
            calls["peek"] += 1
            return None

        def _boom(*_a, **_k):  # pragma: no cover - must never be called
            calls["construct"] += 1
            raise AssertionError("request_state must NOT construct a kernel")

        monkeypatch.setattr(ak_module, "peek_active_kernel", _fake_peek)
        monkeypatch.setattr(ak_module, "get_agent_kernel", _boom)
        monkeypatch.setattr(ak_module, "get_active_kernel", _boom)
        monkeypatch.setattr("backend.iris_config.load_field_values", lambda: {})

        loop.run_until_complete(
            gw._handle_request_state("session_iris", "iris")
        )

        assert calls["peek"] >= 1, "request_state must peek the active kernel"
        assert calls["construct"] == 0, (
            "request_state must NEVER construct a kernel — that is the 71.8s "
            "cold-construction hazard that caused the empty-dropdown bug"
        )
