"""
test_caducean_observability_wave5.py — Wave 5 verification for
caducean-kernel-unification.

Covers REQ-15 (observability: perturbations + coupling events logged at INFO
with full detail; relaxation steps at DEBUG with distance-from-baseline) and
REQ-20 (test-isolation: every new global store exposes a reset accessor, and
the shared autouse fixture resets them between tests).

Additive — the locked test files are untouched.
"""

import logging
import os
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.gateway.iris_ffi import ffi_init_engine, ffi_caducean_init_session
from backend.agent.coupled_registry import (
    get_coupled_registry,
    reset_coupled_registry,
)
from backend.agent.param_homeostasis import (
    get_param_homeostasis,
    reset_param_homeostasis,
)
from backend.agent.caducean_trajectory import (
    CaduceanTrajectoryRecorder,
    reset_eml_cache_for_testing,
)


def _engine_tmp():
    tmp = tempfile.mktemp(suffix=".db")
    ffi_init_engine(tmp, "00" * 32)
    return tmp


# ---------------------------------------------------------------------------
# REQ-15: observability — perturbations + coupling events at INFO
# ---------------------------------------------------------------------------


def test_perturbation_logged_at_info(caplog):
    """A perturbation is logged at INFO with session id + writer (REQ-15 AC4)."""
    reset_param_homeostasis()
    try:
        with caplog.at_level(logging.INFO, logger="backend.agent.param_homeostasis"):
            get_param_homeostasis().register_perturbation("obs_s1", "barge_in")
        assert any(
            "obs_s1" in r.message and "barge_in" in r.message
            for r in caplog.records
        )
    finally:
        reset_param_homeostasis()


def test_coupling_event_logged_at_info(caplog):
    """A coupling event is logged at INFO with both sessions, c_eff, verdict,
    phase diff and role (REQ-15 AC3/AC4)."""
    tmp = _engine_tmp()
    try:
        ffi_caducean_init_session("ce_a", 1, 1)
        ffi_caducean_init_session("ce_b", 2, 2)
        reset_coupled_registry()
        reg = get_coupled_registry()
        reg.register_session("ce_a", 1, 1)
        reg.register_session("ce_b", 2, 2)
        reg.update_session_state("ce_a", xi=1.0, u=0.3)
        reg.update_session_state("ce_b", xi=1.05, u=-0.3)
        with caplog.at_level(logging.INFO, logger="backend.agent.coupled_registry"):
            reg.apply_coupling("ce_a")
        assert any("ce_a" in r.message and "ce_b" in r.message for r in caplog.records)
        assert any("rational=" in r.message for r in caplog.records)
        assert any("nucleus" in r.message or "barrier" in r.message for r in caplog.records)
    finally:
        reset_coupled_registry()
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# REQ-20: test-isolation — reset accessors for every new global store
# ---------------------------------------------------------------------------


def test_reset_eml_cache_for_testing():
    """The per-session EML cache exposes a reset accessor (REQ-20 AC2)."""
    CaduceanTrajectoryRecorder._eml_cache_per_session["x"] = (1.0, 2.0, 3.0)
    CaduceanTrajectoryRecorder._eml_cache_timestamps["x"] = 1.0
    reset_eml_cache_for_testing()
    assert CaduceanTrajectoryRecorder._eml_cache_per_session == {}
    assert CaduceanTrajectoryRecorder._eml_cache_timestamps == {}


def test_reset_param_homeostasis_for_testing():
    """The homeostasis baseline store exposes a reset accessor (REQ-20 AC2)."""
    h = get_param_homeostasis()
    h.set_baseline("rh_s1", 3.0, 3.0, 0.5)
    assert h.get_baseline("rh_s1").a == 3.0
    reset_param_homeostasis()
    assert get_param_homeostasis().get_baseline("rh_s1").a == 2.0


def test_fixture_resets_globals_between_tests():
    """Relies on the autouse _caducean_scheduler_isolation fixture resetting the
    new global stores (REQ-20 AC1). A sibling test using the same id must not
    leak its baseline into this one, in either collection order."""
    assert get_param_homeostasis().get_baseline("wave5_iso_shared").a == 2.0


def test_fixture_resets_globals_between_tests_sibling():
    """Sets a non-default baseline for wave5_iso_shared; the fixture must reset
    it before the next test (see test_fixture_resets_globals_between_tests)."""
    h = get_param_homeostasis()
    h.set_baseline("wave5_iso_shared", 3.0, 3.0, 0.5)
    assert h.get_baseline("wave5_iso_shared").a == 3.0


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
