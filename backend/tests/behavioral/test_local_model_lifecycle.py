"""Behavioral: local-model lifecycle convergence through the REAL gateway
handlers (specs/local-model-lifecycle-sync REQ-3/REQ-4/REQ-5).

B-1 — Unload converges without a refresh: after `_handle_unload_local_model`,
      the router registry loses the `local:*` provider, the manager reports
      `is_loaded()==False`, and a `local_model_status {loaded:false}` is
      broadcast to the SESSION (not just the initiator) so any surviving
      socket reconciles.
B-2 — Reconnect heals drift: `build_inference_snapshot(router)` after unload
      no longer lists the local provider — the exact payload the frontend's
      reconnect re-fetch (useInferenceState T7) pulls from /api/inference/state.
B-4 — Unload frees VRAM (observability): `is_loaded()==False` after unload.

T10 — Missing API key surfaces as ProviderNotReadyError, not a transport crash.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.agent.exceptions import ProviderNotReadyError
from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import InferenceRouter
from backend.agent.inference.snapshot import build_inference_snapshot
from backend.iris_gateway import IRISGateway


class _FakeWSManager:
    def __init__(self):
        self.sent = []
        self.broadcasts = []

    async def send_to_client(self, client_id, msg):
        self.sent.append((client_id, msg))

    async def broadcast_to_session(self, session_id, msg, exclude_clients=None):
        self.broadcasts.append((session_id, msg))

    async def broadcast(self, msg):
        self.broadcasts.append((None, msg))

    async def flush_pending(self, session_id, client_id):
        pass


class _FakeLocalModelManager:
    """Tracks loaded state like the real LocalModelManager (in-process path)."""

    ENDPOINT = "http://127.0.0.1:8082/v1"

    def __init__(self):
        self._loaded = False
        self._model_path = None
        self._llm = None  # in-process: non-None when loaded

    def is_loaded(self):
        return self._loaded

    def get_status(self):
        return {
            "loaded": self._loaded,
            "model_path": self._model_path if self._loaded else None,
            "profile": "balanced" if self._loaded else None,
            "n_ctx": 4096 if self._loaded else None,
            "purpose": "chat" if self._loaded else None,
            "endpoint": None,
            "pid": None,
            "inprocess": self._llm is not None,
            "rotorquant": False,
            "vision_loaded": False,
        }

    async def load_model(self, model_path, profile, custom_params, *,
                         purpose=None, progress_cb=None, crash_cb=None,
                         with_projector=True):
        self._loaded = True
        self._model_path = model_path
        self._llm = object()  # in-process instance held
        return True

    async def unload_model(self):
        self._loaded = False
        self._model_path = None
        self._llm = None
        return True


class _FakeKernel:
    def __init__(self, router):
        self._router = router

    def configure_openai_compat(self, *a, **k):
        pass

    def configure_inprocess_local(self, *a, **k):
        pass


def _make_router() -> InferenceRouter:
    reg = ProviderRegistry()
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


class TestLifecycleConvergence:
    def test_unload_converges_without_refresh(self, loop, monkeypatch):
        """B-1: load then unload — provider gone, manager unloaded, status
        broadcast to the session."""
        router = _make_router()
        ws = _FakeWSManager()
        gw = IRISGateway(ws_manager=ws)
        gw._main_loop = loop
        mgr = _FakeLocalModelManager()
        kernel = _FakeKernel(router)

        monkeypatch.setattr(
            "backend.agent.local_model_manager.get_local_model_manager", lambda: mgr
        )
        monkeypatch.setattr(
            "backend.agent.get_agent_kernel", lambda session_id=None: kernel
        )
        monkeypatch.setattr(
            "backend.iris_config.load_config", lambda: type("C", (), {"inference": type("I", (), {})()})()
        )
        monkeypatch.setattr(
            "backend.iris_config.save_config", lambda cfg: None
        )

        # ── Load ──
        loop.run_until_complete(
            gw._handle_load_local_model(
                "session_iris", "client_iris",
                {"payload": {"model_path": "/models/qwen3-9b.gguf"}},
            )
        )
        assert mgr.is_loaded() is True
        local_ids = [i.id for i in router.registry.list() if i.id.startswith("local:")]
        assert local_ids, "load must register a local:<stem> provider"

        # ── Unload ──
        loop.run_until_complete(
            gw._handle_unload_local_model("session_iris", "client_iris", {})
        )
        assert mgr.is_loaded() is False, "B-4: unload must clear the manager"
        local_ids = [i.id for i in router.registry.list() if i.id.startswith("local:")]
        assert not local_ids, "unload must remove the local:* provider from the registry"

        # The unload status must be broadcast to the SESSION (REQ-3 AC1), not
        # just sent to the initiator — a surviving socket must reconcile.
        session_status = [
            m for (sid, m) in ws.broadcasts
            if sid == "session_iris" and m.get("type") == "local_model_status"
        ]
        assert session_status, (
            "unload must broadcast local_model_status to the session, got "
            f"broadcasts={ws.broadcasts}"
        )
        # The load also broadcasts loaded:true to the session; the LAST
        # local_model_status broadcast is the unload's loaded:false.
        assert session_status[-1]["payload"]["loaded"] is False

    def test_reconnect_snapshot_heals_drift(self, loop, monkeypatch):
        """B-2: after unload, build_inference_snapshot (what the reconnect
        re-fetch pulls) no longer lists the local provider."""
        router = _make_router()
        ws = _FakeWSManager()
        gw = IRISGateway(ws_manager=ws)
        gw._main_loop = loop
        mgr = _FakeLocalModelManager()
        kernel = _FakeKernel(router)
        monkeypatch.setattr("backend.agent.local_model_manager.get_local_model_manager", lambda: mgr)
        monkeypatch.setattr("backend.agent.get_agent_kernel", lambda session_id=None: kernel)
        monkeypatch.setattr(
            "backend.iris_config.load_config", lambda: type("C", (), {"inference": type("I", (), {})()})()
        )
        monkeypatch.setattr("backend.iris_config.save_config", lambda cfg: None)

        loop.run_until_complete(
            gw._handle_load_local_model(
                "session_iris", "client_iris",
                {"payload": {"model_path": "/models/qwen3-9b.gguf"}},
            )
        )
        snap_loaded = build_inference_snapshot(router)
        assert any(p["id"].startswith("local:") for p in snap_loaded["providers"])

        loop.run_until_complete(
            gw._handle_unload_local_model("session_iris", "client_iris", {})
        )
        snap_unloaded = build_inference_snapshot(router)
        assert not any(p["id"].startswith("local:") for p in snap_unloaded["providers"]), (
            "reconnect re-fetch must not resurrect an unloaded local provider"
        )


class TestMissingKeyNotCrash:
    def test_generate_raises_provider_not_ready_not_invalid_header(self, monkeypatch):
        """T10: binding reasoning to an API provider with no key must raise
        ProviderNotReadyError (typed, catchable), NOT httpx.InvalidHeader."""
        reg = ProviderRegistry()
        reg.add(ProviderInstance(id="cerebras", label="Cerebras",
                                 kind=ProviderKind.API, model="gemma-4-31b",
                                 api_base_url="https://api.cerebras.ai/v1"))
        router = InferenceRouter.__new__(InferenceRouter)
        object.__setattr__(router, "_registry", reg)
        object.__setattr__(router, "_roles", RoleBindingTable(reg))
        object.__setattr__(router, "_default_role", "reasoning")
        object.__setattr__(router, "_transports", {})
        object.__setattr__(router, "_inprocess_mgr", None)
        router.bind_role("reasoning", "cerebras")

        monkeypatch.setattr(
            "backend.agent.inference.router.get_secret", lambda pid: None
        )

        with pytest.raises(ProviderNotReadyError) as excinfo:
            router.generate(
                "reasoning",
                [{"role": "user", "content": "hi"}],
            )
        assert excinfo.value.details["reason"] == "missing_api_key"
        assert excinfo.value.code.value == 1005
