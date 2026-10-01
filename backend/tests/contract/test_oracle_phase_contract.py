"""Contract tests: Oracle decisions under the Caducean phase model (P2).

Spec: specs/oracle-phase-concurrency (REQ-1, REQ-2). Design:
docs/architecture/PHASE_DOMAINS.md. Flag: IRIS_ORACLE_PHASE (default OFF).

Pins, with a stub backend that can be held mid-run:
  * each consumer is its own participant ("{session}:{consumer_id}") in the
    domain "decision.oracle_cpu", at distinct angles;
  * domains share code, never state: Oracle oscillators never appear in the
    router's phase_manager registry and vice versa; two domains never mix;
  * a priority-class decision bypasses the gate (wait 0, never registered);
  * two decisions are in flight at once - and MORE than the CPU's run capacity
    (the capacity is a load parameter, never a cap);
  * load/unload never races a run (shutdown waits for in-flight runs; the lazy
    load happens once under concurrent first use);
  * a gate fault admits the decision (fail-open);
  * flag off keeps the classical lock path;
  * the new module obeys CT-3 / CT-4 import discipline.
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest

import backend.agent.phase_domain as phase_domain_mod
from backend.agent import decision_engine as de
from backend.agent import phase_manager as pm
from backend.agent.call_context import CallClass, call_class_scope
from backend.agent.decision_engine import (
    CandidateScore,
    DecisionEngine,
    DecisionScore,
    EngineConfig,
)
from backend.agent.phase_domain import (
    PhaseDomain,
    get_phase_domain,
    reset_phase_domains_for_testing,
)

DOMAIN = "decision.oracle_cpu"


@pytest.fixture(autouse=True)
def _phase_on(monkeypatch):
    monkeypatch.setenv("IRIS_ORACLE_PHASE", "1")
    reset_phase_domains_for_testing()
    yield
    reset_phase_domains_for_testing()


class _Backend:
    """Stub backend. ``hold`` (optional) runs inside decide, i.e. mid-run."""

    model_id = "stub-onnx"

    def __init__(self, hold=None):
        self.hold = hold
        self.shutdown_called = threading.Event()
        self.running = 0
        self.max_running = 0
        self._lk = threading.Lock()

    def load(self) -> bool:
        return True

    def decide(self, consumer_id, options, frame, instruction=None):
        with self._lk:
            self.running += 1
            self.max_running = max(self.max_running, self.running)
        try:
            if self.hold is not None:
                self.hold()
            return DecisionScore(
                consumer_id=consumer_id, chosen=options[0], confidence=0.9,
                distribution=tuple(
                    CandidateScore(o, -0.1, 0.9 if o == options[0] else 0.1)
                    for o in options
                ),
                engine_latency_ms=1,
            )
        finally:
            with self._lk:
                self.running -= 1

    def shutdown(self) -> None:
        self.shutdown_called.set()


def _engine(backend, preload=True):
    eng = DecisionEngine(EngineConfig(), backend_factory=lambda **kw: backend)
    if preload:
        eng._backend = backend
        eng._load_attempted = True
    return eng


def _run_threads(targets):
    ts = [threading.Thread(target=t) for t in targets]
    for t in ts:
        t.start()
    return ts


# -- REQ-1: participants ------------------------------------------------------


class TestParticipants:
    def test_distinct_oscillators_per_consumer_in_the_oracle_domain(self):
        eng = _engine(_Backend())
        for cid in ("tool_choice", "narration", "done"):
            assert eng.decide(cid, ["a", "b"], {"goal": "g"}) is not None
        dom = get_phase_domain(DOMAIN, period_s=0.3, max_wait_s=0.3, k=0.6)
        oscs = dom.registry.get_by_quota(DOMAIN)
        ids = sorted(o.oscillator_id for o in oscs)
        assert ids == ["default:done", "default:narration", "default:tool_choice"]
        assert len({round(o.theta, 6) for o in oscs}) == 3, (
            "distinct participants must hold distinct angles"
        )

    def test_session_is_part_of_the_oscillator_id(self, monkeypatch):
        eng = _engine(_Backend())
        monkeypatch.setattr(de, "_oracle_session_id", lambda: "s1")
        eng.decide("tool_choice", ["a"], {"goal": "g"})
        monkeypatch.setattr(de, "_oracle_session_id", lambda: "s2")
        eng.decide("tool_choice", ["a"], {"goal": "g"})
        dom = get_phase_domain(DOMAIN, period_s=0.3, max_wait_s=0.3, k=0.6)
        assert sorted(o.oscillator_id for o in dom.registry.snapshot()) == [
            "s1:tool_choice", "s2:tool_choice",
        ]

    def test_domains_never_share_state(self):
        eng = _engine(_Backend())
        eng.decide("tool_choice", ["a"], {"goal": "g"})
        router = pm.get_registry()
        router.register("inst:background", "provider-quota")
        oracle = get_phase_domain(DOMAIN, period_s=0.3, max_wait_s=0.3, k=0.6)
        assert oracle.registry is not router
        assert "default:tool_choice" not in {
            o.oscillator_id for o in router.snapshot()
        }, "an Oracle oscillator leaked into the router registry"
        assert "inst:background" not in {
            o.oscillator_id for o in oracle.registry.snapshot()
        }, "a router oscillator leaked into the Oracle registry"
        other = get_phase_domain("test.other", period_s=0.3, max_wait_s=0.3, k=0.6)
        other.wait_for("x:y")
        assert {o.oscillator_id for o in other.registry.snapshot()} == {"x:y"}
        assert "x:y" not in {o.oscillator_id for o in oracle.registry.snapshot()}

    def test_one_instance_per_name(self):
        a = get_phase_domain("test.same", period_s=0.3, max_wait_s=0.3, k=0.6)
        b = get_phase_domain("test.same", period_s=9.0, max_wait_s=9.0, k=9.0)
        assert a is b and isinstance(a, PhaseDomain)

    def test_domain_does_not_read_the_router_tunables(self, monkeypatch):
        """A domain's k / tau / period / load are its OWN: changing the router's
        module tunables must not move a domain's oscillators."""
        monkeypatch.setattr(pm, "PHASE_K", 99.0)
        monkeypatch.setattr(pm, "AMP_RELAX_TAU_S", 0.0001)
        monkeypatch.setattr(pm, "DEFAULT_PERIOD_S", 77.0)
        dom = PhaseDomain("test.own", period_s=0.3, max_wait_s=0.3, k=0.6,
                          load_fn=lambda: 0.0)
        dom.wait_for("a:b")
        assert dom.registry.get("a:b").natural_period_s == pytest.approx(0.3)
        assert dom.registry._k == 0.6


# -- priority bypass ----------------------------------------------------------


class TestPriorityBypass:
    def test_background_waits_for_its_position_priority_does_not(self):
        dom = get_phase_domain(DOMAIN, period_s=0.3, max_wait_s=0.3, k=0.6)
        assert dom.wait_for("default:fresh_bg") > 0.0
        for cls in (CallClass.USER_TURN, CallClass.SPEAK):
            with call_class_scope(cls):
                assert dom.wait_for(f"default:fresh_{cls.value}") == 0.0
        # the bypass returns BEFORE registration: no oscillator was created
        ids = {o.oscillator_id for o in dom.registry.snapshot()}
        assert "default:fresh_user_turn" not in ids

    def test_non_priority_classes_are_gated(self):
        dom = get_phase_domain(DOMAIN, period_s=0.3, max_wait_s=0.3, k=0.6)
        with call_class_scope(CallClass.GRAFT):  # GRAFT is deliberately gated
            assert dom.wait_for("default:graft_consumer") > 0.0

    def test_priority_decision_registers_nothing_and_completes(self):
        eng = _engine(_Backend())
        with call_class_scope(CallClass.USER_TURN):
            t0 = time.perf_counter()
            ds = eng.decide("tool_choice", ["a", "b"], {"goal": "g"})
            elapsed = time.perf_counter() - t0
        assert ds is not None
        assert elapsed < 0.1, f"a priority-class decision waited {elapsed:.3f}s"
        dom = get_phase_domain(DOMAIN, period_s=0.3, max_wait_s=0.3, k=0.6)
        assert dom.registry.snapshot() == []


# -- REQ-2: overlap -----------------------------------------------------------


class TestOverlap:
    def test_two_decisions_are_in_flight_at_once(self):
        gate = threading.Barrier(2, timeout=5.0)
        backend = _Backend(hold=gate.wait)  # each run waits for the OTHER run
        eng = _engine(backend)
        out = {}

        def call(cid):
            out[cid] = eng.decide(cid, ["a", "b"], {"goal": "g"})

        ts = _run_threads([lambda: call("tool_choice"), lambda: call("narration")])
        for t in ts:
            t.join(10.0)
        assert out["tool_choice"] is not None and out["narration"] is not None, (
            "the runs were serialised: the second never started while the first ran"
        )
        assert backend.max_running == 2

    def test_concurrency_is_not_capped_at_the_cpu_run_capacity(self):
        """The CPU's run capacity (cores / intra-op) is a LOAD parameter that
        slows the cadence - it must never be a ceiling on runs in flight."""
        n = 6
        cap = max(1, (de.os.cpu_count() or 1) // max(1, de._oracle_intra_op or
                                                      max(1, (de.os.cpu_count() or 1) // 2)))
        assert n > cap, "test needs more runs than the capacity to mean anything"
        gate = threading.Barrier(n, timeout=10.0)
        backend = _Backend(hold=gate.wait)
        eng = _engine(backend)
        out = {}
        ts = _run_threads([
            (lambda i=i: out.__setitem__(i, eng.decide(f"c{i}", ["a", "b"], {"goal": "g"})))
            for i in range(n)
        ])
        for t in ts:
            t.join(15.0)
        assert all(out.get(i) is not None for i in range(n))
        assert backend.max_running == n

    def test_load_fraction_is_runs_in_flight_over_capacity(self, monkeypatch):
        monkeypatch.setattr(de.os, "cpu_count", lambda: 8)
        monkeypatch.setattr(de, "_oracle_intra_op", 4)
        monkeypatch.setattr(de, "_oracle_runs_in_flight", 0)
        assert de._oracle_load_fraction() == 0.0
        monkeypatch.setattr(de, "_oracle_runs_in_flight", 1)
        assert de._oracle_load_fraction() == pytest.approx(0.5)
        monkeypatch.setattr(de, "_oracle_runs_in_flight", 5)
        assert de._oracle_load_fraction() == 1.0  # clamped load, not a refusal

    def test_in_flight_counter_returns_to_zero(self):
        eng = _engine(_Backend())
        for i in range(5):
            eng.decide(f"c{i}", ["a", "b"], {"goal": "g"})
        assert de._oracle_runs_in_flight == 0

    def test_decision_counters_are_exact_under_concurrency(self):
        eng = _engine(_Backend())
        ts = _run_threads([
            (lambda i=i: eng.decide("tool_choice", ["a", "b"], {"goal": "g"}))
            for i in range(12)
        ])
        for t in ts:
            t.join(15.0)
        assert eng.counters.decisions == 12
        assert eng.counters.by_consumer["tool_choice"] == 12
        assert eng.counters.lock_timeouts == 0


# -- REQ-2: load/unload never races a run -------------------------------------


class TestLoadUnloadNeverRacesARun:
    def test_shutdown_waits_for_the_in_flight_run(self):
        release = threading.Event()
        started = threading.Event()

        def hold():
            started.set()
            release.wait(10.0)

        backend = _Backend(hold=hold)
        eng = _engine(backend)
        out = {}
        run = threading.Thread(
            target=lambda: out.update(ds=eng.decide("tool_choice", ["a", "b"], {"goal": "g"})))
        run.start()
        assert started.wait(5.0)
        stopper = threading.Thread(target=eng.shutdown)
        stopper.start()
        time.sleep(0.3)
        assert not backend.shutdown_called.is_set(), (
            "shutdown freed the backend while a run was in flight"
        )
        assert eng._backend is backend
        release.set()
        run.join(5.0)
        stopper.join(5.0)
        assert out["ds"] is not None, "the in-flight decision was lost to the unload"
        assert backend.shutdown_called.is_set()
        assert eng._backend is None

    def test_decision_during_shutdown_waits_then_reloads(self):
        release = threading.Event()
        started = threading.Event()
        calls = {"n": 0}

        def hold():
            calls["n"] += 1
            if calls["n"] == 1:
                started.set()
                release.wait(10.0)

        backend = _Backend(hold=hold)
        eng = _engine(backend)
        first = {}
        a = threading.Thread(
            target=lambda: first.update(ds=eng.decide("tool_choice", ["a"], {"goal": "g"})))
        a.start()
        assert started.wait(5.0)
        stopper = threading.Thread(target=eng.shutdown)
        stopper.start()
        time.sleep(0.2)
        second = {}
        b = threading.Thread(
            target=lambda: second.update(ds=eng.decide("narration", ["a"], {"goal": "g"})))
        b.start()
        time.sleep(0.2)
        assert "ds" not in second, "a new run entered while the unload was draining"
        release.set()
        for t in (a, stopper, b):
            t.join(10.0)
        assert first["ds"] is not None and second["ds"] is not None

    def test_lazy_load_happens_once_under_concurrent_first_use(self):
        built = {"n": 0}
        backend = _Backend()

        def factory(**kw):
            built["n"] += 1
            time.sleep(0.2)  # a slow load: the other callers arrive meanwhile
            return backend

        eng = DecisionEngine(EngineConfig(), backend_factory=factory)
        out = {}
        ts = _run_threads([
            (lambda i=i: out.__setitem__(i, eng.decide(f"c{i}", ["a", "b"], {"goal": "g"})))
            for i in range(5)
        ])
        for t in ts:
            t.join(15.0)
        assert built["n"] == 1, "the backend was loaded more than once"
        assert all(out.get(i) is not None for i in range(5)), (
            "a decision was lost while another caller loaded the model"
        )

    def test_engine_unavailable_returns_none(self):
        eng = DecisionEngine(EngineConfig(), backend_factory=lambda **kw: None)
        assert eng.decide("tool_choice", ["a"], {"goal": "g"}) is None
        assert eng._runs == 0, "a failed load leaked a run slot"


# -- fail-open and the flag ---------------------------------------------------


class TestFailOpenAndFlag:
    def test_a_gate_fault_admits_the_decision(self, monkeypatch):
        eng = _engine(_Backend())
        dom = get_phase_domain(DOMAIN, period_s=0.3, max_wait_s=0.3, k=0.6)
        monkeypatch.setattr(
            dom.registry, "advance_all",
            lambda q: (_ for _ in ()).throw(RuntimeError("boom")))
        assert dom.wait_for("default:x") == 0.0
        assert eng.decide("tool_choice", ["a", "b"], {"goal": "g"}) is not None

    def test_a_load_fault_reads_as_no_load(self):
        dom = PhaseDomain("test.load", period_s=0.3, max_wait_s=0.3, k=0.6,
                          load_fn=lambda: 1 / 0)
        assert dom.registry._load_fraction("test.load") == 0.0

    def test_flag_off_uses_the_classical_lock(self, monkeypatch):
        monkeypatch.delenv("IRIS_ORACLE_PHASE", raising=False)
        eng = _engine(_Backend())
        assert eng.decide("tool_choice", ["a", "b"], {"goal": "g"}) is not None
        assert phase_domain_mod._domains == {}, (
            "the phase domain was spawned with the flag off"
        )

    def test_flag_off_still_times_out_on_a_held_lock(self, monkeypatch):
        monkeypatch.delenv("IRIS_ORACLE_PHASE", raising=False)
        eng = DecisionEngine(EngineConfig(acquire_timeout_s=0.05),
                             backend_factory=lambda **kw: _Backend())
        eng._backend = _Backend()
        eng._load_attempted = True
        with eng._lock:
            assert eng.decide("tool_choice", ["a"], {"goal": "g"}) is None
        assert eng.counters.lock_timeouts == 1


# -- CT-3 / CT-4 import discipline for the new module -------------------------

_ALLOWED = {
    "__future__", "math", "time", "typing", "threading", "asyncio", "logging",
    "backend.agent.phase_manager", "backend.agent.trig_coupling",
    "backend.agent.call_context",
}


class TestPhaseDomainImportDiscipline:
    def _imports(self):
        src = Path(phase_domain_mod.__file__).read_text(encoding="utf-8")
        mods = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                mods.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module)
        return mods

    def test_only_scheduler_safe_imports(self):
        extra = self._imports() - _ALLOWED
        assert not extra, f"phase_domain imports outside the CT-3/CT-4 set: {extra}"

    def test_never_touches_cognitive_state(self):
        src = Path(phase_domain_mod.__file__).read_text(encoding="utf-8")
        code = "\n".join(
            ln for ln in src.splitlines() if not ln.strip().startswith("#"))
        for forbidden in ("coupled_registry", "iris_ffi", "ffi_caducean"):
            # the docstring names them; code must not import or call them
            assert f"import {forbidden}" not in code
            assert f"{forbidden}(" not in code
        assert "coupled_registry" not in self._imports()
        assert not any("iris_ffi" in m for m in self._imports())

    def test_is_not_a_budget(self):
        """No semaphore / counter-cap vocabulary in the gate (NOT THIS)."""
        src = Path(phase_domain_mod.__file__).read_text(encoding="utf-8")
        for word in ("Semaphore", "BoundedSemaphore", "max_concurrent", "max_in_flight"):
            assert word not in src
