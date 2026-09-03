"""
Unit tests for ProviderRateMeter sliding window (T2.1 / T2.2 / REQ-6).

Covers:
  * record_request / draw keyed by quota identity
  * age-based eviction (samples older than METER_WINDOW_S excluded)
  * count bound (deque maxlen = METER_MAX_SAMPLES)
  * draw() is side-effect free (does not mutate samples)
"""
import time

from backend.agent.rate_meter import (
    METER_MAX_SAMPLES,
    METER_WINDOW_S,
    ProviderRateMeter,
    clear_ceilings_for_testing,
    get_rate_meter,
    reset_rate_meter_for_testing,
)


def _meter():
    reset_rate_meter_for_testing()
    clear_ceilings_for_testing()
    return get_rate_meter()


def test_record_and_draw_keyed_by_quota():
    _m = _meter()
    _m.record_request("quotaA", tokens=100, priority=0, estimated=False, label="inst1")
    _m.record_request("quotaA", tokens=50, priority=0, estimated=False, label="inst1")
    _m.record_request("quotaB", tokens=10, priority=0, estimated=False)
    _a = _m.draw("quotaA")
    _b = _m.draw("quotaB")
    assert _a["requests"] == 2
    assert _a["tokens"] == 150
    assert _b["requests"] == 1
    assert _b["tokens"] == 10


def test_draw_is_side_effect_free():
    _m = _meter()
    _m.record_request("quotaA", tokens=100, priority=0, estimated=False)
    _before = _m.draw("quotaA")
    # Calling draw() again must not change the window
    _after = _m.draw("quotaA")
    assert _before == _after
    assert _before["requests"] == 1


def test_age_based_eviction():
    _m = _meter()
    _m.record_request("quotaA", tokens=100, priority=0, estimated=False)
    # Simulate an old sample by manipulating the window directly
    _w = _m._windows["quotaA"]
    _old_ts = time.time() - (METER_WINDOW_S + 10)
    _w.samples[0] = _w.samples[0].__class__(_old_ts, 100, False, 0)
    _m.record_request("quotaA", tokens=50, priority=0, estimated=False)
    _d = _m.draw("quotaA")
    # The old sample is outside the window → only the recent one counts
    assert _d["requests"] == 1
    assert _d["tokens"] == 50


def test_count_bound():
    _m = _meter()
    for _i in range(METER_MAX_SAMPLES + 50):
        _m.record_request("quotaA", tokens=1, priority=0, estimated=False)
    _d = _m.draw("quotaA")
    # deque maxlen caps stored samples
    assert _d["requests"] <= METER_MAX_SAMPLES


def test_label_retained_for_logs():
    _m = _meter()
    _m.record_request("quotaA", tokens=10, priority=0, estimated=False, label="instX")
    assert "instX" in _m._windows["quotaA"].label_ids
