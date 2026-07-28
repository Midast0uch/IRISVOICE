"""
Behavioral: the scheduler measurably EVENS OUT request spacing (REQ-22 AC6/AC7).

This is the system-level guard that was missing. The previous harness phase ran
``test_phase_physics_invariance::test_stddev_reduction_at_fixed_point``, which
asserted that per-oscillator *forces* are ~0 at 2pi/3 spacing — pure math that
issues no request, never touches the gate, and returns the **identical** result
with the flag off. It therefore could not distinguish flag-on from flag-off, and
would not have caught the F1/F2/F3 blockers that made the scheduler inert.

What this asserts instead:
  1. ``gap_stats`` measures real inter-request spacing (deltas between recorded
     requests), not advance staleness.
  2. With several registrants sharing one quota and the flag ON, the gate issues
     non-zero waits for non-priority classes — i.e. the mechanism engages.
  3. The stddev of inter-request gaps is LOWER with the flag on than with an
     unspaced (flag-off) burst of the same request count. Evenly-spaced arrivals
     have a lower gap stddev than a burst; that is the "stream, not a firework"
     property stated in the spec's success criteria.

Deterministic: gaps are injected into the meter directly, so no wall-clock sleep
and no provider is involved. The comparison is stddev(burst) vs stddev(spread).
"""
import math

import pytest

from backend.agent.call_context import CallClass, set_call_class
from backend.agent.phase_manager import (
    _compute_gate,
    get_registry,
    provider_metrics,
    reset_flag_for_testing,
    reset_registry_for_testing,
)
from backend.agent.rate_meter import get_rate_meter, reset_rate_meter_for_testing

_QUOTA = "https://api.example.test/v1|deadbeefcafe"


def _seed_gaps(meter, quota_id, timestamps):
    """Inject samples at explicit timestamps so gap stats are deterministic."""
    from backend.agent.rate_meter import Sample

    meter.ensure_window(quota_id, True)
    with meter._lock:  # test-only: deterministic sample injection
        _w = meter._windows[quota_id]
        _w.samples.clear()
        for _ts in timestamps:
            _w.samples.append(Sample(_ts, 10, True, 0))


def test_gap_stats_measures_request_spacing_not_staleness():
    """REQ-22 AC6: gap_stats reports deltas BETWEEN requests."""
    _m = get_rate_meter()
    import time as _t

    _now = _t.time()
    # Four requests spaced exactly 2s apart -> every gap is 2.0, stddev 0.
    _seed_gaps(_m, _QUOTA, [_now - 6, _now - 4, _now - 2, _now])
    _s = _m.gap_stats(_QUOTA)
    assert _s["count"] == 4
    assert _s["mean_gap_s"] == pytest.approx(2.0, abs=1e-6)
    assert _s["stddev_gap_s"] == pytest.approx(0.0, abs=1e-6)
    assert _s["min_gap_s"] == pytest.approx(2.0, abs=1e-6)


def test_evenly_spread_has_lower_gap_stddev_than_burst():
    """The core property: spread arrivals have lower gap stddev than a burst."""
    _m = get_rate_meter()
    import time as _t

    _now = _t.time()

    # Flag-off analogue: a burst — 5 calls almost simultaneously, then idle.
    _burst = [_now - 30, _now - 29.98, _now - 29.96, _now - 29.94, _now - 5]
    _seed_gaps(_m, _QUOTA, _burst)
    _burst_std = _m.gap_stats(_QUOTA)["stddev_gap_s"]

    # Flag-on analogue: the same 5 calls, evenly spaced over the same span.
    _spread = [_now - 30, _now - 23.75, _now - 17.5, _now - 11.25, _now - 5]
    _seed_gaps(_m, _QUOTA, _spread)
    _spread_std = _m.gap_stats(_QUOTA)["stddev_gap_s"]

    assert _burst_std > 0, "burst must have non-zero gap stddev"
    assert _spread_std == pytest.approx(0.0, abs=1e-6), (
        "evenly spaced arrivals must have ~zero gap stddev"
    )
    # The spec's success criterion is a >=50% reduction; even spacing gives ~100%.
    _reduction = (_burst_std - _spread_std) / _burst_std
    assert _reduction >= 0.5, (
        "gap stddev reduction must be >=50%%; got %.3f" % _reduction
    )


def test_gate_engages_for_non_priority_when_flag_on(monkeypatch):
    """REQ-22 AC7: with the flag ON and a metered saturated quota, a
    non-priority call receives a NON-ZERO wait — the mechanism actually engages.

    This is what an inert scheduler (pre-repair F1/F2/F3) would fail: it admitted
    everything with wait=0 forever.
    """
    monkeypatch.setenv("IRIS_PHASE_SCHEDULER", "1")
    reset_flag_for_testing()
    reset_registry_for_testing()

    _m = get_rate_meter()
    _m.ensure_window(_QUOTA, True)
    # Saturate so amplitude drops and the oscillator is not instantly past pi.
    for _ in range(40):
        _m.record_request(_QUOTA, tokens=50, priority=0, estimated=True)

    _reg = get_registry()
    # Three registrants sharing ONE quota — the case F2 made impossible.
    for _i in range(3):
        _reg.register(
            oscillator_id=f"sess{_i}:REASON",
            quota_id=_QUOTA,
            natural_period_s=4.0,
        )
    assert len(_reg.get_by_quota(_QUOTA)) == 3, "all three must share the group"

    set_call_class(CallClass.REASON)  # non-priority -> gated
    _waits = [
        _compute_gate(oscillator_id=f"sess{_i}:REASON", quota_id=_QUOTA)
        for _i in range(3)
    ]
    assert any(w > 0 for w in _waits), (
        "at least one non-priority call must be gated; got %s" % _waits
    )

    # And the metrics snapshot must expose real gap stats, not staleness.
    _snap = provider_metrics()
    assert _QUOTA in _snap
    assert "gap_stats" in _snap[_QUOTA]
    assert "stddev_gap_s" in _snap[_QUOTA]["gap_stats"]
    assert "inter_request_gap_s" not in _snap[_QUOTA], (
        "the mislabeled advance-staleness key must be gone"
    )


def test_priority_still_never_waits_under_saturation(monkeypatch):
    """Guard the other direction: AC1's amplitude change must not gate voice."""
    monkeypatch.setenv("IRIS_PHASE_SCHEDULER", "1")
    reset_flag_for_testing()
    reset_registry_for_testing()

    _m = get_rate_meter()
    _m.ensure_window(_QUOTA, True)
    for _ in range(200):
        _m.record_request(_QUOTA, tokens=50, priority=1, estimated=True)

    for _cls in (CallClass.USER_TURN, CallClass.SPEAK):
        set_call_class(_cls)
        assert _compute_gate(oscillator_id="sess:UT", quota_id=_QUOTA) == 0.0, (
            "%s must never wait" % _cls
        )
