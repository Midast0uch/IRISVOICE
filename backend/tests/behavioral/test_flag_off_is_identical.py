"""
Behavioral test: IRIS_PHASE_SCHEDULER=OFF preserves identical behavior to
no flag (no advance, no metering, no coupling).

This test patches the environment variable and confirms that when the flag
is off, acquire() returns 0.0 immediately and no oscillator state changes.
"""
import math
import os
import uuid as _uuid

import pytest

from unittest.mock import patch

from backend.agent.phase_manager import (
    PhaseRegistry,
    acquire,
    get_registry,
    reset_registry_for_testing,
)
from backend.agent.call_context import CallClass, call_class, set_call_class


def _uid(tag: str) -> str:
    """Unique registry/quota keys per test.

    The phase registry and rate meter are PROCESS-WIDE singletons, so shared
    literal ids can be mutated by a thread leaked from an unrelated test (the
    real-app crawl tests boot a FastAPI app). That produced failures visible only
    in full-suite runs. Unique ids remove the coupling.
    """
    return f"{tag}-{_uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def clean():
    """Reset registry and ensure quota is metered (finite ceiling) so that
    flag-on tests exercise the full gate path and create oscillators."""
    from backend.agent.phase_manager import get_rate_meter
    reset_registry_for_testing()
    get_rate_meter().reset_for_testing()
    # Each test primes its OWN unique quota (see _uid) rather than a shared one.
    set_call_class(CallClass.BACKGROUND)
    yield


def test_flag_off_returns_zero_wait():
    """When IRIS_PHASE_SCHEDULER=0, acquire returns 0.0."""
    with patch.dict(os.environ, {"IRIS_PHASE_SCHEDULER": "0"}, clear=False):
        # Re-check the flag (the module caches it, so we need to force a re-read)
        import backend.agent.phase_manager as _pm
        # Hard-reset the cached flag
        _pm._flag_logged = False
        _w = acquire(oscillator_id="test_id", quota_id="test_q")
        assert _w == 0.0, (
            "Flag off should return 0 wait; got %s" % _w
        )


def test_flag_off_no_oscillator_created():
    """When IRIS_PHASE_SCHEDULER=0, acquire should NOT create an oscillator."""
    with patch.dict(os.environ, {"IRIS_PHASE_SCHEDULER": "0"}, clear=False):
        import backend.agent.phase_manager as _pm
        _pm._flag_logged = False
        acquire(oscillator_id="test_id", quota_id="test_q")
        # No oscillator should exist
        assert get_registry().get("test_id") is None, (
            "Oscillator should not be created when flag is off"
        )


def test_flag_on_creates_oscillator():
    """When IRIS_PHASE_SCHEDULER=1, acquire creates an oscillator normally."""
    _oid, _qid = _uid("osc"), _uid("quota")
    with patch.dict(os.environ, {"IRIS_PHASE_SCHEDULER": "1"}, clear=False):
        import backend.agent.phase_manager as _pm
        _pm._flag_logged = False
        # An unmetered quota short-circuits BEFORE registration (REQ-8 AC2), so
        # give this quota a metered window to exercise the path this test names.
        from backend.agent.rate_meter import get_rate_meter as _grm
        _grm().ensure_window(_qid, True)
        _grm().record_request(_qid, tokens=1, priority=0, estimated=True)
        acquire(oscillator_id=_oid, quota_id=_qid)
        # Oscillator should exist
        assert get_registry().get(_oid) is not None, (
            "Oscillator should be created when flag is on; "
            "flag=%r ceiling=%r cls=%r n_osc=%d"
            % (
                os.environ.get("IRIS_PHASE_SCHEDULER"),
                _grm().get_ceiling(_qid),
                call_class(),
                len(get_registry().snapshot()),
            )
        )
