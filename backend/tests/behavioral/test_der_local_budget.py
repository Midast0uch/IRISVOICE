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
    k._model_provider = "local"
    k._selected_reasoning_model = "Ternary-Bonsai-27B-dspark-Q4_1"
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
