"""Unit tests for T5 (`supports_vision`) and T6 (`resolve_vision_provider`),
specs/unified-vision-routing REQ-1, REQ-2, REQ-9, Decisions Locked 8.

No network, no GPU, no real model loads — every `ProviderInstance` is faked
and every external dependency (`_find_vision_model`, `get_hardware_info`,
`httpx`) is monkeypatched.
"""

from __future__ import annotations

import pytest

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import (
    InferenceRouter,
    VisionResolution,
    supports_vision,
)


def _router_with(*instances: ProviderInstance) -> InferenceRouter:
    """Build a router bypassing __init__ (no config load, no side effects) —
    mirrors the pattern used by test_build_inference_snapshot.py and
    test_provider_instance_vision_loaded_additive.py."""
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


def _no_op_free_vram(monkeypatch):
    """Every hierarchy test is indifferent to the real VRAM figure — stub it
    so no real hardware probe (nvidia-smi / torch) runs during a unit test."""
    monkeypatch.setattr(
        "backend.agent.inference.router._free_vram_gb", lambda: 4.2
    )


# ---------------------------------------------------------------------------
# T5 — supports_vision(instance)
# ---------------------------------------------------------------------------


class TestSupportsVisionAPI:
    def test_known_vision_model_true(self):
        inst = ProviderInstance(
            id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-4o"
        )
        assert supports_vision(inst) is True

    def test_unknown_model_false(self):
        inst = ProviderInstance(
            id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-3.5-turbo"
        )
        assert supports_vision(inst) is False

    def test_unknown_provider_false(self):
        inst = ProviderInstance(
            id="totally-unknown-vendor", label="?", kind=ProviderKind.API, model="gpt-4o"
        )
        assert supports_vision(inst) is False

    def test_no_model_set_false(self):
        inst = ProviderInstance(
            id="openai", label="OpenAI", kind=ProviderKind.API, model=None
        )
        assert supports_vision(inst) is False


class TestSupportsVisionLocal:
    """LOCAL_OPENAI / INPROCESS: ONLY vision_loaded — NEVER disk presence."""

    @pytest.mark.parametrize("kind", [ProviderKind.LOCAL_OPENAI, ProviderKind.INPROCESS])
    def test_vision_loaded_true(self, kind):
        inst = ProviderInstance(
            id="local:gemma", label="local", kind=kind, model="gemma-4-E4B",
            vision_loaded=True,
        )
        assert supports_vision(inst) is True

    @pytest.mark.parametrize("kind", [ProviderKind.LOCAL_OPENAI, ProviderKind.INPROCESS])
    def test_vision_loaded_false_even_with_mmproj_named_model(self, kind):
        """A model whose NAME suggests a projector exists on disk must still
        report False when vision_loaded was never set — disk presence is
        never a signal (REQ-1 AC3)."""
        inst = ProviderInstance(
            id="local:gemma", label="local", kind=kind, model="gemma-4-E4B",
            vision_loaded=False,
        )
        assert supports_vision(inst) is False

    def test_default_vision_loaded_false(self):
        inst = ProviderInstance(
            id="local:qwen", label="local", kind=ProviderKind.LOCAL_OPENAI, model="qwen3-9b",
        )
        assert supports_vision(inst) is False


class TestSupportsVisionOllama:
    def test_capable_model_true(self, monkeypatch):
        class _FakeResp:
            status_code = 200

            def json(self):
                return {"capabilities": ["completion", "vision"]}

        class _FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, url, json):
                return _FakeResp()

        monkeypatch.setattr(
            "httpx.Client", lambda *a, **kw: _FakeClient()
        )
        inst = ProviderInstance(
            id="ollama", label="Ollama", kind=ProviderKind.OLLAMA, model="llama3.2-vision",
        )
        assert supports_vision(inst) is True

    def test_incapable_model_false(self, monkeypatch):
        class _FakeResp:
            status_code = 200

            def json(self):
                return {"capabilities": ["completion"]}

        class _FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, url, json):
                return _FakeResp()

        monkeypatch.setattr("httpx.Client", lambda *a, **kw: _FakeClient())
        inst = ProviderInstance(
            id="ollama", label="Ollama", kind=ProviderKind.OLLAMA, model="llama3.1",
        )
        assert supports_vision(inst) is False

    def test_unreachable_returns_false_never_raises(self, monkeypatch):
        class _RaisingClient:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, url, json):
                raise ConnectionError("no daemon listening (test double)")

        monkeypatch.setattr("httpx.Client", lambda *a, **kw: _RaisingClient())
        inst = ProviderInstance(
            id="ollama", label="Ollama", kind=ProviderKind.OLLAMA, model="llama3.1",
        )
        assert supports_vision(inst) is False

    def test_no_model_false(self):
        inst = ProviderInstance(
            id="ollama", label="Ollama", kind=ProviderKind.OLLAMA, model=None,
        )
        assert supports_vision(inst) is False


class TestSupportsVisionUnrecognisedKind:
    """CT-1: a kind this function does not recognise must return False, never
    raise. ProviderKind is a real Enum so we cannot add a member to it — a
    plain object standing in for "some future kind" exercises the same
    code path (the `else: return False` branch)."""

    def test_unrecognised_kind_returns_false_no_raise(self):
        class _FakeInstance:
            id = "future-provider"
            kind = "quantum-tunneling-transport"  # not any real ProviderKind
            model = "gpt-4o"
            vision_loaded = True

        assert supports_vision(_FakeInstance()) is False

    def test_none_instance_returns_false(self):
        assert supports_vision(None) is False


# ---------------------------------------------------------------------------
# T6 — resolve_vision_provider()
# ---------------------------------------------------------------------------


class TestResolveVisionProviderHierarchy:
    def test_brain_sees_returns_brain_tier_no_load(self, monkeypatch):
        _no_op_free_vram(monkeypatch)
        brain = ProviderInstance(
            id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-4o"
        )
        router = _router_with(brain)
        router.roles.bind("reasoning", "openai")

        res = router.resolve_vision_provider()

        assert isinstance(res, VisionResolution)
        assert res.tier == "brain"
        assert res.provider_id == "openai"
        assert res.requires_load is False
        assert res.takes_lease is False  # remote API — no local process

    def test_tool_sees_returns_tool_tier_when_brain_cannot(self, monkeypatch):
        _no_op_free_vram(monkeypatch)
        brain = ProviderInstance(
            id="cohere", label="Cohere", kind=ProviderKind.API, model="command-r-plus"
        )
        tool = ProviderInstance(
            id="anthropic", label="Anthropic", kind=ProviderKind.API, model="claude-sonnet-5"
        )
        router = _router_with(brain, tool)
        router.roles.bind("reasoning", "cohere")
        router.roles.bind("tool_execution", "anthropic")

        res = router.resolve_vision_provider()

        assert res.tier == "tool"
        assert res.provider_id == "anthropic"
        assert res.requires_load is False
        assert res.takes_lease is False

    def test_neither_sees_falls_to_fallback(self, monkeypatch):
        _no_op_free_vram(monkeypatch)
        brain = ProviderInstance(
            id="cohere", label="Cohere", kind=ProviderKind.API, model="command-r-plus"
        )
        tool = ProviderInstance(
            id="deepseek", label="DeepSeek", kind=ProviderKind.API, model="deepseek-chat"
        )
        router = _router_with(brain, tool)
        router.roles.bind("reasoning", "cohere")
        router.roles.bind("tool_execution", "deepseek")

        monkeypatch.setattr(
            "backend.tools.lfm_vl_provider._find_vision_model",
            lambda: ("/models/LFM2.5-VL-3B/model.gguf", "/models/LFM2.5-VL-3B/mmproj.gguf"),
        )

        res = router.resolve_vision_provider()

        assert res.tier == "fallback"
        assert res.provider_id == "lfm_vl_fallback"
        assert res.requires_load is True
        assert res.takes_lease is True  # fallback is always a local llama-server
        assert res.model_path == "/models/LFM2.5-VL-3B/model.gguf"
        assert res.mmproj_path == "/models/LFM2.5-VL-3B/mmproj.gguf"

    def test_fallback_when_no_vl_model_found(self, monkeypatch):
        """No VL model on disk -> fallback resolution still returns cleanly
        with no paths (T7 owns the hard-failure behavior; T6 only reports)."""
        _no_op_free_vram(monkeypatch)
        router = _router_with()
        monkeypatch.setattr(
            "backend.tools.lfm_vl_provider._find_vision_model", lambda: None
        )

        res = router.resolve_vision_provider()

        assert res.tier == "fallback"
        assert res.model_path is None
        assert res.mmproj_path is None

    def test_role_unbound_continues_down_hierarchy(self, monkeypatch):
        """Reasoning is unbound entirely (empty role table, no default) ->
        treated as no-vision, tool tier is tried next."""
        _no_op_free_vram(monkeypatch)
        tool = ProviderInstance(
            id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-4o"
        )
        router = _router_with(tool)
        router.roles.bind("tool_execution", "openai")
        # _default_role stays None (see _router_with) -> reasoning truly unbound.

        res = router.resolve_vision_provider()

        assert res.tier == "tool"
        assert res.provider_id == "openai"

    def test_resolve_raises_never_propagates(self, monkeypatch):
        """Both roles unbound and no default -> router.resolve() raises for
        BOTH tiers. resolve_vision_provider must swallow both and land on
        the fallback rather than propagate."""
        _no_op_free_vram(monkeypatch)
        router = _router_with()  # empty registry, nothing bound, no default
        monkeypatch.setattr(
            "backend.tools.lfm_vl_provider._find_vision_model", lambda: None
        )

        res = router.resolve_vision_provider()  # must not raise

        assert res.tier == "fallback"

    def test_same_provider_both_roles_returned_once(self, monkeypatch):
        """Both reasoning and tool_execution bound to the SAME multimodal
        provider -> a single VisionResolution, tier='brain' (brain tier wins
        the hierarchy and the tool tier is never separately evaluated)."""
        _no_op_free_vram(monkeypatch)
        shared = ProviderInstance(
            id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-4o"
        )
        router = _router_with(shared)
        router.roles.bind("reasoning", "openai")
        router.roles.bind("tool_execution", "openai")

        res = router.resolve_vision_provider()

        assert res.tier == "brain"
        assert res.provider_id == "openai"


class TestResolveVisionProviderLease:
    """Decisions Locked 8: a LOCAL provider serving vision takes a lease at
    ANY tier; a REMOTE provider takes none — at every tier."""

    def test_local_brain_takes_lease(self, monkeypatch):
        _no_op_free_vram(monkeypatch)
        brain = ProviderInstance(
            id="local:gemma", label="local", kind=ProviderKind.LOCAL_OPENAI,
            model="gemma-4-E4B", vision_loaded=True,
        )
        router = _router_with(brain)
        router.roles.bind("reasoning", "local:gemma")

        res = router.resolve_vision_provider()

        assert res.tier == "brain"
        assert res.takes_lease is True

    def test_local_tool_takes_lease(self, monkeypatch):
        _no_op_free_vram(monkeypatch)
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

    def test_remote_brain_takes_no_lease(self, monkeypatch):
        _no_op_free_vram(monkeypatch)
        brain = ProviderInstance(
            id="anthropic", label="Anthropic", kind=ProviderKind.API, model="claude-sonnet-5"
        )
        router = _router_with(brain)
        router.roles.bind("reasoning", "anthropic")

        res = router.resolve_vision_provider()

        assert res.takes_lease is False

    def test_remote_ollama_tool_takes_no_lease(self, monkeypatch):
        _no_op_free_vram(monkeypatch)
        brain = ProviderInstance(
            id="cohere", label="Cohere", kind=ProviderKind.API, model="command-r-plus"
        )
        tool = ProviderInstance(
            id="ollama", label="Ollama", kind=ProviderKind.OLLAMA, model="llama3.2-vision"
        )
        router = _router_with(brain, tool)
        router.roles.bind("reasoning", "cohere")
        router.roles.bind("tool_execution", "ollama")
        monkeypatch.setattr(
            "backend.agent.inference.router._supports_vision_ollama", lambda inst: True
        )

        res = router.resolve_vision_provider()

        assert res.tier == "tool"
        assert res.takes_lease is False

    def test_fallback_takes_lease(self, monkeypatch):
        _no_op_free_vram(monkeypatch)
        router = _router_with()
        monkeypatch.setattr(
            "backend.tools.lfm_vl_provider._find_vision_model",
            lambda: ("/models/LFM2.5-VL-450M/model.gguf", "/models/LFM2.5-VL-450M/mmproj.gguf"),
        )

        res = router.resolve_vision_provider()

        assert res.tier == "fallback"
        assert res.takes_lease is True
