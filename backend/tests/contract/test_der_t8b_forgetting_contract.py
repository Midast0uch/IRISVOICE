"""T8b (REQ-3 AC4/AC5/AC6) contract: the forgetting is wired AND safe.

Drives the REAL `AgentKernel._der_bound_step_context` (extracted from
_der_finalize_step's step-input section) to pin the three ACs:

  - AC4: content beyond the OQ-6 derived bound is DROPPED from the step's
    working context (coordinate_signal) — the node record is the re-read point.
  - AC5: the per-step prompt token count is recorded (measured reduction),
    and the bound is DERIVED from the REQ-1 resolved window, never a literal.
  - AC6: when the node's chain write FAILED (durability drop counter > 0),
    the working context is the ONLY copy — it must NOT be bounded/dropped.

The AC6 case is the discriminating one: the pre-fix guard
(`_der_chain_drops == 0 or not step_id.startswith("immortus")`) was vacuously
true for every non-immortus step, so a DER step with a failed chain write
still lost its only copy. This test failed against that code.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _make_kernel(chain_drops: int = 0, window: int = 10000) -> SimpleNamespace:
    k = SimpleNamespace()
    k.resolve_context_window = lambda: window
    k._der_chain_drops = chain_drops
    k._der_step_prompt_tokens = 0
    return k


def _item(signal: str, step_id: str = "s1"):
    it = SimpleNamespace()
    it.coordinate_signal = signal
    it.step_id = step_id
    return it


# ── AC4: content beyond the derived bound is dropped ──────────────────────

def test_ac4_drops_tail_beyond_derived_bound():
    """A long coordinate_signal is truncated to the OQ-6 derived bound."""
    from backend.agent.agent_kernel import AgentKernel

    k = _make_kernel(window=10000)  # bound = max(512, 1500) = 1500
    item = _item(signal="x" * 5000, step_id="s1")

    AgentKernel._der_bound_step_context.__get__(k, AgentKernel)(item)

    assert len(item.coordinate_signal) == 1500, (
        f"AC4: tail must be dropped to the derived bound, got "
        f"{len(item.coordinate_signal)}"
    )


# ── AC5: the reduction is measured (per-step token count) ─────────────────

def test_ac5_records_step_prompt_tokens():
    """The per-step prompt token count is recorded so the reduction is a
    measured number."""
    from backend.agent.agent_kernel import AgentKernel

    k = _make_kernel(window=10000)
    item = _item(signal="y" * 800, step_id="s1")

    AgentKernel._der_bound_step_context.__get__(k, AgentKernel)(item)

    assert k._der_step_prompt_tokens == 200, (
        f"AC5: per-step token count must be recorded, got "
        f"{k._der_step_prompt_tokens}"
    )


# ── AC6: a failed chain write must NEVER be forgotten ─────────────────────

def test_ac6_never_forgets_when_chain_write_failed():
    """A node whose chain write failed keeps its FULL working context —
    the context is the only copy (durability-drop counter > 0)."""
    from backend.agent.agent_kernel import AgentKernel

    k = _make_kernel(chain_drops=3, window=10000)  # write FAILED
    item = _item(signal="z" * 5000, step_id="s1")

    AgentKernel._der_bound_step_context.__get__(k, AgentKernel)(item)

    assert len(item.coordinate_signal) == 5000, (
        f"AC6: a failed chain write (drops>0) must NOT drop the only copy; "
        f"got {len(item.coordinate_signal)} — pre-fix guard only protected "
        "immortus-prefixed steps (BUG)"
    )


def test_ac6_derived_bound_not_literal():
    """The bound follows the resolved window (derived), not a hardcoded 8192."""
    from backend.agent.agent_kernel import AgentKernel

    k = _make_kernel(window=40000)  # bound = max(512, 6000) = 6000
    item = _item(signal="w" * 20000, step_id="s1")

    AgentKernel._der_bound_step_context.__get__(k, AgentKernel)(item)

    assert len(item.coordinate_signal) == 6000, (
        f"OQ-6 bound must derive from the window (40k -> 6000), got "
        f"{len(item.coordinate_signal)}"
    )
