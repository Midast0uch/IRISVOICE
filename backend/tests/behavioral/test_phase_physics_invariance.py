"""
Behavioral test: phase physics invariance (REQ-12 / T3.3).

Key physical properties of the Kuramoto splay oscillator:
1. Coupling force is zero at the repulsive fixed point (even spacing).
2. Coupling force is zero for identical phases (all aligned).
3. Per-oscillator force sum over ALL oscillators is zero (momentum conservation).
4. Amplitude stays within [R_MIN, 1.0] under any coupling condition.
5. Theta stays on [0, 2π) after any number of advance steps.
"""
import math
import pytest

from backend.agent.phase_manager import (
    PhaseRegistry,
    get_registry,
    get_rate_meter,
    R_MIN,
    reset_registry_for_testing,
)
from backend.agent.trig_coupling import splay_force
@pytest.fixture(autouse=True)
def clean():
    get_rate_meter().reset_for_testing()
    get_rate_meter().record_request(
        "inv_q", tokens=10, priority=5, estimated=True
    )
    reset_registry_for_testing()
    yield


def test_force_zero_at_even_spacing_n4():
    """Repulsive fixed point for N=4: force ~0 at π/2 spacing."""
    _ths = [0.0, math.pi / 2, math.pi, 3 * math.pi / 2]
    for _i, _th in enumerate(_ths):
        _f = splay_force(_th, _ths, k=1.0)
        assert _f == pytest.approx(0.0, abs=1e-10), (
            "Force at oscillator %d should be ~0 at even spacing; got %s"
            % (_i, _f)
        )


def test_force_zero_identical_phases():
    """All oscillators at same phase → zero coupling force (no gradient)."""
    _ths = [1.0, 1.0, 1.0, 1.0, 1.0]
    for _th in _ths:
        _f = splay_force(_th, _ths, k=2.0)
        assert _f == pytest.approx(0.0, abs=1e-10)


def test_force_sum_is_zero():
    """Sum of per-oscillator splay forces is always zero (momentum conservation)."""
    import random
    for _n in [3, 4, 5, 7]:
        _seed = 42 + _n
        random.seed(_seed)
        _ths = sorted([random.uniform(0, 2 * math.pi) for _ in range(_n)])
        _total = sum(splay_force(_th, _ths, k=0.8) for _th in _ths)
        assert _total == pytest.approx(0.0, abs=1e-10), (
            "Sum of forces for N=%d should be 0; got %s" % (_n, _total)
        )


def test_advance_all_keeps_theta_bounded():
    """After many advance steps, all thetas stay in [0, 2π)."""
    _rm = get_rate_meter()
    _rm.record_request("inv_q", tokens=10, priority=5, estimated=True)

    _r = get_registry()
    _ids = []
    for _i in range(3):
        _oid = "inv_id_%d" % _i
        _r.register(_oid, "inv_q", natural_period_s=1.0)
        _ids.append(_oid)

    import time
    for _step in range(100):
        time.sleep(0.001)
        _r.advance_all("inv_q")

    for _oid in _ids:
        _o = _r.get(_oid)
        assert _o is not None
        assert 0 <= _o.theta < 2 * math.pi, (
            "Theta must stay in [0, 2π); oscillator %s has theta=%s"
            % (_oid, _o.theta)
        )
        assert R_MIN <= _o.amplitude <= 1.0, (
            "Amplitude must stay in [%s, 1.0]; got %s"
            % (R_MIN, _o.amplitude)
        )


def test_stddev_reduction_at_fixed_point():
    """F12/REQ-20: inter-request-gap stddev is minimized at the repulsive
    fixed point.  For oscillators at the fixed point, the coupling force
    is ~0, meaning the phase does not jitter.  This is a proxy for the
    >=50% stddev-reduction assertion in the validation script."""
    _ths = [0.0, 2 * math.pi / 3, 4 * math.pi / 3]
    _forces = [splay_force(th, _ths, k=0.6) for th in _ths]
    _mean = sum(_forces) / len(_forces)
    _var = sum((f - _mean) ** 2 for f in _forces) / len(_forces)
    _std = math.sqrt(_var)
    # At the fixed point, stddev of per-oscillator forces should be ~0
    assert _std == pytest.approx(0.0, abs=1e-10), (
        "Stddev of forces should be ~0 at fixed point; got %s" % _std
    )


# ── REQ-16 AC4: three→two rebalance ──────────────────────────────────────

REBALANCE_TICKS = 20  # max advance steps for the two survivors to converge

def test_three_to_two_rebalance():
    """REQ-16 AC4: Three oscillators at the repulsive fixed point (2π/3
    spacing) rebalance to ~π spacing after one is removed, within
    ``REBALANCE_TICKS`` advance_all calls.

    This verifies that the splay coupling re-establishes uniform spacing
    when the group changes size.
    """
    _r = get_registry()

    _r.register("re_a", "inv_q", natural_period_s=10.0)  # slow period so
    _r.register("re_b", "inv_q", natural_period_s=10.0)  # coupling dominates
    _r.register("re_c", "inv_q", natural_period_s=10.0)

    # Place at 2π/3 spacing — repulsive fixed point for N=3
    _r.get("re_a").theta = 0.0
    _r.get("re_b").theta = 2.0 * math.pi / 3.0
    _r.get("re_c").theta = 4.0 * math.pi / 3.0

    # Set equal amplitudes so coupling is symmetric
    for _o in _r.snapshot():
        _o.amplitude = 1.0

    import time
    # Advance a few ticks to verify N=3 fixed point is stable.
    # Use simulated elapsed time so dt matches omega*coupling scales.
    for _step in range(5):
        _r.advance_all("inv_q")
        # Set last_advance_at 1s in the past so dt ≈ 1.0s per iteration
        for _o in _r.snapshot():
            _o.last_advance_at = time.time() - 1.0
        time.sleep(0.001)

    # Remove one oscillator (simulating quota de-registration)
    _r.unregister("re_c")

    # Advance survivors — they should converge toward π separation.
    for _step in range(REBALANCE_TICKS):
        _r.advance_all("inv_q")
        for _o in _r.snapshot():
            _o.last_advance_at = time.time() - 1.0
        time.sleep(0.001)

    _a = _r.get("re_a")
    _b = _r.get("re_b")
    assert _a is not None
    assert _b is not None

    _gap = abs(_a.theta - _b.theta) % (2.0 * math.pi)
    _gap = min(_gap, 2.0 * math.pi - _gap)  # angular distance (0..π)

    assert _gap == pytest.approx(math.pi, abs=0.3), (
        "REQ-16 AC4: two survivors should converge to ~π separation "
        "within %s ticks; gap=%s (a=%.3f, b=%.3f)"
        % (REBALANCE_TICKS, _gap, _a.theta, _b.theta)
    )
