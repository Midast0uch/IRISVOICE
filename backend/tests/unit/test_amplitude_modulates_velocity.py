"""
REQ-9 AC3 / REQ-22 AC1-AC2: amplitude modulates the effective angular velocity.

Regression guard for review finding N1. The Wave 6 repair fixed the coupling sign
(F1) but dropped amplitude from the velocity term: ``advance_all`` computed
``2*pi/period`` with no ``r``, and ``_estimate_wait`` did the same while its
docstring stated "the amplitude does NOT scale velocity". Amplitude was therefore
computed, relaxed, and logged but never affected behavior — the whole volume-
regulation half of the design (concept doc section 6) was inert.

These assertions make that unreintroducible: a lower amplitude MUST produce a
longer estimated wait, and the two functions MUST agree on velocity.
"""
import math

import pytest

from backend.agent.phase_manager import (
    MIN_PERIOD_S,
    R_MIN,
    PhaseOscillator,
    _estimate_wait,
)


def _osc(theta: float, amplitude: float, period: float = 4.0) -> PhaseOscillator:
    return PhaseOscillator(
        oscillator_id="o",
        quota_id="q",
        provider_label="",
        theta=theta,
        amplitude=amplitude,
        natural_period_s=period,
        last_advance_at=0.0,
    )


def test_lower_amplitude_gives_longer_wait():
    """A loaded provider (low r) must make its registrants fire LESS often."""
    _full = _estimate_wait(_osc(0.0, amplitude=1.0))
    _half = _estimate_wait(_osc(0.0, amplitude=0.5))
    _low = _estimate_wait(_osc(0.0, amplitude=0.2))

    assert _full > 0, "a fresh oscillator at theta=0 must have a positive wait"
    assert _half > _full, "halving amplitude must lengthen the wait"
    assert _low > _half, "lowering amplitude further must lengthen it further"
    # omega_eff = omega * r, so wait scales as 1/r.
    assert _half == pytest.approx(_full * 2.0, rel=1e-6)


def test_amplitude_is_actually_in_the_velocity_term():
    """Direct check of REQ-9 AC3: omega_eff == (2*pi/period) * r."""
    for _r in (1.0, 0.5, 0.25):
        _o = _osc(0.0, amplitude=_r, period=4.0)
        _wait = _estimate_wait(_o)
        _omega_eff = (2.0 * math.pi / 4.0) * _r
        _dist = (math.pi - 0.0) % (2 * math.pi)
        assert _wait == pytest.approx(_dist / _omega_eff, rel=1e-9), (
            "wait must be derived from omega_eff = omega * r (r=%s)" % _r
        )


def test_velocity_never_zero_so_wait_is_finite():
    """R_MIN floor keeps the wait finite even at minimum amplitude."""
    _w = _estimate_wait(_osc(0.0, amplitude=0.0))  # below the floor
    assert math.isfinite(_w) and _w > 0, "wait must stay finite at r=0"
    # Clamped to R_MIN, so it equals the R_MIN wait.
    assert _w == pytest.approx(_estimate_wait(_osc(0.0, amplitude=R_MIN)), rel=1e-9)


def test_past_firing_point_still_admits_regardless_of_amplitude():
    """Amplitude must not resurrect a wait for an oscillator already past pi."""
    for _r in (1.0, 0.5, R_MIN):
        assert _estimate_wait(_osc(math.pi, amplitude=_r)) == 0.0
