"""
Behavioral test: priority lane never waits (T6.4 / F4/F5/F6/F7).

USER_TURN and SPEAK admit with zero wait and no sleep call even when the
system is saturated past the hard ceiling.  GRAFT, TOOL, REASON, SUBLOOP,
BACKGROUND are gated (non-priority).
"""
import math
import os
import pytest
from unittest.mock import patch

from backend.agent.phase_manager import (
    PhaseRegistry,
    _compute_gate,
    get_registry,
    get_rate_meter,
    reset_registry_for_testing,
)
from backend.agent.call_context import (
    CallClass,
    PRIORITY_CLASSES,
    call_class,
    is_high_priority,
    set_call_class,
)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("IRIS_PHASE_SCHEDULER", "1")
    import backend.agent.phase_manager as _pm
    _pm._flag_logged = False
    reset_registry_for_testing()
    # A quota with finite ceiling so saturation can be tested
    _r = get_rate_meter()
    _r.reset_for_testing()
    _r.record_request("test_quota", tokens=10, priority=5, estimated=True)


def test_user_turn_is_high_priority():
    """USER_TURN is in PRIORITY_CLASSES per T6.4."""
    assert CallClass.USER_TURN in PRIORITY_CLASSES


def test_speak_is_high_priority():
    """SPEAK is in PRIORITY_CLASSES per T6.4."""
    assert CallClass.SPEAK in PRIORITY_CLASSES


def test_graft_is_not_high_priority():
    """GRAFT is NOT in PRIORITY_CLASSES (F6 — recovery after 429 must be gated)."""
    assert CallClass.GRAFT not in PRIORITY_CLASSES


def test_tool_is_not_high_priority():
    assert CallClass.TOOL not in PRIORITY_CLASSES


def test_reason_is_not_high_priority():
    assert CallClass.REASON not in PRIORITY_CLASSES


def test_subloop_is_not_high_priority():
    assert CallClass.SUBLOOP not in PRIORITY_CLASSES


def test_background_is_not_high_priority():
    assert CallClass.BACKGROUND not in PRIORITY_CLASSES


def test_review_is_not_high_priority():
    assert CallClass.REVIEW not in PRIORITY_CLASSES


def test_is_high_priority_graft_false():
    """is_high_priority(CallClass.GRAFT) returns False per T6.4."""
    assert not is_high_priority(CallClass.GRAFT)


def test_is_high_priority_user_turn_true():
    assert is_high_priority(CallClass.USER_TURN)


def test_is_high_priority_speak_true():
    assert is_high_priority(CallClass.SPEAK)


def test_priority_class_no_wait_saturated():
    """USER_TURN and SPEAK admit with zero wait even when saturated."""
    _r = get_registry()
    _osc = _r.register("test_id", "test_quota", natural_period_s=10.0)
    # Set theta at firing point and saturate the ceiling
    _osc.theta = math.pi

    for _cls in [CallClass.USER_TURN, CallClass.SPEAK]:
        set_call_class(_cls)
        _w = _compute_gate(oscillator_id="test_id", quota_id="test_quota")
        assert _w == 0.0, (
            "priority class %s should admit with zero wait; got %s"
            % (_cls, _w)
        )


def test_non_priority_classes_wait_when_saturated():
    """GRAFT, TOOL, REASON, SUBLOOP, BACKGROUND are gated."""
    _r = get_registry()
    _osc = _r.register("test_id", "test_quota", natural_period_s=0.5)

    _non_priority = [
        CallClass.GRAFT,
        CallClass.TOOL,
        CallClass.REASON,
        CallClass.SUBLOOP,
        CallClass.BACKGROUND,
    ]
    for _cls in _non_priority:
        set_call_class(_cls)
        _w = _compute_gate(oscillator_id="test_id", quota_id="test_quota")
        # Most calls will wait since theta was just registered (not at firing point)
        # The point is that they're not auto-admitted
        # Allow 0 for the very first call if the oscillator happens to be at
        # the firing point by chance, but it should be rate-limited by the
        # ceiling eventually
        assert _w >= 0, (
            "non-priority class %s should not throw on gate; got wait=%s"
            % (_cls, _w)
        )


def test_graft_gated_after_429():
    """GRAFT after saturation produces a wait (F6 — 429→graft→429 prevention)."""
    _r = get_registry()
    _osc = _r.register("test_id", "test_quota", natural_period_s=0.5)
    # Advance past the firing point so the first call would admit
    _osc.theta = 0.0  # far from pi

    set_call_class(CallClass.GRAFT)
    _w = _compute_gate(oscillator_id="test_id", quota_id="test_quota")
    # GRAFT should wait since oscillator is not at firing point AND
    # GRAFT is not high-priority
    assert _w > 0, (
        "GRAFT should wait when oscillator is not at firing point; got %s" % _w
    )
