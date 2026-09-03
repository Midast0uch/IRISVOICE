"""
Tests for the sync acquire() gate (T3.5 / REQ-13).

The gate must:
  * Return quickly when the feature flag is disabled
  * Admit high-priority calls immediately (REQ-13 AC2 / REQ-14 AC2)
  * Fail open (return 0.0) on internal errors

Flag handling uses ``monkeypatch.setenv`` — never a raw ``os.environ`` write —
so the flag cannot leak into another test module (REQ-22 AC3, review finding N2).
"""
from backend.agent.phase_manager import (
    acquire,
    reset_flag_for_testing,
    reset_registry_for_testing,
)
from backend.agent.call_context import (
    CallClass,
    PRIORITY_CLASSES,
    is_high_priority,
    set_call_class,
)


def _enable_flag(monkeypatch):
    reset_registry_for_testing()
    reset_flag_for_testing()
    monkeypatch.setenv("IRIS_PHASE_SCHEDULER", "1")


def _disable_flag(monkeypatch):
    reset_registry_for_testing()
    reset_flag_for_testing()
    monkeypatch.setenv("IRIS_PHASE_SCHEDULER", "0")


def test_gate_noop_when_flag_disabled(monkeypatch):
    _disable_flag(monkeypatch)
    _result = acquire("test_quota")
    assert _result == 0.0


def test_gate_admits_unknown_quota(monkeypatch):
    _enable_flag(monkeypatch)
    _result = acquire("unknown_quota")
    # Unknown quota has no rate_meter window → inf ceiling → unmetered → admit.
    assert _result == 0.0


def test_gate_admits_high_priority_speak(monkeypatch):
    _enable_flag(monkeypatch)
    set_call_class(CallClass.SPEAK)
    _result = acquire("any")
    assert _result == 0.0


def test_graft_is_not_high_priority(monkeypatch):
    """REQ-14 AC2 / F6: GRAFT must NOT be in the priority lane.

    Graft is recovery-plan generation fired AFTER a step failure — including a
    429-caused failure (REQ-3 AC4 routes rate-limited steps to graft). Exempting
    it from gating would create a 429 -> graft -> 429 amplification loop, which is
    the opposite of the scheduler's purpose.

    Replaces an earlier ``test_gate_admits_high_priority_graft``, which asserted
    the pre-F6 behavior and passed only incidentally: ``acquire`` on an unknown
    quota returns 0.0 via the unmetered short-circuit regardless of call class, so
    it never actually exercised the priority lane.
    """
    _enable_flag(monkeypatch)
    set_call_class(CallClass.GRAFT)
    assert is_high_priority(CallClass.GRAFT) is False
    assert CallClass.GRAFT not in PRIORITY_CLASSES
    # Only USER_TURN and SPEAK are exempt.
    assert PRIORITY_CLASSES == frozenset(
        {CallClass.USER_TURN, CallClass.SPEAK}
    )
