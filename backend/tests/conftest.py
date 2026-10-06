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
import tempfile as _tempfile

# The API transport persists a per-model call-time profile (stall bound, C6).
# Tests write it too: point it at a temp file so no test result lands in the
# app's data/model_call_times.json (it did once, 2026-10-02).
os.environ.setdefault(
    "IRIS_MODEL_CALL_PROFILE",
    os.path.join(_tempfile.gettempdir(), "iris-tests-model_call_times.json"),
)
import sys

def pytest_addoption(parser):
    parser.addoption(
        "--run-expected-failures",
        action="store_true",
        default=False,
        help="run backend/tests/expected_failures as real failures (default: xfail)",
    )

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


# ── Approval-UI precondition for permission tests (goal-contract T15) ────────
#
# REQ-9 AC9.5 (specs/goal-contract-coverage): when NO approval UI is attached
# the bridge now fail-fasts with APPROVAL_UNAVAILABLE instead of waiting out
# the permission timeout. The permission suites below were written against the
# old world, where the gate always waited — their subject is the APPROVAL FLOW
# (deny blocks / approve runs / timeout denies), not the no-UI fail-fast. This
# fixture restores their precondition (an attached approval UI) so they keep
# testing what they were written to test; the no-UI path is pinned separately
# by BT-GC6 in backend/tests/behavioral/test_goal_contract_coverage.py.
@_pytest.fixture
def approval_ui_attached(monkeypatch):
    """Simulate a live approval UI for the session (REQ-12 AC12.1)."""
    from backend.agent import tool_bridge as _tb

    monkeypatch.setattr(_tb, "_approval_ui_attached", lambda _sid: True)
    yield


# ── Real ONNX decision backend (specs/tool-decision-engine REQ-30) ──────────
#
# The Wave 10 tasks (T38–T42) tune the REAL runner: session options, the label
# structure cache, and the encode/session-run counts only exist on a live
# onnxruntime session. These fixtures load it once per session and skip cleanly
# when the model directory is absent, so the suites stay runnable on a machine
# without the 642 MB export (the engine's own contract is "degrade, never
# raise" — a skipped tuning test is honest, a fabricated one is not).
@_pytest.fixture(scope="session")
def onnx_backend():
    """A loaded `GlinerOnnx`, or skip when the model is unavailable."""
    from backend.agent.decision_backend_onnx import GlinerOnnx

    backend = GlinerOnnx()
    if not backend.load():
        _pytest.skip("ONNX decision model unavailable — tuning tests skipped")
    yield backend
    try:
        backend.shutdown()
    except Exception:  # noqa: BLE001 — teardown is best-effort
        pass


@_pytest.fixture(scope="session")
def onnx_runner(onnx_backend):
    """The live `_OnnxRunner` behind the loaded backend."""
    return onnx_backend._runner


# ── Oracle enforcement chokepoint, for tests that exercise a DECIDING consumer ──
#
# Oracle Stage B (2026-10-05): the Oracle's verdict replaces a rule or the Brain
# ONLY when `decision_engine.decides(consumer)` says so - the owner switched the
# consumer on (IRIS_DECISION_ENFORCE, default EMPTY), its bar record is
# `enforced` on the active engine, a threshold was fitted for it, and the
# configuration is not stale. Tests written before that built a stand-in engine
# and expected it to decide (tool_choice "enforced at birth"). Those tests check
# the MECHANICS of the deciding path (menu, cache, ledger rows, evidence seam,
# recovery), not whether the Oracle has earned the right, so they declare which
# consumers decide and this fixture turns the REAL chokepoint on for them,
# against tmp files (never the real bar record or calibration):
#
#     ORACLE_DECIDES = ("tool_choice",)
#     pytestmark = pytest.mark.usefixtures("oracle_decides_module")
#
# The calibration map is the identity on [0.5, 1.0] and the threshold is 0.85, so
# a stand-in confidence of 0.99 acts and 0.40 does not - the same split the
# tests' old raw threshold (0.85) gave.
def _enable_oracle(monkeypatch, tmp_path, consumers, threshold=0.85):
    import json as _json

    from backend.agent import consumer_bar as _cb
    from backend.agent import decision_engine as _de
    from backend.agent import oracle_calibration as _oc

    consumers = tuple(consumers)
    backend = "test-engine-int8"
    bar = {
        c: {"consumer_id": c, "rows": 120, "precision": 0.95, "ece": 0.01,
            "status": "enforced", "gap": "", "config": {"backend_id": backend}}
        for c in consumers
    }
    cal = {backend: {
        c: {"knots": [[0.5, 0.5], [1.0, 1.0]], "threshold": threshold} for c in consumers
    }}
    (tmp_path / "bar.json").write_text(_json.dumps(bar), encoding="utf-8")
    (tmp_path / "cal.json").write_text(_json.dumps(cal), encoding="utf-8")
    monkeypatch.setattr(_cb, "BAR_PATH", tmp_path / "bar.json")
    monkeypatch.setattr(_oc, "CALIBRATION_PATH", tmp_path / "cal.json")
    _oc._CACHE.clear()
    monkeypatch.setenv("IRIS_DECISION_ENFORCE", ",".join(consumers))
    monkeypatch.setattr(_de, "_current_backend_identity", lambda: backend)
    monkeypatch.setattr(_de, "_config_stale", lambda: False)
    monkeypatch.setattr(_de, "_ENFORCEMENT_LOGGED", True)


@_pytest.fixture
def oracle_decides_module(request, monkeypatch, tmp_path):
    """Turn the chokepoint on for the consumers in the module's ORACLE_DECIDES."""
    _enable_oracle(monkeypatch, tmp_path, getattr(request.module, "ORACLE_DECIDES", ()))
    yield


@_pytest.fixture
def oracle_decides(monkeypatch, tmp_path):
    """Callable form: `oracle_decides("presentation")` turns the chokepoint on for
    those consumers from that point of the test on."""
    def _enable(*consumers, threshold=0.85):
        _enable_oracle(monkeypatch, tmp_path, consumers, threshold)

    return _enable


# ── No Oracle shadow score may outlive its test body (Oracle Stage B, 2026-10-05) ──
#
# Shadow scores now run on the `oracle_shadow` lane (a daemon thread), not inline
# on the caller. A test that drives a code path which scores the Oracle starts a
# job that loads the REAL engine (about 5 s, heavy native imports) and used to
# finish INSIDE the test body, on the test's own thread. On the lane it runs
# concurrently with pytest's own end-of-test reporting, and on this Windows
# machine that races: measured, test_wave5_replay_behavior died 4 runs in 5 with
# `OSError: [Errno 9] Bad file descriptor` in pytest's terminal flush
# (INTERNALERROR) while the job was loading the model (`JOB START
# surface:escalate_incomplete` logged, `JOB END` only after the session was
# gone); fd 1 polled os.fstat() reads "The handle is invalid" in short windows
# while lane threads run. At HEAD, 12 runs in 12 passed because the inline load
# kept the main thread busy until the lane jobs had settled. Draining the lane
# when the test body returns - before the call phase is reported - restores that
# boundary without changing any test.
@_pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    yield
    try:
        from backend.utils.durability_queue import lane as _lane

        _lane("oracle_shadow").flush(60.0)
    except Exception:  # noqa: BLE001 - teardown is best-effort
        pass
