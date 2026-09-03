"""
Tests for CallClass ContextVar lifecycle (T3.1 / REQ-14).
"""
from backend.agent.call_context import (
    CallClass,
    call_class,
    is_high_priority,
    set_call_class,
)


def test_default_is_background():
    """REQ-14 AC3: unclassified calls default to BACKGROUND (gated)."""
    assert call_class() == CallClass.BACKGROUND


def test_set_and_read():
    set_call_class(CallClass.SPEAK)
    assert call_class() == CallClass.SPEAK


def test_high_priority_speak():
    assert is_high_priority(CallClass.SPEAK) is True


def test_graft_is_not_high_priority():
    """REQ-14 AC2 / F6: GRAFT must be GATED, not exempt.

    Graft is recovery-plan generation fired AFTER a step failure — including a
    429-caused one (REQ-3 AC4 routes rate-limited steps to graft). Exempting it
    would create a 429 -> graft -> 429 amplification loop, the opposite of the
    scheduler's purpose. Supersedes the earlier `test_high_priority_graft`, which
    asserted the pre-F6 behavior.
    """
    assert is_high_priority(CallClass.GRAFT) is False


def test_low_priority_reason():
    assert is_high_priority(CallClass.REASON) is False


def test_low_priority_tool():
    assert is_high_priority(CallClass.TOOL) is False


def test_low_priority_background():
    assert is_high_priority(CallClass.BACKGROUND) is False
