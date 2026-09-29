"""Behavioral test: the ONNX backend on the 60-case battery (BT-DEI-13).

AC1.3 (carried by REQ-21/T28)  CPU scoring sub-180ms.
AC22.3                         flat only, no tree.

Runs the REAL ONNX backend over the labeled battery — slow (~10 s incl.
session init), which is the point: the parity numbers must be measured, not
assumed. Incumbent baseline: 60.0% / 70.8% / 1172 ms — a regression fails.
"""

from __future__ import annotations

import ast
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.bench_decision_models import (  # noqa: E402
    build_menu,
    load_cases,
    run_gliner_onnx,
)


class TestCpuScoringSub180ms:
    @pytest.fixture(scope="class")
    def battery(self):
        cases = load_cases()
        rows = run_gliner_onnx(cases, None, "model_int8.onnx")
        return rows

    def test_cpu_scoring_sub_180ms(self, battery):
        """BT-DEI-13 / AC1.3: ONNX backend >=70% accuracy, >=99% above the
        0.40 threshold, p50 <=180ms on the 60-case battery. Incumbent:
        60.0% / 70.8% / 1172ms — a regression fails."""
        assert battery, "no rows — the backend never scored"
        n = len(battery)
        correct = sum(1 for r in battery if r["correct"])
        acc = correct / n
        above = [r for r in battery if r["conf"] >= 0.40]
        acc_above = (
            sum(1 for r in above if r["correct"]) / len(above) if above else 0.0
        )
        lats = sorted(r["ms"] for r in battery)
        p50 = lats[min(len(lats) - 1, int(0.50 * len(lats)))]
        assert acc >= 0.70, f"accuracy {acc:.1%} < 70% (incumbent 60.0%)"
        assert acc_above >= 0.99, (
            f"accuracy above 0.40 {acc_above:.1%} < 99% (incumbent 70.8%)"
        )
        assert p50 <= 180, f"p50 {p50:.0f}ms > 180ms (incumbent 1172ms)"


class TestFlatOnlyNoTree:
    def test_flat_only_no_tree(self):
        """AC22.3: flat single-pass scoring is the ONLY path — no tree, no
        lane grouping anywhere in the production path or the bench."""
        for rel in ("backend/agent/decision_engine.py",
                    "backend/agent/tool_decision.py",
                    "scripts/bench_decision_models.py",
                    "scripts/run_engine_calibration.py"):
            src = Path(rel).read_text(encoding="utf-8")
            assert "decide_tree" not in src or src.count("decide_tree") == src.count(
                "# feed decide_tree"
            ), f"{rel} still routes through a tree"
        # The bench has no tree mode left.
        bench = Path("scripts/bench_decision_models.py").read_text(
            encoding="utf-8"
        )
        assert '"tree"' not in bench, "the bench still has a tree mode"
        assert "build_lanes" not in bench, "the bench still builds lanes"
