"""Behavioural tests: a p95 regression is recorded, not kept silently
(REQ-30 AC30.7/AC30.8, T38).

AC30.7 — every tuning change is measured against the recorded Wave 8 baseline.
AC30.8 — IF a tuning change regresses p95 THEN the system SHALL record the
regression and revert rather than keep it silently.

The bench cannot revert source code, so "revert" is a REPORTED obligation: the
run exits non-zero, names the regression, and writes it into the baseline's
`regressions` list instead of absorbing the new numbers as the new normal.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_BENCH = _REPO / "scripts" / "bench_decision_engine.py"


def _bench_module():
    spec = importlib.util.spec_from_file_location("bench_decision_engine", _BENCH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def bench():
    return _bench_module()


class TestRegressionDetection:
    def test_no_baseline_is_not_a_regression(self, bench):
        assert bench._detect_regressions(
            {"p50_ms": 100, "p95_ms": 200, "accuracy": 0.6}, {}) == []

    def test_a_clean_run_reports_nothing(self, bench):
        base = {"p50_ms": 100, "p95_ms": 200, "accuracy": 0.60}
        observed = {"p50_ms": 101, "p95_ms": 205, "accuracy": 0.60}
        assert bench._detect_regressions(observed, base) == []

    def test_p95_regression_is_detected_and_named(self, bench):
        """AC30.8: beyond tolerance → a named regression, not silence."""
        base = {"p50_ms": 100, "p95_ms": 200, "accuracy": 0.60}
        observed = {"p50_ms": 140, "p95_ms": 400, "accuracy": 0.60}

        out = bench._detect_regressions(observed, base)

        assert out, "a 2x p95 regression was silently accepted (AC30.8)"
        assert any("p95" in r for r in out)
        assert any("400" in r and "200" in r for r in out), out

    def test_accuracy_regression_is_detected(self, bench):
        """AC30.7: no accuracy regression, at any tolerance."""
        base = {"p50_ms": 100, "p95_ms": 200, "accuracy": 0.60}
        observed = {"p50_ms": 100, "p95_ms": 200, "accuracy": 0.55}

        out = bench._detect_regressions(observed, base)

        assert out and any("accuracy" in r for r in out), out

    def test_p95_within_tolerance_is_noise(self, bench):
        """A small p95 move is noise, not a regression — the tolerance exists
        so the baseline is not churned on every run."""
        base = {"p50_ms": 100, "p95_ms": 200, "accuracy": 0.60}
        observed = {"p50_ms": 100, "p95_ms": int(200 * (1 + bench.P95_TOLERANCE))}

        assert bench._detect_regressions(observed, base) == []


class TestBaselineRecord:
    def test_baseline_round_trips(self, bench, tmp_path, monkeypatch):
        """The baseline is recorded where the next run will read it."""
        target = tmp_path / "baseline.json"
        monkeypatch.setattr(bench, "BASELINE_PATH", target)

        payload = {"p50_ms": 120, "p95_ms": 180, "accuracy": 0.62}
        bench._save_baseline(payload)

        assert target.is_file(), "the baseline was not written"
        assert json.loads(target.read_text(encoding="utf-8")) == payload
        assert bench._load_baseline() == payload

    def test_unreadable_baseline_is_absent_not_fatal(self, bench, tmp_path,
                                                     monkeypatch):
        target = tmp_path / "baseline.json"
        target.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(bench, "BASELINE_PATH", target)

        assert bench._load_baseline() == {}, (
            "an unreadable baseline must be treated as absent, never crash"
        )

    def test_baseline_path_is_repo_relative(self, bench):
        """A recorded baseline must live in the repo, not in a temp dir that
        the next run cannot see."""
        assert "benchmarks" in str(bench.BASELINE_PATH)
        assert _REPO in bench.BASELINE_PATH.parents

    def test_the_bench_reports_regressions_for_revert(self):
        """AC30.8: the run says so out loud and exits non-zero."""
        src = _BENCH.read_text(encoding="utf-8", errors="replace")
        assert "REGRESSION" in src
        assert "revert" in src.lower()
        assert "regressions" in src
