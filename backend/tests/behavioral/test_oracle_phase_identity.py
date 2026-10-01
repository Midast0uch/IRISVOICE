"""REQ-3 (QUALITY): an Oracle decision is IDENTICAL alone and while others run.

Spec: specs/oracle-phase-concurrency. The calibrated thresholds were measured on
solo runs, one question per session run. The phase path overlaps runs on the one
loaded onnxruntime session, so this drives the REAL model over the calibration
inputs (the 60 labelled cases in scripts/fixtures/decision_engine_cases.json as
tool_choice menus, plus the monitor / review / narration consumers and one long
input - the same deterministic workload as benchmarks/oracle_phase_bench.py) and
asserts every probability distribution is BITWISE equal (names, logits and
probabilities as floats) across three conditions:

  1. alone, lock path (flag off)          - the committed behaviour = reference
  2. alone, phase path (flag on)          - the phase path itself changes nothing
  3. under load, phase path               - 8 threads + a noise thread running
                                            the long input, so several runs are
                                            really in flight (asserted via the
                                            peak in-flight run count)

NO tolerance: if a distribution differs, this test fails and the measured
difference is the finding - never widen it here.

Skipped only when the ONNX model directory is absent (no model, nothing to
measure).
"""

from __future__ import annotations

import importlib.util
import threading
from pathlib import Path

import pytest

from backend.agent import decision_engine as de
from backend.agent.decision_backend_onnx import resolve_model_dir
from backend.agent.phase_domain import reset_phase_domains_for_testing

_BENCH = Path(__file__).resolve().parents[3] / "benchmarks" / "oracle_phase_bench.py"

pytestmark = pytest.mark.skipif(
    resolve_model_dir(None) is None, reason="ONNX decision model not installed")


def _bench():
    spec = importlib.util.spec_from_file_location("oracle_phase_bench", _BENCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _dist(ds):
    return None if ds is None else [[c.name, c.logprob, c.prob] for c in ds.distribution]


@pytest.fixture(scope="module")
def world():
    bench = _bench()
    bench._register_consumers()
    items = bench.build_workload()
    eng = de.DecisionEngine(de.load_engine_config())
    assert eng._load(), "model dir resolved but the model did not load"
    yield eng, items
    eng.shutdown()


def _alone(eng, items):
    return [_dist(eng.decide(it["consumer"], it["options"], {"goal": it["goal"]}))
            for it in items]


def test_distributions_identical_alone_lock_alone_phase_and_under_load(world, monkeypatch):
    eng, items = world

    monkeypatch.delenv("IRIS_ORACLE_PHASE", raising=False)
    reference = _alone(eng, items)  # 1. lock path, alone
    assert all(r is not None for r in reference), "an alone decision returned None"

    monkeypatch.setenv("IRIS_ORACLE_PHASE", "1")
    reset_phase_domains_for_testing()
    phase_alone = _alone(eng, items)  # 2. phase path, alone
    assert phase_alone == reference, "the phase path changed a distribution (alone)"

    # 3. under load: every item issued from 8 threads, two rounds, while a noise
    #    thread keeps the long input running.
    results = {}
    peak = {"n": 0}
    lock = threading.Lock()
    stop = threading.Event()
    long_item = next(it for it in items if it["long"])

    def noise():
        while not stop.is_set():
            eng.decide(long_item["consumer"], long_item["options"],
                       {"goal": long_item["goal"]})

    def sampler():
        while not stop.is_set():
            with de._ORACLE_RUNS_LOCK:
                peak["n"] = max(peak["n"], de._oracle_runs_in_flight)
            stop.wait(0.005)

    def worker(idxs):
        for rnd in range(2):
            for i in idxs:
                it = items[i]
                d = _dist(eng.decide(it["consumer"], it["options"], {"goal": it["goal"]}))
                with lock:
                    results.setdefault(i, []).append(d)

    helpers = [threading.Thread(target=noise), threading.Thread(target=sampler)]
    for h in helpers:
        h.start()
    shares = [list(range(k, len(items), 8)) for k in range(8)]
    ts = [threading.Thread(target=worker, args=(s,)) for s in shares]
    for t in ts:
        t.start()
    for t in ts:
        t.join(300)
    stop.set()
    for h in helpers:
        h.join(60)

    assert peak["n"] >= 2, "no two runs were ever in flight - the load was not concurrent"
    bad = []
    for i, ref in enumerate(reference):
        got = results.get(i, [])
        assert len(got) == 2, f"item {i} ({items[i]['consumer']}) lost a decision under load"
        for g in got:
            if g != ref:
                bad.append((i, items[i]["consumer"]))
    assert not bad, (
        f"{len(bad)} distribution(s) differ under load (peak in flight "
        f"{peak['n']}): {bad[:10]}"
    )
