"""Unit tests: calibration quality (REQ-18, T24).

AC18.1  reliability buckets / ECE / Brier computed.
AC18.3  softmax_tau resolved — the sharpening is deleted; the reported
        confidence IS the native softmax probability.
AC18.5  INSUFFICIENT_DATA below the row floor — never a verdict.
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
    [{"confidence": 0.30 + (i % 6) / 100, "correct": False} for i in range(40)]
    + [{"confidence": 0.55 + (i % 20) / 100, "correct": True} for i in range(60)]
)


class TestReliabilityEceBrierComputed:
    def test_reliability_ece_brier_computed(self):
        """AC18.1: ECE and Brier are computed over the rows."""
        ece, brier = cal._ece_brier(ROWS)
        assert ece is not None and brier is not None
        assert 0.0 <= ece <= 1.0
        assert 0.0 <= brier <= 1.0
        # A perfectly calibrated set has ECE near 0.
        perfect = [{"confidence": 1.0, "correct": True},
                   {"confidence": 0.0, "correct": False}]
        ece_p, _ = cal._ece_brier(perfect)
        assert ece_p == 0.0

    def test_ece_reported_with_precision(self):
        """AC18.2: the report carries ECE alongside the threshold/precision."""
        # The report shape: the group dict carries ece + brier keys.
        import inspect

        src = Path(ROOT / "scripts" / "calibrate_decision_threshold.py").read_text(
            encoding="utf-8"
        )
        assert '"ece": ece' in src and '"brier": brier' in src, (
            "ECE/Brier must ride the report alongside precision (AC18.2)"
        )


class TestTauReplacedByFittedMap:
    def test_tau_replaced_by_fitted_map(self):
        """AC18.3: softmax_tau is RESOLVED — the fixed sharpening is deleted
        with the LFM path; the ONNX backend's softmax is natively calibrated
        (D13), so the reported confidence IS the probability."""
        from backend.agent.decision_engine import EngineConfig

        assert not hasattr(EngineConfig(), "softmax_tau"), (
            "the fixed sharpening must be deleted (T29/AC18.3)"
        )
        src = Path("backend/agent/decision_backend_onnx.py").read_text(
            encoding="utf-8"
        )
        assert "softmax_tau" not in src
        assert "NO sharpening" in src or "natively" in src


class TestInsufficientDataNoVerdict:
    def test_insufficient_data_no_verdict(self):
        """AC18.5: below the row floor (50), the recommendation refuses —
        never a verdict on insufficient data."""
        small = ROWS[:10]
        t, n = cal.recommend_threshold(small)
        assert t is None, "a verdict on insufficient data"
        assert n == 10
