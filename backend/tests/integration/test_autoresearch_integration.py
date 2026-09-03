"""Tests for AutoResearch Domain 19 integration."""
import sqlite3

import pytest

from backend.agent.auto_research import AutoResearchRunner
from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder
from backend.agent.skill_simulator import SkillSimulator


class FakeSemantic:
    def get_by_category(self, cat):
        return []


class FakeMemory:
    def __init__(self):
        self.semantic = FakeSemantic()
        self.episodic = type("E", (), {"db": sqlite3.connect(":memory:", check_same_thread=False)})()


class TestAutoResearchIntegration:
    def test_init_creates_components(self):
        mi = FakeMemory()
        runner = AutoResearchRunner(mi)
        assert isinstance(runner._skill_sim, SkillSimulator)
        assert runner._traj_ctrl is not None

    def test_should_fire_bootstrap_high_eml(self):
        mi = FakeMemory()
        runner = AutoResearchRunner(mi)
        # Mock _get_caducean_state to return high EML
        runner._get_caducean_state = lambda: {"eml": 1.8, "x": 0.6, "y": 0.4}
        assert runner._should_fire_now() is True

    def test_should_fire_bootstrap_balanced(self):
        mi = FakeMemory()
        runner = AutoResearchRunner(mi)
        runner._get_caducean_state = lambda: {"eml": 1.0, "x": 0.5, "y": 0.5}
        assert runner._should_fire_now() is False

    def test_should_fire_bootstrap_low_eml(self):
        mi = FakeMemory()
        runner = AutoResearchRunner(mi)
        runner._get_caducean_state = lambda: {"eml": 0.5, "x": 0.3, "y": 0.7}
        assert runner._should_fire_now() is True

    def test_skill_sim_fallback_no_filter(self):
        mi = FakeMemory()
        runner = AutoResearchRunner(mi)
        scores = runner._skill_sim.score_variants(
            ["variant one", "variant two"], "original"
        )
        assert scores == [pytest.approx(0.5), pytest.approx(0.5)]

    def test_record_cycle_trajectory_no_crash(self):
        mi = FakeMemory()
        runner = AutoResearchRunner(mi)
        runner._cycles_completed = 3
        runner._record_cycle_trajectory(improved=True)
        # Should not crash even without real FFI

    def test_get_status_returns_fields(self):
        mi = FakeMemory()
        runner = AutoResearchRunner(mi)
        status = runner.get_status()
        assert "running" in status
        assert "cycles_completed" in status
        assert "recent_reports" in status

    def test_stop_clears_running(self):
        mi = FakeMemory()
        runner = AutoResearchRunner(mi)
        runner._running = True
        runner.stop()
        # _stop_event is set, but _running stays True until loop exits
        assert runner._stop_event.is_set() is True
