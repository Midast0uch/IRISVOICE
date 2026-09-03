"""
Tests for PhaseOscillator advance() and trig coupling (T3.3 / T3.4 / REQ-12).

Uses a controlled registry with isolated oscillators to verify basic advance
mechanics. Per-oscillator coupling force is tested via the signed primitive
``splay_force`` (T6.1), not a scalar abs() aggregator.
"""
import math

import pytest

from backend.agent.phase_manager import (
    PhaseRegistry,
    advance,
    get_registry,
    reset_registry_for_testing,
)
from backend.agent.trig_coupling import (
    splay_force,
    align_force,
    splay_coupling_magnitude,
    align_coupling_magnitude,
)


@pytest.fixture
def registry():
    reset_registry_for_testing()
    return PhaseRegistry()


def test_advance_noop_on_unknown_quota(registry):
    """Advancing an unregistered quota is a no-op."""
    advance("nonexistent", "nonexistent", registry)
    assert len(registry.snapshot()) == 0


def test_register_creates_oscillator(registry):
    _o = registry.register(
        "q1", "q1", provider_label="test", natural_period_s=1.0
    )
    assert _o.quota_id == "q1"
    assert _o.oscillator_id == "q1"
    assert 0 <= _o.theta < 2 * math.pi
    assert _o.amplitude >= 0.1


def test_register_preserves_theta_on_reregister(registry):
    _o = registry.register("q1", "q1", natural_period_s=1.0)
    _old_theta = _o.theta
    _o2 = registry.register("q1", "q1", natural_period_s=0.5)
    assert _o2 is _o
    assert _o2.theta == _old_theta  # preserved


def test_widest_gap_two_oscillators(registry):
    """Two oscillators on the same quota_id are placed ~π apart."""
    _a = registry.register("id1", "shared", natural_period_s=1.0)
    _b = registry.register("id2", "shared", natural_period_s=1.0)
    _gap = (_a.theta - _b.theta) % (2 * math.pi)
    _dist = min(_gap, 2 * math.pi - _gap)
    assert _dist == pytest.approx(math.pi, abs=0.1)


def test_widest_gap_two_oscillators_different_quota_not_spread(registry):
    """Two oscillators on DIFFERENT quota_ids are NOT spread (T6.2)."""
    _a = registry.register("id1", "q1", natural_period_s=1.0)
    _b = registry.register("id2", "q2", natural_period_s=1.0)
    # The second oscillator has its own quota, so _widest_gap for q2 sees no
    # existing oscillators and returns 0.0 (the default initial theta).
    assert _b.theta == pytest.approx(0.0, abs=1e-6)


def test_widest_gap_three_oscillators_same_quota(registry):
    _a = registry.register("id1", "shared", natural_period_s=1.0)
    _b = registry.register("id2", "shared", natural_period_s=1.0)
    _c = registry.register("id3", "shared", natural_period_s=1.0)
    _thetas = sorted([_a.theta, _b.theta, _c.theta])
    _gaps = []
    for i in range(3):
        _gaps.append((_thetas[(i + 1) % 3] - _thetas[i]) % (2 * math.pi))
    assert min(_gaps) == pytest.approx(math.pi / 2, abs=0.1)
    assert max(_gaps) == pytest.approx(math.pi, abs=0.1)


def test_unregister_removes_oscillator(registry):
    registry.register("q1", "q1", natural_period_s=1.0)
    registry.unregister("q1")
    assert registry.get("q1") is None
    assert len(registry.snapshot()) == 0


def test_get_by_quota_returns_same_group(registry):
    """get_by_quota returns only oscillators sharing that quota_id."""
    _a = registry.register("id1", "shared", natural_period_s=1.0)
    _b = registry.register("id2", "shared", natural_period_s=1.0)
    _c = registry.register("id3", "other", natural_period_s=1.0)
    _shared = registry.get_by_quota("shared")
    assert len(_shared) == 2
    assert all(o.quota_id == "shared" for o in _shared)
    _other = registry.get_by_quota("other")
    assert len(_other) == 1


# ── per-oscillator coupling (T6.1 — signed primitive, not abs!) ──────────

def test_splay_force_two_oscillators_repulsive_sign():
    """Per-oscillator splay force: leading gets +, trailing gets -.

    Two oscillators at 0 and pi/2: the one at 0 is trailing (less theta),
    so its force is negative (pulled forward by the convention).  The one
    at pi/2 is leading, so its force is positive (pushed backward).
    This is the repulsive convention — oscillators spread apart.
    """
    _force_0 = splay_force(0.0, [0.0, math.pi / 2], k=1.0)
    _force_pi2 = splay_force(math.pi / 2, [0.0, math.pi / 2], k=1.0)
    # The trailing oscillator (0) experiences negative force
    assert _force_0 < 0, "trailing oscillator should have negative force"
    # The leading oscillator (pi/2) experiences positive force
    assert _force_pi2 > 0, "leading oscillator should have positive force"
    # Magnitudes are equal (symmetric pair)
    assert _force_0 == pytest.approx(-_force_pi2, abs=1e-10)


def test_splay_force_opposite_sign_regression():
    """REGRESSION GUARD (F1): force for LEADING and TRAILING oscillators
    must have OPPOSITE signs.  This assertion makes F1 impossible to
    reintroduce.
    """
    _f0 = splay_force(0.0, [0.0, math.pi / 2], k=1.0)
    _f1 = splay_force(math.pi / 2, [0.0, math.pi / 2], k=1.0)
    assert (_f0 > 0 and _f1 < 0) or (_f0 < 0 and _f1 > 0), (
        "Forces must have opposite signs; got f0=%s, f1=%s" % (_f0, _f1)
    )


def test_splay_force_converges_to_separation():
    """SEPARATION ASSERTION: two oscillators at delta-theta = 0.1, advanced
    repeatedly, must converge toward π apart (the repulsive fixed point).
    """
    _t0, _t1 = 0.0, 0.1
    _k = 0.6
    _dt = 0.01
    for _step in range(5000):
        _f0 = splay_force(_t0, [_t0, _t1], k=_k)
        _f1 = splay_force(_t1, [_t0, _t1], k=_k)
        _t0 = (_t0 + _f0 * _dt) % (2 * math.pi)
        _t1 = (_t1 + _f1 * _dt) % (2 * math.pi)
    _gap = (_t0 - _t1) % (2 * math.pi)
    _dist = min(_gap, 2 * math.pi - _gap)
    assert _dist == pytest.approx(math.pi, abs=0.15), (
        "Two oscillators should converge to ~pi apart; got dist=%s" % _dist
    )


def test_splay_force_zero_at_pi_separation_n2():
    """At the repulsive fixed point (π apart for N=2), splay_force ≈ 0."""
    _f0 = splay_force(0.0, [0.0, math.pi], k=1.0)
    _f1 = splay_force(math.pi, [0.0, math.pi], k=1.0)
    assert _f0 == pytest.approx(0.0, abs=1e-10)
    assert _f1 == pytest.approx(0.0, abs=1e-10)


def test_splay_force_zero_at_even_spacing_n3():
    """At the repulsive fixed point (2π/3 spacing for N=3), splay_force ≈ 0."""
    _p = 2 * math.pi / 3
    _f0 = splay_force(0.0, [0.0, _p, 2 * _p], k=0.6)
    _f1 = splay_force(_p, [0.0, _p, 2 * _p], k=0.6)
    _f2 = splay_force(2 * _p, [0.0, _p, 2 * _p], k=0.6)
    assert _f0 == pytest.approx(0.0, abs=1e-10)
    assert _f1 == pytest.approx(0.0, abs=1e-10)
    assert _f2 == pytest.approx(0.0, abs=1e-10)


def test_align_force_is_negation_of_splay():
    """align_force is the negation of splay_force for any configuration."""
    import random
    _thetas = sorted([random.uniform(0, 2 * math.pi) for _ in range(5)])
    for _i, _th in enumerate(_thetas):
        _others = [_thetas[j] for j in range(5) if j != _i] + [_th]
        _sp = splay_force(_th, _others, k=1.0)
        _al = align_force(_th, _others, k=1.0)
        assert _sp == pytest.approx(-_al, abs=1e-10)


# ── Coupling magnitude diagnostic (scalar, no abs in advance path) ────────

def test_splay_coupling_magnitude_non_negative():
    """splay_coupling_magnitude is always >= 0 (mean absolute)."""
    _v = splay_coupling_magnitude([0.0, math.pi / 2], k=1.0)
    assert _v >= 0


def test_align_coupling_magnitude_non_negative():
    """align_coupling_magnitude is always >= 0 (mean absolute)."""
    _v = align_coupling_magnitude([0.0, math.pi / 2], k=1.0)
    assert _v >= 0


def test_coupling_magnitude_zero_at_even_spacing_n3():
    """Evenly spaced N=3 phases → coupling magnitude = 0 (fixed point)."""
    _v = splay_coupling_magnitude(
        [0.0, 2 * math.pi / 3, 4 * math.pi / 3], k=0.6
    )
    assert _v == pytest.approx(0.0, abs=1e-9)
