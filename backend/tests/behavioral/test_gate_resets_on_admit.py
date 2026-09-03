"""
Behavioral test: gate resets theta ON ADMIT (T6.3 / F3).

A call admitted (wait <= 0) must move the oscillator off its firing point
so a second immediate call is NOT auto-admitted.  This test checks that
the gate reset on admit prevents double-fire.
"""
import math
import time as _time
import uuid as _uuid

import pytest

from backend.agent.phase_manager import (
    PhaseRegistry,
    _compute_gate,
    get_registry,
    get_rate_meter,
    reset_registry_for_testing,
)
from backend.agent.call_context import CallClass, set_call_class


def _uid(tag: str) -> str:
    """Unique registry keys per test.

    The phase registry is a PROCESS-WIDE singleton. Shared literal ids like
    "test_id" can be mutated by a background thread leaked from an unrelated
    test (the real-app crawl tests boot a FastAPI app), producing failures
    that only appear in a full-suite run. Unique ids remove that coupling.
    """
    return f"{tag}-{_uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch):
    monkeypatch.setenv("IRIS_PHASE_SCHEDULER", "1")
    # Force re-read of the cached flag
    import backend.agent.phase_manager as _pm
    _pm._flag_logged = False
    reset_registry_for_testing()
    # Each test primes its OWN unique quota via _uid() (see that docstring), so
    # nothing is primed here — a shared literal quota is exactly what let an
    # unrelated test's leaked thread break this file in full-suite runs.
    set_call_class(CallClass.BACKGROUND)  # non-priority so the gate engages
    yield


def test_second_call_not_auto_admitted():
    """After an admit, the oscillator is reset by +π so a second immediate
    call is NOT auto-admitted (T6.3)."""

    # Register an oscillator with a finite ceiling so the gate engages
    _r = get_registry()
    _oid, _qid = _uid("osc"), _uid("quota")
    get_rate_meter().ensure_window(_qid, True)
    get_rate_meter().record_request(_qid, tokens=10, priority=0, estimated=True)
    _osc = _r.register(_oid, _qid, natural_period_s=1.0)

    # Set theta to pi (firing point) so the first call is admitted immediately
    _osc.theta = math.pi
    # REQ-12 AC4 / N5: dt is CLAMPED, not skipped, so a stale timestamp
    # would advance theta by TICK_MAX_DT_S. Mark it freshly advanced so dt~0
    # and theta stays where this test puts it.
    _osc.last_advance_at = _time.time()

    # First call: should admit (wait <= 0)
    _w1 = _compute_gate(oscillator_id=_oid, quota_id=_qid)
    assert _w1 == 0.0, (
        "First call at firing point should admit; got wait=%s" % _w1
    )

    # After admit, theta should have been reset (by +π mod 2π)
    # pi + pi = 2π mod 2π = 0, so theta should be ~0
    # Same tolerance note as below: theta advances by omega*dt (omega ~ 6.28
    # rad/s at period=1.0) before the reset, so a 1e-6 bound would be asserting
    # sub-microsecond scheduler timing rather than the reset itself. 1e-2 still
    # pins "theta was reset by +pi" to within 1% of a radian.
    assert _osc.theta == pytest.approx(0.0, abs=1e-2), (
        "Theta should be reset by +π on admit; got theta=%s" % _osc.theta
    )

    # Second call: should NOT be auto-admitted — theta is at 0, not pi
    _w2 = _compute_gate(oscillator_id=_oid, quota_id=_qid)
    assert _w2 > 0, (
        "Second call after admit should wait; got wait=%s" % _w2
    )


def test_admit_resets_even_with_small_advance():
    """Even with natural advancement, admit resets theta away from firing point."""
    _r = get_registry()
    _oid, _qid = _uid("osc"), _uid("quota")
    get_rate_meter().ensure_window(_qid, True)
    get_rate_meter().record_request(_qid, tokens=10, priority=0, estimated=True)
    _osc = _r.register(_oid, _qid, natural_period_s=1.0)

    # Theta just before pi — should get a very small wait or 0
    _osc.theta = math.pi - 0.01
    # REQ-12 AC4 / N5: dt is CLAMPED, not skipped, so a stale timestamp
    # would advance theta by TICK_MAX_DT_S. Mark it freshly advanced so dt~0
    # and theta stays where this test puts it.
    _osc.last_advance_at = _time.time()

    _w = _compute_gate(oscillator_id=_oid, quota_id=_qid)
    if _w == 0.0:
        # Was admitted → theta reset
        assert _osc.theta != pytest.approx(math.pi - 0.01, abs=1e-6), (
            "Theta should have been reset after admit"
        )
        # New theta should be (old_theta + pi) % 2pi
        # Tolerance note: theta also advances naturally by omega*dt before the
        # reset (omega ~ 6.28 rad/s at period=1.0, so even ~20us of real elapsed
        # time exceeds 1e-4 rad). 1e-2 keeps the assertion meaningful — it still
        # pins the +pi reset to within 1% of a radian — while not depending on
        # sub-millisecond scheduler timing.
        assert _osc.theta == pytest.approx(
            (math.pi - 0.01 + math.pi) % (2 * math.pi), abs=1e-2
        )
