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
    """Kernel whose ONLY model state is the router's binding.

    This used to also assign ``_model_provider = ""`` and
    ``_selected_reasoning_model = ""`` to stage the stale-legacy-field case that
    collapsed the window to 8192. Those two lines were removed on 2026-08-16
    when both names became read-only properties derived from the binding — the
    staged condition is no longer representable, so the setup could not run.

    Note this costs the CT-B1 cases below some discriminating power: they can no
    longer fail the specific way they were built to catch, because a legacy
    field can no longer disagree with the binding. They still verify that
    ``resolve_context_window_with_source`` funds the window from the binding.
    The assertions are unchanged.
    """
    k = _ak.AgentKernel.__new__(_ak.AgentKernel)
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
    # The two `k._selected_reasoning_model = None` / `k._model_provider = None`
    # staging lines were removed on 2026-08-16 — both are now read-only
    # properties. The assertion below is unchanged and still holds.
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


# ---------------------------------------------------------------------------
# CT-B3: every model brings its OWN window, and a switch re-resolves it
# ---------------------------------------------------------------------------
#
# The product claim is that IRIS is model-agnostic — the user switches between
# API providers and local models freely, from either the Brain or the Tool
# selector. Each of those models has a DIFFERENT context window, so the budget
# is only correct if it re-resolves on every switch. CT-B1/CT-B2 pin a single
# binding's window; nothing pinned that the window FOLLOWS a rebind.
#
# To be precise about what changed on 2026-08-16 and what did not: THIS resolver
# already consulted the router before the legacy fields (REQ-1 AC1), so the DER
# budget did follow a switch. What was missing was any test saying so — the
# behaviour rested on one function remembering to check the router first, and a
# refactor could have dropped that branch silently.
#
# What the derived properties changed is the ~45 OTHER readers of
# `_selected_reasoning_model` / `_model_provider` across the backend, none of
# which had a router-first branch. Those read a stored field that the gateway's
# role-binding path never wrote, so after a switch they saw the startup model.
# Now every reader resolves the binding, and this contract pins the property for
# the resolver that matters most.

@pytest.mark.parametrize(
    "provider, model, expected_tokens, expected_source",
    [
        ("cerebras", "gemma-4-31b", 256_000, "table"),
        ("cohere", "command-r-plus-08-2024", 128_000, "table"),
        ("openai", "gpt-4", 8_192, "table"),
        ("mistral", "mistral-large-latest", 128_000, "table"),
        ("groq", "mixtral-8x7b-32768", 32_768, "table"),
    ],
)
def test_ctb3_each_model_resolves_its_own_window(
    provider, model, expected_tokens, expected_source
):
    """A model's window comes from ITS OWN (provider, model) entry."""
    _fresh_registry()
    router = _router_with(provider, model)
    router.bind_role("reasoning", provider, model_override=model)
    w = _stub_kernel(router).resolve_context_window_with_source()
    assert w.tokens == expected_tokens, (
        f"{provider}/{model} resolved {w.tokens}, expected {expected_tokens}"
    )
    assert w.source == expected_source


def test_ctb3_window_follows_a_live_switch():
    """Rebinding the reasoning role RE-RESOLVES the window for the new model.

    Drives a real switch sequence across three windows in both directions, so a
    resolver that cached the first model (or read a stored field written only at
    startup) cannot pass: it would report 256k after the switch to gpt-4.
    """
    _fresh_registry()
    router = _router_with("cerebras", "gemma-4-31b")
    _add = router.registry.add
    from backend.agent.inference.provider import ProviderInstance, ProviderKind

    _add(ProviderInstance(id="cohere", label="cohere", kind=ProviderKind.API,
                          model="command-r-plus-08-2024"))
    _add(ProviderInstance(id="openai", label="openai", kind=ProviderKind.API,
                          model="gpt-4"))
    k = _stub_kernel(router)

    # Big -> small -> medium -> big again. Each step must report the CURRENT
    # model's window, including the shrink (the dangerous direction: a stale
    # large window over-sizes the budget past what the model can accept).
    for provider, model, expected in [
        ("cerebras", "gemma-4-31b", 256_000),
        ("openai", "gpt-4", 8_192),
        ("cohere", "command-r-plus-08-2024", 128_000),
        ("cerebras", "gemma-4-31b", 256_000),
    ]:
        router.bind_role("reasoning", provider, model_override=model)
        w = k.resolve_context_window_with_source()
        assert w.tokens == expected, (
            f"after switching to {provider}/{model} the window was {w.tokens}, "
            f"expected {expected} — the budget did not follow the switch"
        )
        assert k._selected_reasoning_model == model


def test_ctb3_brain_and_tool_windows_are_independent():
    """Brain and Tool on different providers resolve their own models.

    The subagent/swarm case: per-role bindings must not collapse onto one
    another, or a tool model's window would size the brain's budget.
    """
    _fresh_registry()
    router = _router_with("cerebras", "gemma-4-31b")
    from backend.agent.inference.provider import ProviderInstance, ProviderKind

    router.registry.add(
        ProviderInstance(id="openai", label="openai", kind=ProviderKind.API,
                         model="gpt-4")
    )
    router.bind_role("reasoning", "cerebras", model_override="gemma-4-31b")
    router.bind_role("tool_execution", "openai", model_override="gpt-4")

    k = _stub_kernel(router)
    assert k._selected_reasoning_model == "gemma-4-31b"
    assert k._selected_tool_execution_model == "gpt-4"
    # The DER budget is sized off the REASONING binding, not the tool one.
    assert k.resolve_context_window_with_source().tokens == 256_000


# ---------------------------------------------------------------------------
# CT-B4: a Brain/Tool split must not over-budget the smaller model
# ---------------------------------------------------------------------------
#
# DER spends ONE budget across calls that go to the reasoning binding and calls
# that go to the tool_execution binding (agent_kernel.infer(role="EXECUTION")).
# Sizing that budget from the reasoning window alone means a Brain on a 256k
# model budgets ~230k for tool steps running on an 8k model — every one of which
# truncates silently. That is the exact overcommit the conservative 8192 default
# exists to prevent, reintroduced through a split binding (2026-08-16).

def _split_router(reasoning=("cerebras", "gemma-4-31b"),
                  tool=("openai", "gpt-4")):
    from backend.agent.inference.provider import ProviderInstance, ProviderKind
    from backend.agent.inference.registry import ProviderRegistry
    from backend.agent.inference.roles import RoleBindingTable

    reg = ProviderRegistry()
    for pid, model in {reasoning, tool}:
        reg.add(ProviderInstance(id=pid, label=pid, kind=ProviderKind.API,
                                 model=model))
    r = InferenceRouter.__new__(InferenceRouter)
    for k, v in [("_registry", reg), ("_roles", RoleBindingTable(reg)),
                 ("_default_role", "reasoning"), ("_transports", {}),
                 ("_inprocess_mgr", None)]:
        object.__setattr__(r, k, v)
    r.bind_role("reasoning", reasoning[0], model_override=reasoning[1])
    r.bind_role("tool_execution", tool[0], model_override=tool[1])
    return r


def test_ctb4_each_role_resolves_its_own_window():
    """reasoning and tool_execution report THEIR model's window, not each other's."""
    _fresh_registry()
    k = _stub_kernel(_split_router())
    assert k.resolve_context_window("reasoning") == 256_000
    assert k.resolve_context_window("tool_execution") == 8_192


def test_ctb4_turn_budget_is_capped_by_the_smaller_window():
    """Brain 256k + Tool 8k -> the turn window is 8k, never 256k."""
    _fresh_registry()
    k = _stub_kernel(_split_router())
    assert k.resolve_turn_context_window() == 8_192, (
        "the turn budget was sized by the Brain; every tool-role call would "
        "truncate silently"
    )


def test_ctb4_cap_applies_in_either_direction():
    """The smaller window wins regardless of which role holds it."""
    _fresh_registry()
    k = _stub_kernel(_split_router(reasoning=("openai", "gpt-4"),
                                   tool=("cerebras", "gemma-4-31b")))
    assert k.resolve_context_window("reasoning") == 8_192
    assert k.resolve_context_window("tool_execution") == 256_000
    assert k.resolve_turn_context_window() == 8_192


def test_ctb4_same_model_on_both_roles_is_unchanged():
    """No split -> no cap; the single window is used as-is."""
    _fresh_registry()
    k = _stub_kernel(_split_router(reasoning=("cerebras", "gemma-4-31b"),
                                   tool=("cerebras", "gemma-4-31b")))
    assert k.resolve_turn_context_window() == 256_000


def test_ctb4_default_role_still_resolves_reasoning():
    """The no-argument contract used by ~20 call sites is preserved."""
    _fresh_registry()
    k = _stub_kernel(_split_router())
    assert k.resolve_context_window() == k.resolve_context_window("reasoning")
