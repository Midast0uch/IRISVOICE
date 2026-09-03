"""Anti-drift contract: REST `/api/inference/state` and BOTH WS
`role_bindings_updated` broadcast sites must emit the SAME key set.

Before this fix, three sites built the inference-state payload three
different ways:
  - `backend/main.py`'s REST endpoint: `router.snapshot()` + manually
    appended `provider_presets` / `model_catalog` / local-model status.
  - `iris_gateway.py`'s `_persist_and_broadcast_role_bindings` (the
    `set_role_binding` path): bare `router.snapshot()` — no presets, no
    catalog.
  - `iris_gateway.py`'s `set_model_selection` path: an ad-hoc
    `{"role_bindings": [...]}` dict — not even `providers`.

`backend.agent.inference.snapshot.build_inference_snapshot` is now the ONE
place all three call, so this test drives the REAL handlers (not a
reimplementation) and asserts their emitted key sets are identical. This is
the assertion that prevents the drift from returning — a future change that
adds a field to only one site fails here immediately.

NOTE: this deliberately does NOT boot `backend.main`'s FastAPI `app` — its
module-level import chain pulls in audio/model/litellm setup with real
network calls (observed >60s just to import in this environment) that would
make this test file itself the thing that times out. Since main.py's
`api_inference_state` endpoint body is exactly `return
build_inference_snapshot(router)` (backend/main.py, no extra processing
after the builder call), calling the builder directly on the SAME router
IS what the REST endpoint returns — verified by reading the endpoint's
source at backend/main.py.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import InferenceRouter
from backend.agent.inference.snapshot import build_inference_snapshot
from backend.iris_config import IRISConfig
from backend.iris_gateway import IRISGateway


class _FakeWSManager:
    def __init__(self):
        self.sent = []
        self.broadcasts = []

    async def send_to_client(self, client_id, msg):
        self.sent.append((client_id, msg))

    async def broadcast_to_session(self, session_id, msg):
        self.broadcasts.append((session_id, msg))

    async def broadcast(self, msg):
        self.broadcasts.append((None, msg))


class _FakeKernel:
    """Stand-in for AgentKernel exposing only what the handlers read/call."""

    def __init__(self, router):
        self._router = router

    def set_model_selection(self, reasoning_model, tool_execution_model,
                             model_provider=None, api_base_url=None, api_key=None,
                             preserve_bindings=False):
        # The real AgentKernel.set_model_selection registers a ProviderInstance
        # and binds roles on self._router as a side effect (agent_kernel.py
        # :9488-9516) BEFORE the gateway broadcasts. Mirror that side effect
        # here so the router the broadcast reads from is the one the "user
        # selection" actually produced, not an empty stand-in.
        inst = ProviderInstance(
            id=model_provider, label=model_provider, kind=ProviderKind.API,
            model=reasoning_model or "",
        )
        self._router.add_provider(inst)
        self._router.bind_role("reasoning", inst.id)
        if tool_execution_model:
            self._router.bind_role("tool_execution", inst.id)
        return True


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


def _fake_with_modify_config(modifier_fn):
    """In-memory stand-in for iris_config.with_modify_config — applies the
    modifier to a throwaway IRISConfig instead of touching disk."""
    cfg = IRISConfig()
    modifier_fn(cfg)
    return cfg


@pytest.fixture
def loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestInferenceSnapshotKeyParity:
    def test_set_model_selection_broadcast_matches_rest_key_set(self, loop, monkeypatch):
        """The `set_model_selection` WS broadcast (iris_gateway.py ~5959-5977)
        must carry the SAME keys as build_inference_snapshot() — i.e. what
        the REST endpoint returns — not the old bare {"role_bindings": [...]}."""
        router = _make_router()
        ws = _FakeWSManager()
        gw = IRISGateway(ws_manager=ws)
        gw._main_loop = loop

        kernel = _FakeKernel(router)
        # `_handle_set_model_selection` calls the module-level `get_agent_kernel`
        # bound into iris_gateway's own namespace at import time (`from .agent
        # import get_agent_kernel`) — patch it there, not on backend.agent.
        monkeypatch.setattr(
            "backend.iris_gateway.get_agent_kernel", lambda session_id=None: kernel
        )
        monkeypatch.setattr(
            "backend.iris_config.with_modify_config", _fake_with_modify_config
        )

        msg = {
            "type": "set_model_selection",
            "payload": {
                "reasoning_model": "gemma-4-31b",
                "tool_execution_model": "gemma-4-31b",
                "model_provider": "cerebras",
                "api_key": "",
                "api_base_url": "",
            },
        }
        loop.run_until_complete(
            gw.handle_message("iris", msg, session_id="session_iris")
        )

        broadcasts = [m for (_, m) in ws.broadcasts if m.get("type") == "role_bindings_updated"]
        assert broadcasts, f"expected a role_bindings_updated broadcast, got: {ws.broadcasts}"
        ws_payload = broadcasts[0]["payload"]

        rest_payload = build_inference_snapshot(router)

        assert set(ws_payload.keys()) == set(rest_payload.keys()), (
            f"set_model_selection broadcast keys {sorted(ws_payload.keys())} "
            f"!= REST endpoint keys {sorted(rest_payload.keys())} — the drift "
            f"build_inference_snapshot exists to prevent has returned"
        )
        # The specific regression: `providers` must be present (its absence
        # is what made the frontend's field-wise-merge fix necessary AND
        # what made the OLD all-or-nothing guard drop this payload outright).
        assert "providers" in ws_payload
        assert "model_catalog" in ws_payload
        assert "provider_presets" in ws_payload

    def test_set_role_binding_broadcast_matches_rest_key_set(self, loop, monkeypatch):
        """The `set_role_binding` WS broadcast (`_persist_and_broadcast_role_
        bindings`) must also carry the same key set as the REST endpoint."""
        router = _make_router()
        ws = _FakeWSManager()
        gw = IRISGateway(ws_manager=ws)
        gw._main_loop = loop

        kernel = _FakeKernel(router)
        # `_handle_set_role_binding` does a LOCAL `from .agent import
        # get_agent_kernel` at call time — patch the source module, matching
        # the existing CT-S5 / test_switch_from_chat_row convention.
        monkeypatch.setattr(
            "backend.agent.get_agent_kernel", lambda session_id=None: kernel
        )
        monkeypatch.setattr(
            "backend.iris_config.load_config", lambda: IRISConfig()
        )
        monkeypatch.setattr(
            "backend.iris_config.save_config", lambda cfg: None
        )

        msg = {
            "type": "set_role_binding",
            "payload": {"role": "reasoning", "instance_id": "cerebras"},
        }
        loop.run_until_complete(
            gw.handle_message("iris", msg, session_id="session_iris")
        )

        broadcasts = [m for (_, m) in ws.broadcasts if m.get("type") == "role_bindings_updated"]
        assert broadcasts, f"expected a role_bindings_updated broadcast, got: {ws.broadcasts}"
        ws_payload = broadcasts[0]["payload"]

        rest_payload = build_inference_snapshot(router)

        assert set(ws_payload.keys()) == set(rest_payload.keys()), (
            f"set_role_binding broadcast keys {sorted(ws_payload.keys())} "
            f"!= REST endpoint keys {sorted(rest_payload.keys())}"
        )

    def test_both_ws_broadcast_sites_agree_with_each_other(self, loop, monkeypatch):
        """The two WS broadcast sites must not just each match the REST
        shape independently — they must match EACH OTHER too, since they are
        both consumed by the same frontend handler."""
        router_a = _make_router()
        router_b = _make_router()

        ws_a = _FakeWSManager()
        gw_a = IRISGateway(ws_manager=ws_a)
        gw_a._main_loop = loop
        kernel_a = _FakeKernel(router_a)
        monkeypatch.setattr(
            "backend.iris_gateway.get_agent_kernel", lambda session_id=None: kernel_a
        )
        monkeypatch.setattr(
            "backend.iris_config.with_modify_config", _fake_with_modify_config
        )
        loop.run_until_complete(
            gw_a.handle_message(
                "iris",
                {
                    "type": "set_model_selection",
                    "payload": {
                        "reasoning_model": "gemma-4-31b",
                        "tool_execution_model": "gemma-4-31b",
                        "model_provider": "cerebras",
                        "api_key": "", "api_base_url": "",
                    },
                },
                session_id="session_iris",
            )
        )
        payload_a = next(
            m["payload"] for (_, m) in ws_a.broadcasts if m.get("type") == "role_bindings_updated"
        )

        ws_b = _FakeWSManager()
        gw_b = IRISGateway(ws_manager=ws_b)
        gw_b._main_loop = loop
        kernel_b = _FakeKernel(router_b)
        monkeypatch.setattr(
            "backend.agent.get_agent_kernel", lambda session_id=None: kernel_b
        )
        monkeypatch.setattr("backend.iris_config.load_config", lambda: IRISConfig())
        monkeypatch.setattr("backend.iris_config.save_config", lambda cfg: None)
        loop.run_until_complete(
            gw_b.handle_message(
                "iris",
                {"type": "set_role_binding", "payload": {"role": "reasoning", "instance_id": "cerebras"}},
                session_id="session_iris",
            )
        )
        payload_b = next(
            m["payload"] for (_, m) in ws_b.broadcasts if m.get("type") == "role_bindings_updated"
        )

        assert set(payload_a.keys()) == set(payload_b.keys()), (
            f"the two WS broadcast sites disagree on key set: "
            f"{sorted(payload_a.keys())} vs {sorted(payload_b.keys())}"
        )
