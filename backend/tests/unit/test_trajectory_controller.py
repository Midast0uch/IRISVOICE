"""Tests for TrajectoryController."""
import sqlite3
import time

import numpy as np
import pytest

from backend.agent.trajectory_controller import TrajectoryController, _MIN_FOR_FIT


def _make_conn():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(
        "CREATE TABLE caducean_trajectories (id INTEGER PRIMARY KEY, ts REAL, "
        "session_id TEXT, step_num INTEGER, x REAL, y REAL, xi REAL, u REAL, "
        "action INTEGER, outcome TEXT, eml_after REAL)"
    )
    return conn


def _insert(conn, eml, action=0, session="s"):
    conn.execute(
        "INSERT INTO caducean_trajectories "
        "(ts, session_id, step_num, x, y, xi, u, action, outcome, eml_after) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (time.time(), session, 0, 0.5, 0.5, 0.0, 0.0, action, "ok", eml),
    )
    conn.commit()


class TestTrajectoryController:
    def test_bootstrap_eml_balanced(self):
        ctrl = TrajectoryController(_make_conn())
        should, cat, conf = ctrl.should_fire(0, 0, 0, 0, 1.0, 0)
        assert should is False
        assert cat is None
        assert conf == pytest.approx(0.5)

    def test_bootstrap_eml_high(self):
        ctrl = TrajectoryController(_make_conn())
        should, cat, conf = ctrl.should_fire(0, 0, 0, 0, 1.8, 0)
        assert should is True
        assert cat is None

    def test_bootstrap_eml_low(self):
        ctrl = TrajectoryController(_make_conn())
        should, cat, conf = ctrl.should_fire(0, 0, 0, 0, 0.5, 0)
        assert should is True

    def test_fit_succeeds_at_100(self):
        conn = _make_conn()
        for i in range(_MIN_FOR_FIT):
            _insert(conn, 1.8 if i % 3 == 0 else 1.0, action=i % 3)
        ctrl = TrajectoryController(conn)
        assert ctrl.fit() is True
        assert ctrl.is_fitted is True

    def test_fit_fails_below_100(self):
        conn = _make_conn()
        for i in range(50):
            _insert(conn, 1.8, action=0)
        ctrl = TrajectoryController(conn)
        assert ctrl.fit() is False
        assert ctrl.is_fitted is False

    def test_predict_output_types(self):
        conn = _make_conn()
        for i in range(_MIN_FOR_FIT):
            _insert(conn, 1.8 if i % 3 == 0 else 1.0)
        ctrl = TrajectoryController(conn)
        ctrl.fit()
        should, cat, conf = ctrl.should_fire(0.5, 0.5, 0, 0, 1.2, 300)
        assert isinstance(should, bool)
        assert isinstance(conf, float)
        assert 0.0 <= conf <= 1.0
        assert cat in ("explore", "compress", "continue", None)

    def test_refit_only_at_milestones(self):
        conn = _make_conn()
        ctrl = TrajectoryController(conn)
        for i in range(100):
            _insert(conn, 1.8, action=0)
        assert ctrl.fit() is True
        assert ctrl._last_fit_count == 100
        for i in range(50):
            _insert(conn, 1.8, action=0)
        assert ctrl.fit() is True  # already fitted, no refit needed
        assert ctrl._last_fit_count == 100  # count unchanged
        for i in range(400):
            _insert(conn, 1.8, action=0)
        assert ctrl.fit() is True  # 500 milestone hit
        assert ctrl._last_fit_count == 550

    def test_target_category_after_fit(self):
        conn = _make_conn()
        for i in range(_MIN_FOR_FIT):
            _insert(conn, 1.8, action=1)  # all COMPRESS
        ctrl = TrajectoryController(conn)
        ctrl.fit()
        assert ctrl.target_category() == "compress"
