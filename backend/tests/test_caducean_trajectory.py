"""
Tests for CaduceanTrajectoryRecorder.
Run: python -m pytest backend/tests/test_caducean_trajectory.py -v
"""
import sqlite3
import threading
import time

import pytest

from backend.agent.caducean_trajectory import (
    CaduceanTrajectoryRecorder,
    get_trajectory_recorder,
)


@pytest.fixture
def recorder():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    rec = CaduceanTrajectoryRecorder(conn)
    yield rec
    conn.close()


class TestCaduceanTrajectoryRecorder:
    # ── Schema ────────────────────────────────────────────────────────────

    def test_table_created_on_first_record(self, recorder):
        count = recorder.trajectory_count()
        assert count == 0

    def test_record_writes_correct_fields(self, recorder):
        recorder.record(
            session_id="sess_1",
            step_num=3,
            x=0.5,
            y=0.2,
            action=1,
            outcome="success",
            eml_after=1.25,
        )
        rows = recorder.get_trajectories()
        assert len(rows) == 1
        assert rows[0]["session_id"] == "sess_1"
        assert rows[0]["step_num"] == 3
        assert rows[0]["x"] == pytest.approx(0.5)
        assert rows[0]["y"] == pytest.approx(0.2)
        assert rows[0]["action"] == 1
        assert rows[0]["outcome"] == "success"
        assert rows[0]["eml_after"] == pytest.approx(1.25)
        assert "ts" in rows[0]

    def test_trajectory_count(self, recorder):
        assert recorder.trajectory_count() == 0
        recorder.record("s", 0, 0, 0, 0, "ok", 1.0)
        assert recorder.trajectory_count() == 1
        recorder.record("s", 1, 0, 0, 0, "ok", 1.0)
        assert recorder.trajectory_count() == 2

    def test_get_trajectories_in_insertion_order(self, recorder):
        recorder.record("s", 0, 0, 0, 0, "a", 1.0)
        recorder.record("s", 1, 0, 0, 0, "b", 2.0)
        recorder.record("s", 2, 0, 0, 0, "c", 3.0)
        rows = recorder.get_trajectories()
        assert [r["outcome"] for r in rows] == ["a", "b", "c"]

    def test_eml_cache_updated(self, recorder):
        CaduceanTrajectoryRecorder._eml_cache = 1.0  # reset before assert
        assert CaduceanTrajectoryRecorder.get_cached_eml() == pytest.approx(1.0)
        recorder.record("s", 0, 0, 0, 0, "ok", 2.34)
        assert CaduceanTrajectoryRecorder.get_cached_eml() == pytest.approx(2.34)

    # ── Filtering ─────────────────────────────────────────────────────────

    def test_get_trajectories_filter_by_session(self, recorder):
        recorder.record("sess_a", 0, 0, 0, 0, "x", 1.0)
        recorder.record("sess_b", 0, 0, 0, 0, "y", 1.0)
        rows_a = recorder.get_trajectories(session_id="sess_a")
        assert len(rows_a) == 1
        assert rows_a[0]["outcome"] == "x"

    def test_get_trajectories_missing_session(self, recorder):
        recorder.record("sess_a", 0, 0, 0, 0, "x", 1.0)
        rows = recorder.get_trajectories(session_id="nonexistent")
        assert rows == []

    # ── Robustness ────────────────────────────────────────────────────────

    def test_graceful_no_crash_on_double_record(self, recorder):
        recorder.record("s", 0, 0, 0, 0, "ok", 1.0)
        recorder.record("s", 0, 0, 0, 0, "ok", 1.0)  # should not raise
        assert recorder.trajectory_count() == 2

    def test_concurrent_writes(self, recorder):
        def worker(i):
            recorder.record(f"s", i, i * 0.1, i * 0.1, 0, "ok", i * 0.1)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert recorder.trajectory_count() == 20

    # ── get_trajectory_recorder singleton ─────────────────────────────────

    def test_singleton_same_instance(self, recorder):
        """get_trajectory_recorder returns cached instance for same MI."""
        class FakeMI:
            pass

        fake = FakeMI()
        fake.episodic = type("E", (), {"db": recorder._conn})()
        r1 = get_trajectory_recorder(fake)
        r2 = get_trajectory_recorder(fake)
        assert r1 is r2

    def test_singleton_different_instances(self, recorder):
        class FakeMI:
            pass

        fake1 = FakeMI()
        fake1.episodic = type("E", (), {"db": recorder._conn})()
        fake2 = FakeMI()
        fake2.episodic = type("E", (), {"db": sqlite3.connect(":memory:", check_same_thread=False)})()
        r1 = get_trajectory_recorder(fake1)
        r2 = get_trajectory_recorder(fake2)
        assert r1 is not r2
