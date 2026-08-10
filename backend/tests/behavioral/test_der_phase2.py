"""Phase 2 tests — Emergent Shape (growth-width split/execute, physics-driven).

Validates D2.1–D2.4 of docs/DER_COUPLED_ACTION_CYCLE_SPEC.md:
  F2 fixed : execution-tree shape emerges from live (u,xi), not mode
  F3 fixed : recovery uses the SAME _split_step operator (no separate graft)
  MAX_DEPTH cap, DER_MAX_GRAFTS cap, work_units from live context window,
  adaptive verify strictness by |u| band.
"""

import types

import pytest


def _make_kernel():
    from backend.agent.agent_kernel import AgentKernel

    k = AgentKernel.__new__(AgentKernel)
    k._memory_interface = None
    k._tool_bridge = None
    k._der_task_class = "full"
    k._der_completed_tools = []
    k._der_work_units = 0
    k.conversation_id = "test-conv"
    k.session_id = "test-session"
    return k


def _make_item(step_id="s1", depth=0, critical=True):
    from backend.agent.der_loop import QueueItem

    return QueueItem(
        step_id=step_id,
        step_number=1,
        description="do the thing",
        objective_anchor="objective",
        depth_layer=depth,
        expected_output="thing done",
        critical=critical,
    )


# ── Test 1: split on unresolved_u (|u| < U_SPLIT) ───────────────────────────
def test_split_on_unresolved_u():
    from backend.agent.der_constants import U_SPLIT

    k = _make_kernel()
    item = _make_item()
    cad = {"x": 0.1, "y": 0.2, "xi": 0.3, "u": U_SPLIT - 0.1}  # unresolved
    children = k._split_step(item, "unresolved_u", cad, work_units=10)
    assert len(children) == 3, "unresolved_u must split WIDE (3)"
    assert all(c.is_subloop for c in children), "children are Sub-Loops"
    assert all(c.depth_layer == 1 for c in children)


# ── Test 2: split on verify_failed uses SAME operator (F3) ──────────────────
def test_split_on_failure():
    k = _make_kernel()
    item = _make_item()
    cad = {"x": 0.0, "y": 0.0, "xi": 0.0, "u": 0.1}  # unresolved -> wide
    children = k._split_step(item, "verify_failed", cad, work_units=10)
    assert len(children) == 3, "verify_failed must use the same _split_step"
    assert all(c.is_subloop for c in children)


# ── Test 3: MAX_DEPTH cap ───────────────────────────────────────────────────
def test_max_depth_cap():
    from backend.agent.der_constants import MAX_DEPTH

    k = _make_kernel()
    item = _make_item(depth=MAX_DEPTH)  # at the cap
    cad = {"u": 0.0}  # unresolved -> would split wide
    children = k._split_step(item, "unresolved_u", cad, work_units=10)
    assert children == [], "no split past MAX_DEPTH"


# ── Test 4: DER_MAX_GRAFTS cap ──────────────────────────────────────────────
def test_max_grafts_cap():
    from backend.agent.der_constants import DER_MAX_GRAFTS

    k = _make_kernel()
    item = _make_item()
    cad = {"u": 0.0}  # unresolved -> wants 3
    # work_units huge so the only limiter is DER_MAX_GRAFTS
    children = k._split_step(item, "unresolved_u", cad, work_units=999)
    assert len(children) <= DER_MAX_GRAFTS, "width capped at DER_MAX_GRAFTS"


# ── Test 5: work_units derived from live context window (D-1) ───────────────
def test_work_units_from_context_window():
    from backend.agent.der_constants import derive_work_units_0, AVG_STEP_COST

    k = _make_kernel()
    k.resolve_context_window = lambda: 30000
    # emulate the D2.4 init
    k._der_work_units = derive_work_units_0(k.resolve_context_window())
    expected = max(1, int(30000 / AVG_STEP_COST))
    assert k._der_work_units == expected, "work_units must derive from context window"
    # split prepays width
    item = _make_item()
    cad = {"u": 0.0}
    before = k._der_work_units
    children = k._split_step(item, "unresolved_u", cad, k._der_work_units)
    after = before - len(children)
    assert after >= 0, "split cannot overdraw work units"


# ── Test 6: adaptive verify strictness by |u| band (D2.3) ───────────────────
def test_adaptive_verify_by_u():
    from backend.agent.der_constants import U_SPLIT, U_CONVERGED

    k = _make_kernel()
    assert k._der_verify_strictness(U_SPLIT - 0.1) == "wide"
    assert k._der_verify_strictness((U_SPLIT + U_CONVERGED) / 2) == "rubric"
    assert k._der_verify_strictness(U_CONVERGED + 0.1) == "atomic"


# ── Test 7: live cad state fallback (D2.2) ──────────────────────────────────
def test_live_cad_state_fallback():
    k = _make_kernel()
    # No engine, no recorder -> returns zeros, never raises
    state = k._der_live_cad_state("test-session")
    assert set(state.keys()) == {"x", "y", "xi", "u"}
    assert all(isinstance(v, float) for v in state.values())
