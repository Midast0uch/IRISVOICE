"""Behavioral: an unlisted provider resolving to the default must NOT produce a
budget above its resolved window. The live cerebras case (REQ-1): provider=cerebras
model=gemma-4-31b resolved to the 8192 default and DER reported budget=40000
(4.9x the window). Steps kept issuing while every call truncated.
"""
from __future__ import annotations

from backend.agent.der_constants import resolve_der_token_budget


def _make_kernel(provider: str, model: str):
    """Build a minimal AgentKernel (skip full __init__) for window resolution."""
    from backend.agent import agent_kernel

    k = agent_kernel.AgentKernel.__new__(agent_kernel.AgentKernel)
    k._model_provider = provider
    k._selected_reasoning_model = model
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
