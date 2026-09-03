"""
Unit test: amplitude relaxation toward 1 - load_fraction (T3.4 / REQ-12).

When the rate ceiling is low (load → 1), amplitude should relax toward R_MIN.
When the ceiling is high (load → 0), amplitude should relax toward 1.0.
"""
import math
import pytest
import time

from backend.agent.phase_manager import (
    PhaseRegistry,
    get_registry,
    get_rate_meter,
    reset_registry_for_testing,
)
@pytest.fixture(autouse=True)
def clean():
    get_rate_meter().reset_for_testing()
    get_rate_meter().record_request(
        "test_q", tokens=10, priority=5, estimated=True
    )
    reset_registry_for_testing()
    yield


def test_amplitude_decreases_when_load_high():
    """Amplitude relaxes toward R_MIN when load_fraction → 1."""
    _rm = get_rate_meter()
    _rm.record_request("test_q", tokens=1, priority=5, estimated=True)

    _r = get_registry()
    _osc = _r.register("test_id", "test_q", natural_period_s=1.0)
    _osc.amplitude = 1.0  # start fully relaxed

    # Saturate the rate meter
    for _i in range(20):
        _rm.record_request("test_q", tokens=100, priority=5, estimated=True)

    # Advance — amplitude should decay toward R_MIN
    _r.advance_all("test_q")
    _r.advance_all("test_q")
    _r.advance_all("test_q")

    # Load is high → amplitude should have decreased
    assert _osc.amplitude < 1.0, "Amplitude should decrease under load"
    assert _osc.amplitude >= 0.1, "Amplitude should be floored at R_MIN"


def test_amplitude_increases_when_load_low():
    """Amplitude relaxes toward 1.0 when load_fraction → 0."""
    _rm = get_rate_meter()
    _rm.record_request("test_q", tokens=1, priority=1, estimated=True)

    _r = get_registry()
    _osc = _r.register("test_id2", "test_q", natural_period_s=1.0)
    _osc.amplitude = 0.1  # start at minimum
    # Simulate time passage by advancing last_advance_at 1s in the past so
    # the relaxation formula applies a meaningful delta.
    _osc.last_advance_at = time.time() - 1.0

    # Advance — amplitude should increase toward 1.0
    for _ in range(8):
        _r.advance_all("test_q")
        time.sleep(0.001)  # ensure dt > 0

    assert _osc.amplitude >= 0.15, (
        "Amplitude should increase when load is low; got %s" % _osc.amplitude
    )


def test_amplitude_stays_bounded():
    """Amplitude stays within [R_MIN, 1.0] regardless of load extremes."""
    _rm = get_rate_meter()
    _r = get_registry()
    _osc = _r.register("test_id3", "test_q", natural_period_s=1.0)

    for _ in range(20):
        _r.advance_all("test_q")
    assert 0.1 <= _osc.amplitude <= 1.0, (
        "Amplitude must stay in [R_MIN, 1.0]; got %s" % _osc.amplitude
    )
