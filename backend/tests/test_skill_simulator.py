"""
Tests for SkillSimulator.
Run: python -m pytest backend/tests/test_skill_simulator.py -v
"""
import time

import numpy as np
import pytest

from backend.agent.skill_simulator import SkillSimulator, _extract_features


class TestSkillSimulator:
    # ── Fallback ────────────────────────────────────────────────────────

    def test_untrained_returns_half(self):
        sim = SkillSimulator()
        assert sim.predict("any variant", "any original") == pytest.approx(0.5)

    def test_untrained_is_trained_false(self):
        sim = SkillSimulator()
        assert sim.is_trained is False

    # ── Feature extraction ──────────────────────────────────────────────

    def test_extract_features_shape(self):
        f = _extract_features("This variant will search for patterns", "original", None)
        assert f.shape == (6,)
        assert f.dtype == np.float64

    def test_short_variant_scores_lower(self):
        f_short = _extract_features("x", "original", None)
        f_long = _extract_features("This variant will search for patterns using advanced methods", "original", None)
        assert f_short[0] < f_long[0]  # length score

    def test_novel_words_score_higher(self):
        f_dup = _extract_features("original original", "original", None)
        f_new = _extract_features("brand new creative variant here", "original", None)
        assert f_dup[3] < f_new[3]  # novel word ratio

    # ── Training ──────────────────────────────────────────────────────────

    def test_fit_from_reports_insufficient(self):
        sim = SkillSimulator()
        reports = [{"variant": "v", "original": "o", "improved": True}] * 5
        assert sim.fit_from_reports(reports) is False
        assert sim.is_trained is False

    def test_fit_from_reports_sufficient(self):
        sim = SkillSimulator()
        reports = [
            {"variant": "will search for solutions using advanced methods", "original": "find stuff", "improved": True, "caducean_state": {"eml": 1.5, "x": 0.6, "y": 0.4}},
            {"variant": "can run complex analysis pipelines", "original": "analyze data", "improved": True, "caducean_state": {"eml": 1.5, "x": 0.6, "y": 0.4}},
            {"variant": "use new techniques for discovery", "original": "find things", "improved": True, "caducean_state": {"eml": 1.5, "x": 0.6, "y": 0.4}},
            {"variant": "help users by providing answers", "original": "assist users", "improved": True, "caducean_state": {"eml": 1.5, "x": 0.6, "y": 0.4}},
            {"variant": "perform comprehensive system scans", "original": "scan system", "improved": True, "caducean_state": {"eml": 1.5, "x": 0.6, "y": 0.4}},
            {"variant": "a", "original": "find stuff", "improved": False, "caducean_state": {"eml": 0.8, "x": 0.3, "y": 0.7}},
            {"variant": "b", "original": "analyze data", "improved": False, "caducean_state": {"eml": 0.8, "x": 0.3, "y": 0.7}},
            {"variant": "c", "original": "find things", "improved": False, "caducean_state": {"eml": 0.8, "x": 0.3, "y": 0.7}},
            {"variant": "d", "original": "assist users", "improved": False, "caducean_state": {"eml": 0.8, "x": 0.3, "y": 0.7}},
            {"variant": "e", "original": "scan system", "improved": False, "caducean_state": {"eml": 0.8, "x": 0.3, "y": 0.7}},
        ]
        assert sim.fit_from_reports(reports) is True
        assert sim.is_trained is True

    def test_predict_output_bounded(self):
        sim = SkillSimulator()
        reports = [
            {"variant": "will search for solutions using advanced methods and find patterns", "original": "find stuff", "improved": True, "caducean_state": {"eml": 1.5, "x": 0.6, "y": 0.4}},
            {"variant": "a", "original": "find stuff", "improved": False, "caducean_state": {"eml": 0.8, "x": 0.3, "y": 0.7}},
        ] * 5
        sim.fit_from_reports(reports)
        p = sim.predict("any variant", "any original")
        assert 0.0 <= p <= 1.0

    def test_trained_predicts_good_higher_than_bad(self):
        sim = SkillSimulator()
        reports = [
            {"variant": "will search for solutions using advanced methods and find patterns", "original": "find stuff", "improved": True, "caducean_state": {"eml": 1.5, "x": 0.6, "y": 0.4}},
            {"variant": "a", "original": "find stuff", "improved": False, "caducean_state": {"eml": 0.8, "x": 0.3, "y": 0.7}},
        ] * 5
        sim.fit_from_reports(reports)
        p_good = sim.predict("will search for solutions using advanced methods", "find stuff", {"eml": 1.5, "x": 0.6, "y": 0.4})
        p_bad = sim.predict("a", "find stuff", {"eml": 0.8, "x": 0.3, "y": 0.7})
        assert p_good > p_bad

    # ── Performance ───────────────────────────────────────────────────────

    def test_predict_speed(self):
        sim = SkillSimulator()
        reports = [{"variant": "v", "original": "o", "improved": i % 2 == 0, "caducean_state": {"eml": 1.0, "x": 0.5, "y": 0.5}} for i in range(10)]
        sim.fit_from_reports(reports)
        t0 = time.perf_counter()
        for _ in range(1000):
            sim.predict("variant text here", "original text")
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.020  # 20ms for 1000 calls (feature extraction included)

    # ── Batch ─────────────────────────────────────────────────────────────

    def test_score_variants_returns_list(self):
        sim = SkillSimulator()
        sim.fit_from_reports([{"variant": "v", "original": "o", "improved": True, "caducean_state": {"eml": 1.0, "x": 0.5, "y": 0.5}}] * 10)
        scores = sim.score_variants(["a", "b", "c"], "o")
        assert len(scores) == 3
        assert all(isinstance(s, float) for s in scores)
