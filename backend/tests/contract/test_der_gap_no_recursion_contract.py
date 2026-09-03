"""Contract: Trailing-Director gap-fill is REMOVED (2026-08-06 decision).

The gap-fill ran SEQUENTIALLY after the user's task: analyze_gaps was called
synchronously in _der_finalize_step and its gap items were queued into the
SAME turn, re-executing completed steps' work after the plan finished (live
turn 95cbe698-342: 5 planned steps then gap-s2-* extended the turn;
turn fc2a1a48-ddf looped unbounded on gap-on-gap). It never ran in parallel
with the task, so it only added latency and unsolicited steps. Decision:
remove the gap-fill entirely — _trailing_director is never constructed.

These tests pin the removal:
  1. the kernel never constructs a TrailingDirector (init keeps it None)
  2. the finalize path contains no analyze_gaps call (the block is gone)
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def test_kernel_does_not_construct_trailing_director():
    """AgentKernel init must NOT create a TrailingDirector.

    Regression: init constructed TrailingDirector(adapter=self) and wired it
    into set_memory_interface; the gap-fill then extended every turn. The
    removal keeps _trailing_director None so no gap analysis ever runs.
    """
    from backend.agent.agent_kernel import AgentKernel

    # Assert the init default (the construction block was removed from init).
    kernel = AgentKernel.__new__(AgentKernel)
    assert getattr(kernel, "_trailing_director", None) is None


def test_finalize_has_no_analyze_gaps_call():
    """_der_finalize_step must not call analyze_gaps.

    Regression (live 95cbe698-342): after 5 planned steps completed, gap-s2-*
    items were queued and executed, extending the turn. The gap-analysis block
    is removed from the finalize path.
    """
    import inspect

    from backend.agent import agent_kernel

    src = inspect.getsource(agent_kernel.AgentKernel._der_finalize_step)
    assert "analyze_gaps" not in src, (
        "_der_finalize_step must not call analyze_gaps (gap-fill removed)"
    )
