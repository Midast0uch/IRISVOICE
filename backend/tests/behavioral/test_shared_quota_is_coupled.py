"""
Behavioral test: shared quota coupling (T6.2 / F2+F11).

Two oscillators on ONE quota_id land in ONE group and spread via Kuramoto
splay coupling.  Two on the same endpoint with DIFFERENT credentials land
in separate groups and do NOT spread.
"""
import math
import pytest

from backend.agent.phase_manager import get_registry, reset_registry_for_testing
from backend.agent.trig_coupling import splay_force


@pytest.fixture(autouse=True)
def clean():
    reset_registry_for_testing()
    yield


def test_two_oscillators_same_quota_coupled():
    """Two oscillators on the same quota_id are placed ~π apart by widest-gap,
    and splay coupling keeps them spread (no net force at π separation)."""
    _r = get_registry()
    _a = _r.register("osc_a", "shared_quota", natural_period_s=1.0)
    _b = _r.register("osc_b", "shared_quota", natural_period_s=1.0)

    # Both are on the same quota → placed ~π apart
    _gap = (_a.theta - _b.theta) % (2 * math.pi)
    _dist = min(_gap, 2 * math.pi - _gap)
    assert _dist == pytest.approx(math.pi, abs=0.1)

    # Force on each should be ~0 at π separation (fixed point)
    _fa = splay_force(_a.theta, [_a.theta, _b.theta], k=0.6)
    _fb = splay_force(_b.theta, [_a.theta, _b.theta], k=0.6)
    assert _fa == pytest.approx(0.0, abs=1e-10)
    assert _fb == pytest.approx(0.0, abs=1e-10)

    # They should be in the same coupling group
    _same_quota = _r.get_by_quota("shared_quota")
    assert len(_same_quota) == 2


def test_two_oscillators_different_credentials_not_coupled():
    """Two oscillators on the same endpoint but DIFFERENT credentials (quota_id)
    land in separate groups and do NOT spread."""
    _r = get_registry()
    _a = _r.register("osc_a1", "quota_user1", natural_period_s=1.0)
    _b = _r.register("osc_b1", "quota_user2", natural_period_s=1.0)

    # Different quotas → each starts at 0.0 (no oscillators in its group)
    assert _a.theta == pytest.approx(0.0, abs=1e-6)
    assert _b.theta == pytest.approx(0.0, abs=1e-6)

    # Different quota groups
    assert len(_r.get_by_quota("quota_user1")) == 1
    assert len(_r.get_by_quota("quota_user2")) == 1

    # Theta values are identical (0.0) — NOT spread
    assert _a.theta == _b.theta
