"""Contract: the vision server is never owned, so it is never killed.

specs/vision-single-server REQ-2: the standalone llama-server spawn path is
DELETED. This file used to pin the owned-server lease lifecycle (lease blocks
idle-stop; stop kills only the tracked PID). Those concepts no longer exist —
the guards that remain are STRUCTURAL: the module contains no lease symbols
and no process-kill surface at all, and the borrowed server is cleared from
the reuse selection rather than stopped.

The tier lease semantics (Decisions Locked 8 of specs/unified-vision-routing)
still apply to tiers 1/2; tier 3 is now explicitly lease-free.
"""

from __future__ import annotations

import backend.agent.inference.router as router_mod
from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import InferenceRouter
from backend.tools import lfm_vl_provider as vl


def _router_with(*instances):
    reg = ProviderRegistry()
    for inst in instances:
        reg.add(inst)
    router = InferenceRouter.__new__(InferenceRouter)
    object.__setattr__(router, "_registry", reg)
    object.__setattr__(router, "_roles", RoleBindingTable(reg))
    object.__setattr__(router, "_default_role", None)
    object.__setattr__(router, "_transports", {})
    object.__setattr__(router, "_inprocess_mgr", None)
    return router


class TestNoOwnedServerSurface:
    def test_lease_symbols_gone(self):
        for sym in (
            "VisionLease",
            "acquire_vision_lease",
            "has_active_lease",
            "_VISION_LEASES",
            "_VISION_SERVER_PID",
        ):
            assert getattr(vl, sym, None) is None, sym

    def test_kill_surface_gone(self):
        for sym in ("_stop_owned_vision_server", "_kill_process_tree", "_kill_pid"):
            assert getattr(vl, sym, None) is None, sym

    def test_disable_never_kills(self):
        """disable() is pure state reset. Call it in a dirty state; the only
        observable effect is the reuse selection clearing."""
        vl._reused_vision_base_url = "http://borrowed.example/v1"
        vl._reused_vision_model = "whatever"
        vl.get_lfm_vl_provider().disable()
        assert vl._reused_vision_base_url is None


class TestTakesLeaseFollowsLocalVsRemoteAtEveryTier:
    def test_local_brain_tier1_takes_lease(self, monkeypatch):
        monkeypatch.setattr("backend.agent.inference.router._free_vram_gb", lambda: 4.0)
        brain = ProviderInstance(
            id="local:gemma", label="local", kind=ProviderKind.LOCAL_OPENAI,
            model="gemma-4-E4B", vision_loaded=True,
        )
        router = _router_with(brain)
        router.roles.bind("reasoning", "local:gemma")

        res = router.resolve_vision_provider()

        assert res.tier == "brain"
        assert res.takes_lease is True

    def test_local_tool_tier2_takes_lease(self, monkeypatch):
        monkeypatch.setattr("backend.agent.inference.router._free_vram_gb", lambda: 4.0)
        brain = ProviderInstance(
            id="cohere", label="Cohere", kind=ProviderKind.API, model="command-r-plus"
        )
        tool = ProviderInstance(
            id="local:gemma", label="local", kind=ProviderKind.INPROCESS,
            model="gemma-4-E4B", vision_loaded=True,
        )
        router = _router_with(brain, tool)
        router.roles.bind("reasoning", "cohere")
        router.roles.bind("tool_execution", "local:gemma")

        res = router.resolve_vision_provider()

        assert res.tier == "tool"
        assert res.takes_lease is True

    def test_fallback_tier3_takes_no_lease(self, monkeypatch):
        """specs/vision-single-server: tier 3 is borrow-only; the shared
        multimodal server is never ours, so takes_lease is False."""
        monkeypatch.setattr("backend.agent.inference.router._free_vram_gb", lambda: 4.0)
        router = _router_with()
        monkeypatch.setattr(
            "backend.tools.lfm_vl_provider._discover_reusable_vision_server",
            lambda base_url="": "http://127.0.0.1:8082/v1",
        )

        res = router.resolve_vision_provider()

        assert res.tier == "fallback"
        assert res.takes_lease is False

    def test_remote_brain_tier1_takes_no_lease(self, monkeypatch):
        monkeypatch.setattr("backend.agent.inference.router._free_vram_gb", lambda: 4.0)
        brain = ProviderInstance(
            id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-4o"
        )
        router = _router_with(brain)
        router.roles.bind("reasoning", "openai")

        res = router.resolve_vision_provider()

        assert res.tier == "brain"
        assert res.takes_lease is False

    def test_remote_tool_tier2_takes_no_lease(self, monkeypatch):
        monkeypatch.setattr("backend.agent.inference.router._free_vram_gb", lambda: 4.0)
        brain = ProviderInstance(
            id="cohere", label="Cohere", kind=ProviderKind.API, model="command-r-plus"
        )
        tool = ProviderInstance(
            id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-4o"
        )
        router = _router_with(brain, tool)
        router.roles.bind("reasoning", "cohere")
        router.roles.bind("tool_execution", "openai")

        res = router.resolve_vision_provider()

        assert res.tier == "tool"
        assert res.takes_lease is False
