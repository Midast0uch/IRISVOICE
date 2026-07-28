"""
Test configuration for backend tests.

History:
  - Previously this conftest monkey-patched `backend.conversation_store`
    to use a test SQLite path under project root, assuming the store
    was a SQLite-backed module.
  - In 2026, conversation_store was refactored to an in-memory store
    (pure Python dict). The old monkeypatch tried to set `_DB_PATH` and
    `_CONN` attributes that no longer exist, causing all pytest
    collection in backend/tests/ to fail with AttributeError.

Current behavior:
  - conversation_store is in-memory; no patching is required.
  - This conftest is intentionally a no-op. It exists for the sys.path
    setup and as a placeholder for any future test fixtures.
  - If conversation_store ever needs to be mocked or redirected in
    tests, add the fixture here.

Usage:
  python -m pytest backend/tests/ -v
"""

import os
import sys

# Ensure project root is on sys.path (so `from backend.X import Y` works)
_project_root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


# ── Caducean phase-scheduler isolation (REQ-22 AC3/AC4 — review finding N2) ──
#
# The scheduler uses PROCESS-WIDE singletons (PhaseRegistry, ProviderRateMeter),
# a module-level `_flag_logged` guard, and a PERSISTED ceilings file that
# get_rate_meter() reloads on construction. Without a shared reset, state leaks
# between test modules and the suite becomes order-dependent: before this fixture
# existed, test_flag_off_is_identical::test_flag_on_creates_oscillator and
# test_concurrent_exec_contract::test_ct2a_concurrent_acquire_same_quota both
# PASSED in isolation and FAILED in the full unit+contract run.
#
# Autouse + session-independent so every test starts from identical state,
# whatever the collection order or whether pytest-xdist is in play.
import pytest as _pytest


@_pytest.fixture(autouse=True)
def _caducean_scheduler_isolation(monkeypatch):
    """Reset all phase-scheduler global state around every test.

    Uses monkeypatch.delenv for IRIS_PHASE_SCHEDULER so a test that opts in with
    monkeypatch.setenv is automatically restored — never write os.environ
    directly in a scheduler test (REQ-22 AC3).
    """
    try:
        from backend.agent import phase_manager as _pm
        from backend.agent import rate_meter as _rm
    except Exception:
        yield  # scheduler modules unavailable — nothing to isolate
        return

    def _reset() -> None:
        try:
            _rm.clear_ceilings_for_testing()
            _rm.reset_rate_meter_for_testing()
            _pm.reset_registry_for_testing()
            _pm.reset_flag_for_testing()
        except Exception:
            pass
        # REQ-20 AC1: reset the global stores this spec adds so the suite stays
        # order-independent — homeostasis baselines (REQ-2), the per-session
        # EML cache (REQ-16), and the coupled-registry singleton (REQ-10). All
        # three expose reset_*_for_testing() accessors. The coupled registry is
        # a process-wide singleton, so the same order-dependence that bit the
        # scheduler applies here if it is not reset.
        try:
            from backend.agent.param_homeostasis import reset_param_homeostasis
            from backend.agent.caducean_trajectory import reset_eml_cache_for_testing
            from backend.agent.coupled_registry import reset_coupled_registry

            reset_param_homeostasis()
            reset_eml_cache_for_testing()
            reset_coupled_registry()
        except Exception:
            pass
        # The call class is a ContextVar, and pytest runs every test in ONE
        # thread — so a test that calls set_call_class(USER_TURN) without
        # restoring leaks the priority lane into whatever runs next, making the
        # gate admit with wait=0 and unrelated tests fail. This is review finding
        # N4 reproducing inside the suite; reset it to the BACKGROUND default so
        # each test starts gated (REQ-14 AC3).
        try:
            from backend.agent.call_context import CallClass, set_call_class

            set_call_class(CallClass.BACKGROUND)
        except Exception:
            pass

    # Default the flag OFF for every test; opt in via monkeypatch.setenv.
    monkeypatch.delenv("IRIS_PHASE_SCHEDULER", raising=False)
    _reset()
    yield
    _reset()
