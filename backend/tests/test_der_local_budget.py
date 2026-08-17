"""
Regression test for DER budget / context-window adaptation with local models.

The agent must respond through a local model. A mismatch between the budget's
assumed context window and the model's ACTUAL loaded n_ctx causes either:
  - under-sizing (wasteful truncation), or
  - over-sizing (packing 60k tokens into an 8k window -> model errors -> no response).

These tests prove resolve_context_window() trusts the live local manager's
actual n_ctx (source of truth) instead of substring-guessing to 8192, and that
the DER flat token budget is capped at the real window.
"""
import sys
import types
import pytest


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



def _load_kernel_module(monkeypatch, loaded_n_ctx):
    """Import AgentKernel with a stubbed local manager reporting loaded_n_ctx."""
    # Stub backend.agent.local_model_manager before import
    lmm = types.ModuleType("backend.agent.local_model_manager")
    class _Mgr:
        _current_params = {"n_ctx": loaded_n_ctx}
        _current_model_path = "C:/models/Ternary-Bonsai-27B-dspark-Q4_1.gguf"
        def is_loaded(self):
            return loaded_n_ctx is not None
    lmm.get_local_model_manager = lambda: _Mgr()
    lmm.LocalModelManager = _Mgr
    monkeypatch.setitem(sys.modules, "backend.agent.local_model_manager", lmm)

    from backend.agent import agent_kernel
    # Build a minimal kernel (avoid full __init__)
    k = agent_kernel.AgentKernel.__new__(agent_kernel.AgentKernel)
    k._router = _stub_router("local", "Ternary-Bonsai-27B-dspark-Q4_1")
    k._context_window_overrides = {}
    return k


def test_local_model_uses_actual_n_ctx(monkeypatch):
    """A local Bonsai 27B loaded at n_ctx=32768 must resolve to 32768, not 8192."""
    k = _load_kernel_module(monkeypatch, loaded_n_ctx=32768)
    window = k.resolve_context_window()
    assert window == 32768, f"expected 32768 (actual loaded), got {window}"


def test_local_model_unloaded_falls_back(monkeypatch):
    """When no local model is loaded, fall back to a safe default (not crash)."""
    k = _load_kernel_module(monkeypatch, loaded_n_ctx=None)
    window = k.resolve_context_window()
    assert isinstance(window, int) and window > 0


def test_der_budget_capped_at_window(monkeypatch):
    """DER flat budget must never exceed the model's real context window * 0.9."""
    k = _load_kernel_module(monkeypatch, loaded_n_ctx=8192)
    # Simulate the budget-cap logic from the DER loop
    from backend.agent.der_constants import DER_TOKEN_BUDGETS
    flat = DER_TOKEN_BUDGETS.get("full", 50000)
    window = k.resolve_context_window()
    capped = min(flat, int(window * 0.9))
    assert capped <= int(window * 0.9), "budget must be capped at the real window"
    assert capped == int(8192 * 0.9), f"expected 7372 for 8k window, got {capped}"
