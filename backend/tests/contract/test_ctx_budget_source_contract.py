"""Contract CT-B1 + CT-B2: budget source locked to the ACTIVE binding.

REQ-1 (design CT-B1/CT-B2):
  - CT-B1: the DER budget context window must be resolved from the
    InferenceRouter's ACTIVE reasoning binding — not from stale legacy
    kernel fields. The router getters that expose the binding
    (``resolve()`` / ``health_check_provider()``) are pinned here so they
    cannot be removed or renamed.
  - CT-B2: when the active binding's model has no known window, the
    resolver MUST degrade loudly: source tag == "default" AND a WARN log
    naming provider+model+source. A silent fallback is a contract break
    (the 256k->8192 collapse case must never be invisible).
"""
from __future__ import annotations

import logging

import pytest

from backend.agent import agent_kernel as _ak
from backend.agent.inference.registry import _REGISTRY as _REG  # noqa: F401 (reset pattern)
from backend.agent.inference.roles import _ROLES as _R  # noqa: F401
from backend.agent.inference.router import InferenceRouter
from backend.iris_config import InferenceConfig, ProviderEntry

import backend.agent.inference.registry as _reg_mod
import backend.agent.inference.roles as _roles_mod


def _fresh_registry():
    _reg_mod._REGISTRY = None
    _roles_mod._ROLES = None


def _router_with(provider_id: str, model: str, kind: str = "API") -> InferenceRouter:
    cfg = InferenceConfig()
    cfg.providers = {
        provider_id: ProviderEntry(
            id=provider_id,
            label=provider_id,
            kind=kind,
            model=model,
            endpoint="https://localhost:9/test",
            cred_ref=provider_id,
        )
    }
    return InferenceRouter(cfg)


def _stub_kernel(router) -> _ak.AgentKernel:
    """Kernel with STALE/empty legacy fields — the exact case that used to
    collapse the window. Only the router carries the truth."""
    k = _ak.AgentKernel.__new__(_ak.AgentKernel)
    k._model_provider = ""  # stale/never written
    k._selected_reasoning_model = ""  # stale/never written
    k._context_window_overrides = {}
    k._router = router
    return k


# ---------------------------------------------------------------------------
# CT-B1: active-binding getters are the budget source
# ---------------------------------------------------------------------------

def test_ctb1_resolve_exposes_active_binding():
    """``resolve("reasoning")`` returns the bound instance (id/model/kind)
    that the kernel resolver consumes — the getter cannot be removed."""
    _fresh_registry()
    router = _router_with("cerebras", "gemma-4-31b")
    router.bind_role("reasoning", "cerebras")
    inst = router.resolve("reasoning")
    assert inst is not None
    assert inst.id == "cerebras"
    assert inst.model == "gemma-4-31b"
    assert getattr(inst, "kind", None) is not None


def test_ctb1_health_check_provider_shape():
    """``health_check_provider("reasoning")`` returns the pinned dict shape
    (ok/provider/model/error) used by the gateway pre-flight."""
    _fresh_registry()
    router = _router_with("cerebras", "gemma-4-31b")
    router.bind_role("reasoning", "cerebras")
    hc = router.health_check_provider("reasoning")
    assert set(hc) >= {"ok", "provider", "model", "error"}
    assert hc["provider"] == "cerebras"
    assert hc["model"] == "gemma-4-31b"


def test_ctb1_budget_funded_from_binding_not_legacy_fields():
    """Stale/empty legacy kernel fields must NOT collapse the window when an
    active binding exists. (The exact 256k->8192 regression case.)"""
    _fresh_registry()
    router = _router_with("cerebras", "gemma-4-31b")
    router.bind_role("reasoning", "cerebras")
    w = _stub_kernel(router).resolve_context_window_with_source()
    assert w.source in ("table", "authoritative"), f"got {w.source}"
    # cerebras gemma-4-31b is a 256k model; even the conservative table path
    # must fund far above the 8192 collapse floor.
    assert w.tokens >= 32_000, f"window collapsed to {w.tokens}"


def test_ctb1_set_role_binding_syncs_provider():
    """REQ-1 AC2: binding a role must keep the legacy provider field in sync
    so downstream legacy readers agree with actual routing."""
    _fresh_registry()
    router = _router_with("cerebras", "gemma-4-31b")
    k = _ak.AgentKernel.__new__(_ak.AgentKernel)
    k._router = router
    k._selected_reasoning_model = None
    k._model_provider = None
    ok = k.set_role_binding("reasoning", "cerebras")
    assert ok is True
    assert k._model_provider == "cerebras", f"got {k._model_provider!r}"


# ---------------------------------------------------------------------------
# CT-B2: unresolved window degrades LOUDLY (source tag + WARN)
# ---------------------------------------------------------------------------

def test_ctb2_unknown_model_tags_default_and_warns(caplog):
    """Unknown model -> source tag "default", 8192 fallback, AND a WARN log
    naming provider+model+source. Silent fallback is a contract break."""
    _fresh_registry()
    router = _router_with("cerebras", "totally-unknown-model-99")
    router.bind_role("reasoning", "cerebras")
    with caplog.at_level(logging.WARNING, logger="backend.agent.agent_kernel"):
        w = _stub_kernel(router).resolve_context_window_with_source()
    assert w.source == "default", f"got {w.source}"
    assert w.tokens == 8_192, f"got {w.tokens}"
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("source=default" in r.getMessage() for r in warns), "no WARN with source tag"
    joined = " ".join(r.getMessage() for r in warns)
    assert "cerebras" in joined, "WARN must name the provider"
    assert "totally-unknown-model-99" in joined, "WARN must name the model"


def test_ctb2_unbound_role_falls_back_loudly(caplog):
    """No binding at all -> conservative default with a WARN, never a crash
    and never a silently-wrong window."""
    _fresh_registry()
    router = _router_with("cerebras", "gemma-4-31b")  # nothing bound
    with caplog.at_level(logging.WARNING, logger="backend.agent.agent_kernel"):
        w = _stub_kernel(router).resolve_context_window_with_source()
    assert w.source == "default"
    assert w.tokens == 8_192
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warns, "unbound role must degrade loudly (WARN)"
