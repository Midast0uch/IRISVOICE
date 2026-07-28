"""
Unit tests for AIMD ceiling learning (T2.3 / REQ-8).

Covers:
  * multiplicative decrease on 429, floored at CEILING_MIN_RPM
  * additive increase after CEILING_PROBE_S without 429
  * ceilings are strictly per-provider (independent quotas)
  * hard rail PHASE_HARD_MAX_RPM is never exceeded by learning (T2.6)
"""
import time

from backend.agent.rate_meter import (
    CEILING_AI_RPM,
    CEILING_INIT_RPM,
    CEILING_MAX_RPM,
    CEILING_MIN_RPM,
    CEILING_MD,
    CEILING_PROBE_S,
    PHASE_HARD_MAX_RPM,
    clear_ceilings_for_testing,
    get_rate_meter,
    reset_rate_meter_for_testing,
)


def _meter():
    reset_rate_meter_for_testing()
    clear_ceilings_for_testing()
    return get_rate_meter()


def test_multiplicative_decrease_on_429():
    _m = _meter()
    _m.ensure_window("quotaA", metered_flag=True)
    _before = _m.get_ceiling("quotaA")
    _m.observe_429("quotaA", retry_after=1.0)
    _after = _m.get_ceiling("quotaA")
    assert _after == max(CEILING_MIN_RPM, _before * CEILING_MD)
    assert _after < _before


def test_floor_on_repeated_429():
    _m = _meter()
    _m.ensure_window("quotaA", metered_flag=True)
    for _ in range(20):
        _m.observe_429("quotaA", retry_after=1.0)
    assert _m.get_ceiling("quotaA") == CEILING_MIN_RPM


def test_additive_increase_after_probe():
    _m = _meter()
    _m.ensure_window("quotaA", metered_flag=True)
    _m.observe_429("quotaA", retry_after=1.0)
    _low = _m.get_ceiling("quotaA")
    # Advance past the probe period
    _w = _m._windows["quotaA"]
    _w.last_429_at = time.time() - (CEILING_PROBE_S + 1)
    _m.record_request("quotaA", tokens=10, priority=0, estimated=False)
    _high = _m.get_ceiling("quotaA")
    assert _high == min(_low + CEILING_AI_RPM, CEILING_MAX_RPM)
    assert _high > _low


def test_ceilings_independent_per_provider():
    _m = _meter()
    _m.ensure_window("quotaA", metered_flag=True)
    _m.ensure_window("quotaB", metered_flag=True)
    _m.observe_429("quotaA", retry_after=1.0)
    _a = _m.get_ceiling("quotaA")
    _b = _m.get_ceiling("quotaB")
    assert _a < CEILING_INIT_RPM
    assert _b == CEILING_INIT_RPM  # untouched


def test_hard_rail_never_exceeded():
    _m = _meter()
    _m.ensure_window("quotaA", metered_flag=True)
    # Force learned ceiling above the hard rail
    _m._windows["quotaA"].ceiling_rpm = PHASE_HARD_MAX_RPM * 5
    _eff = _m.get_ceiling("quotaA")
    assert _eff <= PHASE_HARD_MAX_RPM
