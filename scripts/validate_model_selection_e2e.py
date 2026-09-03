#!/usr/bin/env python3
"""
Standing CDD harness for specs/model-selection-authority (T7/T8).

Run on every build:  python scripts/validate_model_selection_e2e.py
Exits non-zero if any assertion fails.

Drives the REAL IRISGateway handlers (confirm_card / set_model_selection /
set_role_binding / unload) through the REAL router + role table + config
round-trip, with fakes only for the heavy collaborators (WS manager, local
model manager, kernel shell). Zero API spend — no provider is ever called.

Asserts the authority-chain contracts + behaviors from design.md:
  A1  Explicit switch (confirm_card) rebinds + stamps + persists; next-turn
      routing resolves to the new provider.
  A2  Restart persistence: re-seeding a fresh router from the persisted config
      applies the NEWER record (flat vs bindings) and binds iff table empty.
  A3  Remount is a no-op: re-fetching the snapshot shows no drift and the
      frontend sends zero selection messages.
  A4  20-cycle soak: switch -> restart -> remount repeated 20x with no drift.
  A5  Unload of a bound local model falls back LOUDLY to the last API provider
      (rebind + authority log + user-facing message).
"""

import asyncio
import sys
import traceback
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.agent.inference.provider import ProviderInstance, ProviderKind  # noqa: E402
from backend.agent.inference.registry import ProviderRegistry  # noqa: E402
from backend.agent.inference.roles import RoleBindingTable  # noqa: E402
from backend.agent.inference.router import InferenceRouter  # noqa: E402
from backend.agent.inference.snapshot import build_inference_snapshot  # noqa: E402
from backend.iris_config import InferenceConfig, IRISConfig  # noqa: E402
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
    """Minimal kernel that binds on the router like the real AgentKernel.

    Mirrors the real set_model_selection / set_role_binding binding semantics
    (register provider + bind roles with a stamp) without the heavy AgentKernel
    construction. The gateway's confirm_card path calls these two methods.
    """

    def __init__(self, router):
        self._router = router

    def set_model_selection(self, reasoning_model=None, tool_execution_model=None,
                            model_provider=None, api_base_url=None, api_key=None,
                            preserve_bindings=False):
        import time as _t

        if not model_provider:
            return True
        from backend.agent.inference.provider import ProviderInstance, ProviderKind

        _kind = ProviderKind.API
        _inst = ProviderInstance(
            id=model_provider, label=model_provider, kind=_kind,
            model=reasoning_model or None,
            api_base_url=api_base_url or f"https://api.{model_provider}.ai/v1",
        )
        self._router.add_provider(_inst)
        if not preserve_bindings:
            _stamp = _t.time()
            self._router.bind_role("reasoning", _inst.id,
                                   model_override=reasoning_model, selected_at=_stamp)
            self._router.bind_role("tool_execution", _inst.id,
                                   model_override=tool_execution_model or reasoning_model,
                                   selected_at=_stamp)
        return True

    def set_role_binding(self, role, instance_id, model_override=None):
        import time as _t

        self._router.bind_role(role, instance_id, model_override=model_override,
                               selected_at=_t.time())
        return True

    def configure_openai_compat(self, *a, **k):
        pass

    def configure_inprocess_local(self, *a, **k):
        pass

    def __getattr__(self, _name):
        # Any other kernel method the gateway calls (configure_api, configure_vps,
        # set_launcher_mode, ...) is a no-op for this harness.
        return lambda *a, **k: None


def _make_router():
    reg = ProviderRegistry()
    router = InferenceRouter.__new__(InferenceRouter)
    object.__setattr__(router, "_registry", reg)
    object.__setattr__(router, "_roles", RoleBindingTable(reg))
    object.__setattr__(router, "_default_role", "reasoning")
    object.__setattr__(router, "_transports", {})
    object.__setattr__(router, "_inprocess_mgr", None)
    object.__setattr__(router, "_deferred_selection", None)
    return router


def _seed_providers(router):
    """Register the API providers the harness switches between."""
    for pid, model in (("cerebras", "gemma-4-31b"), ("cohere", "command-a-plus-05-2026")):
        router.add_provider(ProviderInstance(
            id=pid, label=pid, kind=ProviderKind.API, model=model,
            api_base_url=f"https://api.{pid}.ai/v1",
        ))


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _patch_kernel(kernel):
    """Return a context manager patching BOTH get_agent_kernel import sites.

    confirm_card imports from backend.agent.agent_kernel; the unload handler
    imports from backend.agent. Both must resolve to the fake kernel.
    """
    from unittest.mock import patch as _patch

    return (
        _patch("backend.agent.agent_kernel.get_agent_kernel",
               lambda session_id=None: kernel),
        _patch("backend.agent.get_agent_kernel",
               lambda session_id=None: kernel),
    )


def _apply_switch(gw, router, provider, model):
    """Drive confirm_card (the Dashboard APPLY path) to switch provider."""
    _run(gw.handle_message(
        "iris",
        {
            "type": "confirm_card",
            "payload": {
                "section_id": "model_selection",
                "values": {
                    "model_provider": provider,
                    "reasoning_model": model,
                    "tool_model": model,
                },
            },
        },
        session_id="session_iris",
    ))


def _snapshot_binding(router, role="reasoning"):
    for b in router.snapshot()["role_bindings"]:
        if b["role"] == role:
            return b
    return None


def _restart_seed(cfg_dict):
    """Simulate a backend restart: rebuild a fresh router from persisted config.

    Replicates main.py's boot restore: _apply_config seeds role_bindings
    (skip-if-bound), then the flat-newer check forces a rebind from the flat
    record when its stamp beats the bindings' stamp (the 09-03 inversion).
    """
    cfg = InferenceConfig.from_dict(cfg_dict)
    router = _make_router()
    _seed_providers(router)
    router._apply_config(cfg)

    # main.py boot restore: newer record wins, either direction.
    def _epoch(v):
        try:
            return float(v or 0.0)
        except (TypeError, ValueError):
            return 0.0

    _flat_stamp = _epoch(cfg.provider_selected_at)
    _bind_stamps = [
        _epoch(b.get("selected_at", 0.0))
        for b in (cfg.role_bindings or [])
        if isinstance(b, dict)
    ]
    _bindings_stamp = max(_bind_stamps) if _bind_stamps else 0.0
    _flat_newer = bool(_flat_stamp > 0.0 and _flat_stamp > _bindings_stamp)
    if _flat_newer:
        # Rebind from the flat record (preserve_bindings=False).
        _inst = router.registry.get(cfg.provider)
        if _inst is not None:
            router.bind_role("reasoning", _inst.id,
                             model_override=cfg.reasoning_model or None,
                             selected_at=_flat_stamp)
            router.bind_role("tool_execution", _inst.id,
                             model_override=cfg.tool_execution_model or cfg.reasoning_model or None,
                             selected_at=_flat_stamp)
    return router, cfg


def test_switch_takes_effect_and_persists():
    print("A1  Explicit switch rebinds + stamps + persists")
    router = _make_router()
    _seed_providers(router)
    ws = _FakeWSManager()
    gw = IRISGateway(ws_manager=ws)
    kernel = _FakeKernel(router)
    cfg_holder = {"cfg": IRISConfig()}

    def _fake_load():
        return cfg_holder["cfg"]

    def _fake_save(cfg):
        cfg_holder["cfg"] = cfg

    with _patch_kernel(kernel)[0], _patch_kernel(kernel)[1], \
         patch("backend.iris_config.load_config", _fake_load), \
         patch("backend.iris_config.save_config", _fake_save):
        # Pre-bind so the switch is a real switch (confirm_card persists only
        # on _provider_switch, not on first-time unbound binding).
        router.bind_role("reasoning", "cerebras", model_override="gemma-4-31b",
                         selected_at=1.0)
        router.bind_role("tool_execution", "cerebras", model_override="gemma-4-31b",
                         selected_at=1.0)
        _apply_switch(gw, router, "cohere", "command-a-plus-05-2026")

    b = _snapshot_binding(router)
    check("reasoning bound to cohere", b and b["instance_id"] == "cohere")
    check("binding carries a stamp", b and b.get("selected_at", 0.0) > 0.0)
    check("flat provider_selected_at persisted",
          cfg_holder["cfg"].inference.provider_selected_at > 0.0)
    check("role_bindings persisted with stamp",
          any(x.get("selected_at", 0.0) > 0.0
              for x in cfg_holder["cfg"].inference.role_bindings))

    # Next-turn routing resolves to the new provider.
    inst = router.resolve("reasoning")
    check("next-turn routing resolves to cohere", inst.id == "cohere")


def test_restart_applies_newer_record():
    print("A2  Restart applies newer record + binds iff empty")
    # Flat-newer wins (the 09-03 inversion): flat stamp > bindings stamp.
    cfg_dict = {
        "provider": "cohere",
        "provider_selected_at": 300.0,
        "role_bindings": [
            {"role": "reasoning", "instance_id": "cerebras",
             "model_override": "gemma-4-31b", "selected_at": 100.0},
        ],
    }
    router, _ = _restart_seed(cfg_dict)
    b = _snapshot_binding(router)
    check("flat-newer wins over stale bindings", b and b["instance_id"] == "cohere")

    # Bindings-newer wins (the 08-16 case): bindings stamp > flat stamp.
    cfg_dict2 = {
        "provider": "cerebras",
        "provider_selected_at": 100.0,
        "role_bindings": [
            {"role": "reasoning", "instance_id": "cohere",
             "model_override": "command-a-plus-05-2026", "selected_at": 300.0},
        ],
    }
    router2, _ = _restart_seed(cfg_dict2)
    b2 = _snapshot_binding(router2)
    check("bindings-newer wins over stale flat", b2 and b2["instance_id"] == "cohere")

    # Both-zero (pre-migration): legacy heuristic — flat treated as stale copy.
    cfg_dict3 = {
        "provider": "cerebras",
        "provider_selected_at": 0.0,
        "role_bindings": [
            {"role": "reasoning", "instance_id": "cohere",
             "model_override": "command-a-plus-05-2026", "selected_at": 0.0},
        ],
    }
    router3, _ = _restart_seed(cfg_dict3)
    b3 = _snapshot_binding(router3)
    check("both-zero keeps bindings (legacy heuristic)",
          b3 and b3["instance_id"] == "cohere")


def test_remount_is_noop():
    print("A3  Remount re-fetch shows no drift, zero sends")
    router = _make_router()
    _seed_providers(router)
    ws = _FakeWSManager()
    gw = IRISGateway(ws_manager=ws)
    kernel = _FakeKernel(router)
    cfg_holder = {"cfg": IRISConfig()}

    def _fake_load():
        return cfg_holder["cfg"]

    def _fake_save(cfg):
        cfg_holder["cfg"] = cfg

    with _patch_kernel(kernel)[0], _patch_kernel(kernel)[1], \
         patch("backend.iris_config.load_config", _fake_load), \
         patch("backend.iris_config.save_config", _fake_save):
        _apply_switch(gw, router, "cohere", "command-a-plus-05-2026")

    # Remount: re-fetch the snapshot (what useInferenceState does on mount).
    snap = build_inference_snapshot(router)
    b = next(x for x in snap["role_bindings"] if x["role"] == "reasoning")
    check("remount snapshot shows cohere", b["instance_id"] == "cohere")
    # A remount sends zero selection messages (frontend only sends on gesture).
    selection_msgs = [
        m for (_, m) in ws.sent
        if m.get("type") in ("set_model_selection", "set_role_binding", "confirm_card")
    ]
    check("remount sends zero selection messages", not selection_msgs)


def test_20_cycle_soak():
    print("A4  20-cycle soak: switch -> restart -> remount, no drift")
    for i in range(20):
        provider = "cohere" if i % 2 == 0 else "cerebras"
        model = "command-a-plus-05-2026" if i % 2 == 0 else "gemma-4-31b"
        prev_provider = "cerebras" if provider == "cohere" else "cohere"
        prev_model = "gemma-4-31b" if prev_provider == "cerebras" else "command-a-plus-05-2026"
        router = _make_router()
        _seed_providers(router)
        ws = _FakeWSManager()
        gw = IRISGateway(ws_manager=ws)
        kernel = _FakeKernel(router)
        cfg_holder = {"cfg": IRISConfig()}

        def _fake_load():
            return cfg_holder["cfg"]

        def _fake_save(cfg):
            cfg_holder["cfg"] = cfg

        with _patch_kernel(kernel)[0], _patch_kernel(kernel)[1], \
             patch("backend.iris_config.load_config", _fake_load), \
             patch("backend.iris_config.save_config", _fake_save):
            # Pre-bind to the OPPOSITE provider so the switch is real (persists).
            router.bind_role("reasoning", prev_provider, model_override=prev_model,
                             selected_at=1.0)
            router.bind_role("tool_execution", prev_provider, model_override=prev_model,
                             selected_at=1.0)
            _apply_switch(gw, router, provider, model)

        # Restart: rebuild from persisted config (the inference block).
        router2, _ = _restart_seed(cfg_holder["cfg"].inference.to_dict())
        b = _snapshot_binding(router2)
        if not (b and b["instance_id"] == provider):
            check(f"cycle {i}: restart preserved {provider}", False,
                  f"got {b}")
            return
        # Remount: re-fetch, no drift.
        snap = build_inference_snapshot(router2)
        b2 = next(x for x in snap["role_bindings"] if x["role"] == "reasoning")
        if b2["instance_id"] != provider:
            check(f"cycle {i}: remount preserved {provider}", False,
                  f"got {b2['instance_id']}")
            return
    check("20-cycle soak: no drift across switch/restart/remount", True)


def test_unload_loud_fallback():
    print("A5  Unload of bound local falls back LOUDLY to last API provider")
    router = _make_router()
    _seed_providers(router)
    router.add_provider(ProviderInstance(
        id="local:twil", label="Local: TwIL", kind=ProviderKind.LOCAL_OPENAI,
        model="TwIL-LM3-Q4_K_M.gguf", api_base_url="http://127.0.0.1:8082/v1",
        loaded=True,
    ))
    router.bind_role("reasoning", "local:twil", selected_at=10.0)
    router.bind_role("tool_execution", "local:twil", selected_at=10.0)

    ws = _FakeWSManager()
    gw = IRISGateway(ws_manager=ws)
    kernel = _FakeKernel(router)
    mgr = _FakeLocalModelManager()
    mgr._loaded = True
    mgr._model_path = "/models/TwIL-LM3-Q4_K_M.gguf"
    mgr._llm = object()

    cfg_holder = {"cfg": IRISConfig()}

    def _fake_load():
        return cfg_holder["cfg"]

    def _fake_save(cfg):
        cfg_holder["cfg"] = cfg

    with _patch_kernel(kernel)[0], _patch_kernel(kernel)[1], \
             patch("backend.agent.local_model_manager.get_local_model_manager", lambda: mgr), \
             patch("backend.iris_config.load_config", _fake_load), \
             patch("backend.iris_config.save_config", _fake_save):
        _run(gw._handle_unload_local_model("session_iris", "client_iris", {}))

    b = _snapshot_binding(router)
    check("local-bound role fell back to an API provider",
          b and b["instance_id"] == "cerebras")
    check("fallback rebind carries a fresh stamp",
          b and b.get("selected_at", 0.0) > 10.0)
    fallback_msgs = [
        m for (_, m) in ws.broadcasts
        if m.get("type") == "model_selection_fallback"
    ]
    check("user-facing fallback message broadcast",
          bool(fallback_msgs) and "unloaded" in fallback_msgs[-1]["payload"]["reason"])


def main():
    print("=== validate_model_selection_e2e.py ===")
    try:
        test_switch_takes_effect_and_persists()
        test_restart_applies_newer_record()
        test_remount_is_noop()
        test_20_cycle_soak()
        test_unload_loud_fallback()
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