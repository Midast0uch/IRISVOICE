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


# ── Module-identity isolation (the backend.* package graph) ───────────────
#
# DEBT FIX (pin_fd5b312e69bf / c01534199cdb): several suites probe imports by
# deleting/re-importing modules (test_scheduler_isolation, the VAD/tool-format
# importlib loaders). A delete+re-import installs a SECOND module object AND
# rebinds the parent package's attribute, leaving the graph inconsistent.
# Downstream this surfaced as order-dependent failures —
#   AttributeError: 'module' object at backend.agent has no attribute ...
# in every monkeypatch.setattr("backend.agent.…") call of the provider-switch,
# display-text, speak-envelope and task-start-revision suites — all passing in
# isolation. This autouse fixture repairs the graph around EVERY test: any
# backend.* module that was replaced gets its ORIGINAL object back, and each
# parent package's attribute is rebound to that original. Conservative: it
# never evicts modules it did not see before (intentional stubs survive).
@_pytest.fixture(autouse=True)
def _backend_module_identity_repair():
    import sys as _sys

    _saved = {
        _m: _mod
        for _m, _mod in _sys.modules.items()
        if _m == "backend" or _m.startswith("backend.")
    }
    yield

    for _m, _orig in _saved.items():
        _cur = _sys.modules.get(_m)
        if _cur is not _orig:
            _sys.modules[_m] = _orig
        _parent, _, _leaf = _m.rpartition(".")
        if _leaf:
            _parent_mod = _sys.modules.get(_parent)
            if _parent_mod is not None and getattr(_parent_mod, _leaf, None) is not _orig:
                try:
                    setattr(_parent_mod, _leaf, _orig)
                except Exception:
                    pass  # frozen/namespace parent — nothing to rebind


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


# ── Inference role-binding / provider-registry isolation ─────────────────
#
# Same class of problem as the scheduler fixture above, for the same reason:
# `RoleBindingTable` and `ProviderRegistry` are process-wide singletons by
# design (REQ-5 — role bindings live in ONE place, so the API endpoint and the
# live session cannot disagree about which provider serves which role).
#
# Until 2026-08-16 the leakage was masked: `InferenceRouter._apply_config` re-bound
# every role from config on EVERY router construction, and a router is built in
# every AgentKernel.__init__ — so any binding a test leaked was incidentally
# overwritten by the next test that constructed a kernel. That re-seeding was the
# bug (it also overwrote the USER's live choice on every new conversation, which
# is what made the ModelSwitcher revert), so config now seeds only unbound roles.
# Correct in production — there is one seed at startup and the user is the only
# writer — but it removes the accidental cleanup the suite had been relying on.
# Reset explicitly instead of depending on a bug to do it.
@_pytest.fixture(autouse=True)
def _inference_binding_isolation():
    """Restore the process-wide role table + provider registry around each test."""
    try:
        from backend.agent.inference.registry import get_provider_registry
        from backend.agent.inference.roles import get_role_binding_table
    except Exception:
        yield  # inference package unavailable — nothing to isolate
        return

    _reg = get_provider_registry()
    _roles = get_role_binding_table()
    _saved_providers = list(_reg.list())
    _saved_bindings = list(_roles.list())

    def _restore() -> None:
        try:
            for _b in list(_roles.list()):
                _roles.unbind(_b.role)
            for _b in _saved_bindings:
                _roles.bind(_b.role, _b.instance_id, _b.model_override)
            for _p in _saved_providers:
                _reg.add(_p)
        except Exception:
            pass

    yield
    _restore()


# ── Search-provider singleton isolation ──────────────────────────────────
#
# backend/crawler/search_providers/__init__.py caches its provider in a
# process-wide global (`_provider_instance`) and resolves it, on the first
# uncached call, by reading the REAL data/iris_config.json + EXA_API_KEY.
# That file legitimately carries provider="exa" with a live key for this
# deployment (field_values.search — see the Exa wiring fix). Now that
# crawl_planner.plan() calls get_search_provider() in production (it had
# zero callers before), the first test in a run that reaches an uncached
# call would construct a real ExaSearchProvider and could attempt a live
# network call using that committed key. Pre-seed the cache with a safe
# LLMSearchProvider for every test so no test resolves the real config
# unless it explicitly opts in (tests that exercise Exa selection patch
# get_search_provider or the cache directly).
@_pytest.fixture(autouse=True)
def _search_provider_isolation(monkeypatch):
    try:
        from backend.crawler import search_providers as _sp_mod
        from backend.crawler.search_providers.llm import LLMSearchProvider
    except Exception:
        yield  # search_providers package unavailable — nothing to isolate
        return

    monkeypatch.setattr(_sp_mod, "_provider_instance", LLMSearchProvider())
    yield
    monkeypatch.setattr(_sp_mod, "_provider_instance", None)
