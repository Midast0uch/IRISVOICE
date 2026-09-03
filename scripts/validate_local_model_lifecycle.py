#!/usr/bin/env python3
"""
Standing CDD harness for specs/local-model-lifecycle-sync.

Run on every build:  python scripts/validate_local_model_lifecycle.py
Exits non-zero if any assertion fails.

Replays a load -> unload trace through the REAL IRISGateway handlers and
asserts the contracts + behaviors from design.md:
  CT-4  ApiHttpxTransport never emits `Authorization: Bearer ` (empty).
  CT-5  API provider with no key resolves to {ok:false, reason:missing_api_key}
        and _build_transport raises ProviderNotReadyError.
  B-1   Unload converges without a refresh: provider removed from registry,
        manager is_loaded()==False, local_model_status {loaded:false} broadcast
        to the SESSION.
  B-2   Reconnect snapshot (build_inference_snapshot) no longer lists the local
        provider after unload.
  B-4   Unload frees VRAM (manager is_loaded()==False).
"""

import asyncio
import sys
import traceback
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.agent.exceptions import ProviderNotReadyError  # noqa: E402
from backend.agent.inference.provider import ProviderInstance, ProviderKind  # noqa: E402
from backend.agent.inference.registry import ProviderRegistry  # noqa: E402
from backend.agent.inference.roles import RoleBindingTable  # noqa: E402
from backend.agent.inference.router import InferenceRouter  # noqa: E402
from backend.agent.inference.snapshot import build_inference_snapshot  # noqa: E402
from backend.agent.inference.transport import ApiHttpxTransport  # noqa: E402
from backend.iris_gateway import IRISGateway  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


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
    ENDPOINT = "http://127.0.0.1:8082/v1"

    def __init__(self):
        self._loaded = False
        self._model_path = None
        self._llm = None

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
        self._llm = object()
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


def _make_router():
    reg = ProviderRegistry()
    router = InferenceRouter.__new__(InferenceRouter)
    object.__setattr__(router, "_registry", reg)
    object.__setattr__(router, "_roles", RoleBindingTable(reg))
    object.__setattr__(router, "_default_role", "reasoning")
    object.__setattr__(router, "_transports", {})
    object.__setattr__(router, "_inprocess_mgr", None)
    return router


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_bearer_never_empty():
    print("CT-4  Bearer never empty")
    captured = {}

    def _fake_stream(self, url, headers, body, model, messages, chunk_callback, reasoning_callback=None):
        captured["headers"] = headers
        return ("", "", [])

    with patch.object(ApiHttpxTransport, "_stream", _fake_stream):
        t = ApiHttpxTransport(api_base_url="https://api.cerebras.ai/v1", api_key="")
        t.generate("gemma-4-31b", [{"role": "user", "content": "hi"}], chunk_callback=lambda s: None)
    check("empty key omits Authorization header", "Authorization" not in captured["headers"])

    with patch.object(ApiHttpxTransport, "_stream", _fake_stream):
        t = ApiHttpxTransport(api_base_url="https://api.cerebras.ai/v1", api_key="  sk-test  ")
        t.generate("gemma-4-31b", [{"role": "user", "content": "hi"}], chunk_callback=lambda s: None)
    check("real key sets Bearer header", captured["headers"].get("Authorization") == "Bearer sk-test")


def test_missing_key_fails_closed():
    print("CT-5  Missing API key fails closed")
    reg = ProviderRegistry()
    reg.add(ProviderInstance(id="cerebras", label="Cerebras", kind=ProviderKind.API,
                             model="gemma-4-31b", api_base_url="https://api.cerebras.ai/v1"))
    router = InferenceRouter.__new__(InferenceRouter)
    object.__setattr__(router, "_registry", reg)
    object.__setattr__(router, "_roles", RoleBindingTable(reg))
    object.__setattr__(router, "_default_role", "reasoning")
    object.__setattr__(router, "_transports", {})
    object.__setattr__(router, "_inprocess_mgr", None)
    router.bind_role("reasoning", "cerebras")

    with patch("backend.agent.inference.router.get_secret", lambda pid: None):
        health = router.health_check_provider("reasoning")
        check("health reports missing_api_key", health.get("reason") == "missing_api_key")
        try:
            router._build_transport(router.resolve("reasoning"))
            check("_build_transport raises ProviderNotReadyError", False, "did not raise")
        except ProviderNotReadyError as e:
            check("_build_transport raises ProviderNotReadyError",
                  e.details.get("reason") == "missing_api_key")


def test_lifecycle_convergence():
    print("B-1/B-2/B-4  Lifecycle convergence")
    router = _make_router()
    ws = _FakeWSManager()
    gw = IRISGateway(ws_manager=ws)
    mgr = _FakeLocalModelManager()
    kernel = _FakeKernel(router)

    with patch("backend.agent.local_model_manager.get_local_model_manager", lambda: mgr), \
         patch("backend.agent.get_agent_kernel", lambda session_id=None: kernel), \
         patch("backend.iris_config.load_config",
               lambda: type("C", (), {"inference": type("I", (), {})()})()), \
         patch("backend.iris_config.save_config", lambda cfg: None):
        _run(gw._handle_load_local_model(
            "session_iris", "client_iris",
            {"payload": {"model_path": "/models/qwen3-9b.gguf"}},
        ))
        check("load registers local:* provider",
              any(i.id.startswith("local:") for i in router.registry.list()))

        _run(gw._handle_unload_local_model("session_iris", "client_iris", {}))
        check("B-4 unload clears manager", mgr.is_loaded() is False)
        check("unload removes local:* provider",
              not any(i.id.startswith("local:") for i in router.registry.list()))

        session_status = [
            m for (sid, m) in ws.broadcasts
            if sid == "session_iris" and m.get("type") == "local_model_status"
        ]
        check("B-1 unload broadcasts loaded:false to session",
              bool(session_status) and session_status[-1]["payload"]["loaded"] is False)

        snap = build_inference_snapshot(router)
        check("B-2 reconnect snapshot has no local provider",
              not any(p["id"].startswith("local:") for p in snap["providers"]))


def main():
    print("=== validate_local_model_lifecycle.py ===")
    try:
        test_bearer_never_empty()
        test_missing_key_fails_closed()
        test_lifecycle_convergence()
    except Exception:
        traceback.print_exc()
        FAILURES.append("unhandled exception")

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        sys.exit(1)
    print("ALL CHECKS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()