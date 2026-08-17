"""Behavioral: an unlisted provider resolving to the default must NOT produce a
budget above its resolved window. The live cerebras case (REQ-1): provider=cerebras
model=gemma-4-31b resolved to the 8192 default and DER reported budget=40000
(4.9x the window). Steps kept issuing while every call truncated.
"""
from __future__ import annotations

from backend.agent.der_constants import resolve_der_token_budget


def _stub_router(provider, model):
    """Private router with `provider`/`model` bound to the reasoning role.

    Replaces the old `k._model_provider = ...` / `k._selected_reasoning_model
    = ...` staging: both are read-only properties derived from the binding as
    of 2026-08-16. The registry and role table here are LOCAL instances, not
    the process-wide singletons, so this stub cannot leak into another test.
    """
    from backend.agent.inference.provider import ProviderInstance, ProviderKind
    from backend.agent.inference.registry import ProviderRegistry
    from backend.agent.inference.roles import RoleBindingTable
    from backend.agent.inference.router import InferenceRouter

    # Kind chosen so `_provider_string_for_instance` maps back to the exact
    # provider string the stub asked for (OLLAMA->"local", INPROCESS->
    # "iris_local", LOCAL_OPENAI->"lmstudio", API->the instance id).
    _kind = {
        "local": ProviderKind.OLLAMA,
        "iris_local": ProviderKind.INPROCESS,
        "lmstudio": ProviderKind.LOCAL_OPENAI,
    }.get(provider, ProviderKind.API)
    _reg = ProviderRegistry()
    _reg.add(
        ProviderInstance(id=provider, label=provider, kind=_kind, model=model)
    )
    _r = InferenceRouter.__new__(InferenceRouter)
    object.__setattr__(_r, "_registry", _reg)
    object.__setattr__(_r, "_roles", RoleBindingTable(_reg))
    object.__setattr__(_r, "_default_role", "reasoning")
    object.__setattr__(_r, "_transports", {})
    object.__setattr__(_r, "_inprocess_mgr", None)
    _r.bind_role("reasoning", provider, model_override=model)
    return _r



def _make_kernel(provider: str, model: str):
    """Build a minimal AgentKernel (skip full __init__) for window resolution."""
    from backend.agent import agent_kernel

    k = agent_kernel.AgentKernel.__new__(agent_kernel.AgentKernel)
    k._router = _stub_router(provider, model)
    k._context_window_overrides = {}
    return k


def test_cerebras_resolves_confirmed_window():
    # The confirmed table entry ("cerebras", "gemma-4-31b", 256_000) must win.
    k = _make_kernel("cerebras", "gemma-4-31b")
    assert k.resolve_context_window() == 256_000


def test_cerebras_budget_scales_not_overcommits():
    k = _make_kernel("cerebras", "gemma-4-31b")
    window = k.resolve_context_window()
    budget = resolve_der_token_budget(window, "implement")
    assert budget <= window
    # Capacity now scales with the 256k model (was pinned to a flat 40k floor).
    assert budget > 40_000


def test_unlisted_provider_default_no_overcommit():
    # An unlisted provider falls to the 8192 default; budget must stay under it.
    k = _make_kernel("someprovider", "some-model")
    window = k.resolve_context_window()
    assert window == 8_192  # conservative default
    for tc in ["quick", "implement", "full"]:
        assert resolve_der_token_budget(window, tc) <= window, (
            f"overcommit: budget exceeds window {window} for {tc}"
        )
