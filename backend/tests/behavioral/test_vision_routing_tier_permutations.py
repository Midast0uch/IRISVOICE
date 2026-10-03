"""Behavioral (T12, Wave 5): vision-tier resolution under the single-server
architecture — specs/vision-single-server.

The old ladder/spawn permutations (VRAM size-select, no-fit fail lines) tested
the DELETED spawn path. What remains is the tier hierarchy exercised through
the REAL ``InferenceRouter.resolve_vision_provider()`` with the tier-3 borrow
discovery stubbed at its boundary (``_discover_reusable_vision_server``):

  P1. multimodal API brain -> tier 1 answers; discovery never runs.
  P2. no vision anywhere, borrowable shared server -> tier 3 borrows it:
      provider_id="shared_vision_server", requires_load=False, takes_lease=False.
  P3. no vision anywhere, NOTHING borrowable -> VisionModelUnavailable raised
      loudly (REQ-3 AC4 style: named, propagated, never a silent degrade).
  P4. local brain with projector (vision_loaded=True) -> tier 1 answers; a
      local provider takes a lease (Decisions Locked 8 — unchanged).

Off the resolution path, everything is real. On it, only the NETWORK probe is
stubbed — the hierarchy walk, the rule table, the fail-loud behavior are all
production code. No GPU, no network, no real model loads.
"""
from __future__ import annotations

import pytest

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import InferenceRouter
from backend.tools.vision_provider import VisionModelUnavailable


def _router_with(*instances: ProviderInstance) -> InferenceRouter:
    """Build a router bypassing __init__ (no config load, no side effects)."""
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


def _stub_vram(monkeypatch, free_gb: float = 4.0) -> None:
    monkeypatch.setattr(
        "backend.agent.inference.router._free_vram_gb", lambda: free_gb
    )


# ---------------------------------------------------------------------------
# P1 — multimodal brain answers in place; tier-3 discovery never consulted
# ---------------------------------------------------------------------------


def test_tier1_multimodal_brain_short_circuits_before_discovery(monkeypatch):
    _stub_vram(monkeypatch)
    discovery_calls: list = []
    monkeypatch.setattr(
        "backend.tools.vision_provider._discover_reusable_vision_server",
        lambda base_url="": discovery_calls.append(base_url) or "http://should-not-be-used/v1",
    )
    brain = ProviderInstance(
        id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-4o"
    )
    router = _router_with(brain)
    router.roles.bind("reasoning", "openai")

    res = router.resolve_vision_provider()

    assert res.tier == "brain"
    assert res.provider_id == "openai"
    assert res.requires_load is False
    assert res.takes_lease is False
    assert discovery_calls == [], "tier 1 answered; borrow discovery must not run"


# ---------------------------------------------------------------------------
# P2 — nobody sees, shared server borrowable -> tier 3 borrows it
# ---------------------------------------------------------------------------


def test_tier3_borrows_shared_server_without_load_or_lease(monkeypatch):
    _stub_vram(monkeypatch)
    monkeypatch.setattr(
        "backend.tools.vision_provider._discover_reusable_vision_server",
        lambda base_url="": "http://127.0.0.1:8082/v1",
    )
    brain = ProviderInstance(
        id="cohere", label="Cohere", kind=ProviderKind.API, model="command-r-plus"
    )
    tool = ProviderInstance(
        id="deepseek", label="DeepSeek", kind=ProviderKind.API, model="deepseek-chat"
    )
    router = _router_with(brain, tool)
    router.roles.bind("reasoning", "cohere")
    router.roles.bind("tool_execution", "deepseek")

    res = router.resolve_vision_provider()

    assert res.tier == "fallback"
    assert res.provider_id == "shared_vision_server"
    assert res.requires_load is False, "the shared server is already running"
    assert res.takes_lease is False, "we never own the shared server's lifecycle"
    assert res.model_path is None and res.mmproj_path is None


# ---------------------------------------------------------------------------
# P3 — nobody sees, nothing borrowable -> fail LOUDLY
# ---------------------------------------------------------------------------


def test_tier3_nothing_borrowable_fails_loudly(monkeypatch):
    _stub_vram(monkeypatch)
    monkeypatch.setattr(
        "backend.tools.vision_provider._discover_reusable_vision_server",
        lambda base_url="": None,
    )
    # V5 (2026-10-02): tier 3 also answers when the chosen vision model can be
    # autoloaded. "Nothing borrowable" here also means "nothing loadable" -
    # this machine has a real pin and an empty slot.
    monkeypatch.setattr(
        "backend.tools.vision_provider.vision_autoload_possible", lambda: False,
    )
    router = _router_with()

    with pytest.raises(VisionModelUnavailable) as exc_info:
        router.resolve_vision_provider()

    msg = str(exc_info.value)
    assert "shared multimodal server" in msg  # the reason is named


def test_tier3_discovery_error_also_fails_loudly(monkeypatch):
    """A discovery exception (bad config read, etc.) must surface as
    VisionModelUnavailable too — it is the same user-facing reality: no
    verified multimodal server."""
    _stub_vram(monkeypatch)

    def _boom(base_url=""):
        raise RuntimeError("config read exploded")

    monkeypatch.setattr(
        "backend.tools.vision_provider._discover_reusable_vision_server", _boom
    )
    router = _router_with()

    with pytest.raises(VisionModelUnavailable):
        router.resolve_vision_provider()


# ---------------------------------------------------------------------------
# P4 — local brain with projector answers at tier 1, lease still applies
# ---------------------------------------------------------------------------


def test_tier4_local_brain_with_projector_answers_directly(monkeypatch):
    _stub_vram(monkeypatch)
    discovery_calls: list = []
    monkeypatch.setattr(
        "backend.tools.vision_provider._discover_reusable_vision_server",
        lambda base_url="": discovery_calls.append(base_url) or None,
    )
    brain = ProviderInstance(
        id="local:gemma", label="Gemma 4 E4B (local)", kind=ProviderKind.LOCAL_OPENAI,
        model="gemma-4-E4B", loaded=True, vision_loaded=True,
    )
    router = _router_with(brain)
    router.roles.bind("reasoning", "local:gemma")

    res = router.resolve_vision_provider()

    assert res.tier == "brain"
    assert res.provider_id == "local:gemma"
    assert res.requires_load is False
    assert res.takes_lease is True  # LOCAL provider: Decisions Locked 8 unchanged
    assert discovery_calls == []


# ---------------------------------------------------------------------------
# REQ-2 edge case: dangling role binding never breaks the walk
# ---------------------------------------------------------------------------


def test_dangling_role_binding_raises_for_real_and_hierarchy_continues(monkeypatch):
    _stub_vram(monkeypatch)
    monkeypatch.setattr(
        "backend.tools.vision_provider._discover_reusable_vision_server",
        lambda base_url="": "http://127.0.0.1:8082/v1",
    )
    tool = ProviderInstance(
        id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-4o"
    )
    router = _router_with(tool)
    router.roles.bind("reasoning", "cerebras-ghost")  # never registered
    router.roles.bind("tool_execution", "openai")

    with pytest.raises(RuntimeError):
        router.resolve("reasoning")  # sanity: the dangling binding really raises

    res = router.resolve_vision_provider()

    assert res.tier == "tool"
    assert res.provider_id == "openai"
