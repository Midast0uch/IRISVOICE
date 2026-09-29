"""Behavioral test: the calibration curve is reported (REQ-22 AC22.2, BT-DEI-14).

The operating point is re-derivable from
scripts/calibrate_decision_threshold.py's coverage/accuracy-above-threshold
curve rather than hard-coded (D13).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "calibrate_decision_threshold",
    ROOT / "scripts" / "calibrate_decision_threshold.py",
)
cal = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("calibrate_decision_threshold", cal)
_spec.loader.exec_module(cal)


ROWS = (
    # 40 rows at conf ~0.30-0.35, all wrong (the GLiNER error band)
    [{"confidence": 0.30 + (i % 6) / 100, "correct": False} for i in range(40)]
    # 23 rows at conf >= 0.40, all correct (the measured curve)
    + [{"confidence": 0.40 + (i % 12) / 100, "correct": True} for i in range(23)]
    # 37 rows at conf >= 0.40, all correct
    + [{"confidence": 0.55 + (i % 20) / 100, "correct": True} for i in range(37)]
)


class TestCoverageAccuracyCurveReported:
    def test_coverage_accuracy_curve_reported(self):
        """AC22.2 / BT-DEI-14: the curve reports coverage AND
        accuracy-above-threshold per candidate threshold, so the operating
        point is re-derivable. At 0.40 the curve must show 100% accuracy
        above threshold (the measured GLiNER result)."""
        curve = cal.coverage_accuracy_curve(ROWS)
        assert curve, "no curve produced"
        by_t = {pt["threshold"]: pt for pt in curve}
        t040 = by_t.get(0.4)
        assert t040 is not None, "the curve must include t=0.40"
        assert t040["accuracy_above"] == 1.0, (
            f"accuracy above 0.40 must be 1.0, got {t040['accuracy_above']}"
        )
        assert t040["coverage"] > 0, "coverage at 0.40 must be positive"
        assert t040["n_above"] == len(
            [r for r in ROWS if r["confidence"] >= 0.40]
        )
        # Every point carries the three fields.
        for pt in curve:
            assert set(pt) == {"threshold", "coverage", "accuracy_above", "n_above"}

    def test_curve_rederives_the_operating_point(self):
        """D13: the operating point is re-derivable — the highest coverage
        threshold with 100% accuracy above it, from the curve alone."""
        curve = cal.coverage_accuracy_curve(ROWS)
        best = None
        for pt in curve:
            if pt["accuracy_above"] == 1.0 and pt["n_above"] >= 5:
                if best is None or pt["threshold"] < best:
                    best = pt["threshold"]
        assert best == 0.4, f"re-derived operating point {best} != 0.40"


# ── REQ-9 AC9.2 (T12): per-class accuracy for the web intent classes ────────

WEB_CASES = (
    ROOT / "scripts" / "fixtures" / "decision_engine_web_intent_cases.json"
)


class TestPerClassAccuracyReport:
    def test_per_class_accuracy_report(self):
        """AC9.2: the report separates the two WEB intent classes instead of
        pooling them — a classifier good at one and blind to the other is
        invisible in a single accuracy number."""
        rows = (
            # instant-lookup class: 3 of 4 right
            [{"chosen": "search", "correct": True}] * 3
            + [{"chosen": "search", "correct": False}]
            # research class: 1 of 2 right
            + [{"chosen": "crawler_query", "correct": True}]
            + [{"chosen": "crawler_query", "correct": False}]
            # non-web rows are reported but not judged
            + [{"chosen": "read_file", "correct": True}] * 5
        )
        rep = cal.per_class_accuracy(rows)

        assert set(rep) == {"instant_lookup", "research", "other"}, rep
        assert rep["instant_lookup"] == {"n": 4, "accuracy": 0.75}
        assert rep["research"] == {"n": 2, "accuracy": 0.5}
        assert rep["other"] == {"n": 5, "accuracy": 1.0}

        # the classifier is the documented mapping, not a guess
        assert cal.intent_class({"chosen": "search"}) == "instant_lookup"
        assert cal.intent_class({"chosen": "crawler_query"}) == "research"
        assert cal.intent_class({"chosen": "speak"}) == "other"
        assert cal.intent_class({}) == "other"

    def test_battery_contains_both_intent_classes(self):
        """AC9.2: the battery actually CONTAINS both classes — before T12 it
        contained neither (the offline battery excludes internet-gated tools),
        so a per-class report had nothing to report on."""
        import json

        cases = json.loads(WEB_CASES.read_text(encoding="utf-8"))["cases"]
        classes = {cal.intent_class({"chosen": c["expect"]}) for c in cases}
        assert "instant_lookup" in classes, "no instant-lookup cases in the battery"
        assert "research" in classes, "no research-class cases in the battery"

        # Both classes are scored against the SAME menu — otherwise the two
        # classes differ by more than intent and the comparison is meaningless.
        menus = {tuple(c["menu"]) for c in cases}
        assert len(menus) == 1, f"the classes use different menus: {menus}"
        menu = next(iter(menus))
        assert "search" in menu and "crawler_query" in menu



# ── REQ-31 AC31.1/AC31.2 (T50): reported AT the deployed configuration ─────


class TestDeployedConfigReported:
    def _cfg(self, cap=6, backend_id="gliner25-decide-onnx-int8"):
        """The DEPLOYED configuration — parsed from agent_config.yaml, not a
        code default, because `backend_thresholds` is what the threshold is
        keyed by (AC25.8/AC31.1)."""
        from backend.agent.decision_engine import load_engine_config

        cfg = load_engine_config()
        cfg.candidate_cap = cap
        cfg.backend_id = backend_id
        return cfg

    def test_curve_at_deployed_config(self):
        """AC31.1: the operating point is CONFIRMED against the deployed
        backend, cap and variant — a match is a confirmation, not silence."""
        rep = cal.deployed_config_report(self._cfg())

        assert rep["candidate_cap"] == 6
        assert rep["calibrated_cap"] == 6
        assert rep["backend_id"] == "gliner25-decide-onnx-int8"
        assert rep["threshold"] == 0.40, (
            "the deployed tool_choice threshold is not the calibrated 0.40"
        )
        assert rep["stale"] is False
        assert rep["confirms"] is True, (
            "an unchanged configuration must be reported as CONFIRMED"
        )

    def test_a_moved_cap_is_reported_stale_not_confirmed(self):
        """AC31.1/AC31.4: a moved cap is STALE, and enforcement follows."""
        rep = cal.deployed_config_report(self._cfg(cap=10))

        assert rep["stale"] is True
        assert rep["confirms"] is False
        assert rep["threshold"] is None, (
            "a stale configuration still handed out a threshold"
        )

    def test_ece_brier_at_deployed_config(self):
        """AC31.2: ECE and Brier are reported ALONGSIDE precision, at the
        deployed configuration."""
        rep = cal.calibration_report(list(ROWS), self._cfg())

        assert rep["threshold"] == 0.40
        assert rep["precision"] is not None, "no precision was reported"
        assert rep["ece"] is not None, "no ECE was reported (AC18.1/AC31.2)"
        assert rep["brier"] is not None, "no Brier score was reported"
        assert 0.0 <= rep["ece"] <= 1.0
        assert rep["verdict"] == "MEASURED"
        assert rep["deployed"]["confirms"] is True

    def test_below_the_row_floor_is_insufficient_data(self):
        """AC18.5/AC31.1 edge: never a verdict from too few rows."""
        rep = cal.calibration_report(list(ROWS)[:5], self._cfg())
        assert rep["verdict"] == "INSUFFICIENT_DATA"
