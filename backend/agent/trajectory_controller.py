"""
TrajectoryController — learned controller for AutoResearch firing decisions.

Reads trajectory records, fits a polynomial surface mapping
(x, y, xi, u, eml, time_since_last) → (should_fire, target_category, confidence).

Replaces the fixed 1800s timer and random candidate selection in AutoResearch.

Usage:
    from backend.agent.trajectory_controller import TrajectoryController
    ctrl = TrajectoryController(db_conn)
    ctrl.fit()
    should_fire, category, confidence = ctrl.should_fire(x, y, xi, u, eml, time_since_last)
"""

import logging
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_MIN_FOR_FIT = 100
_REFIT_MILESTONES = (100, 500, 1000)


def _fire_features(row: Dict[str, Any], time_since_last: float) -> np.ndarray:
    """Build feature vector from a trajectory record + time delta."""
    return np.array([
        float(row.get("x", 0.5)),
        float(row.get("y", 0.5)),
        float(row.get("xi", 0.0)),
        float(row.get("u", 0.0)),
        float(row.get("eml_after", 1.0)),
        min(1.0, time_since_last / 3600.0),  # normalized to hours
        1.0,  # bias
    ], dtype=np.float64)


class TrajectoryController:
    """
    Data-driven AutoResearch scheduler.

    - Bootstrap (<100 records): EML threshold rule
    - Fitted (≥100 records): polynomial regression on trajectory data
    - Refit milestones: 100, 500, 1000, then every 500 additional records
    """

    def __init__(self, db_conn: sqlite3.Connection) -> None:
        self._conn = db_conn
        self._lock = threading.Lock()
        self._coeffs: Optional[np.ndarray] = None  # shape (7,)
        self._last_fit_count: int = 0
        self._last_fire_ts: float = 0.0
        self._target_category: Optional[str] = None

    # ── Data access ───────────────────────────────────────────────────

    def _trajectory_count(self) -> int:
        try:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM caducean_trajectories"
            )
            row = cur.fetchone()
            return row[0] if row else 0
        except Exception as exc:
            logger.warning("[TrajectoryController] count failed: %s", exc)
            return 0

    def _get_rows(self) -> List[Dict[str, Any]]:
        try:
            rows = self._conn.execute(
                "SELECT * FROM caducean_trajectories ORDER BY ts"
            ).fetchall()
            cols = [d[0] for d in self._conn.execute(
                "SELECT * FROM caducean_trajectories LIMIT 0"
            ).description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception as exc:
            logger.warning("[TrajectoryController] get_rows failed: %s", exc)
            return []

    # ── Fitting ────────────────────────────────────────────────────────

    @property
    def is_fitted(self) -> bool:
        return self._coeffs is not None

    def _needs_refit(self) -> bool:
        count = self._trajectory_count()
        if count < _MIN_FOR_FIT:
            return False
        if count < self._last_fit_count:
            return True  # table was reset
        for m in _REFIT_MILESTONES:
            if self._last_fit_count < m <= count:
                return True
        # After 1000, every 500
        if count >= 1000 and count - self._last_fit_count >= 500:
            return True
        return False

    def fit(self) -> bool:
        """
        Fit (or refit) polynomial regression on trajectory data.
        Label: fire=1 if EML > 1.5 or EML < 0.7 at that step, else 0.
        Returns True if fit succeeded.
        """
        with self._lock:
            if not self._needs_refit():
                return self._coeffs is not None

            rows = self._get_rows()
            if len(rows) < _MIN_FOR_FIT:
                return False

            # Build training matrix
            X = np.zeros((len(rows), 7), dtype=np.float64)
            y = np.zeros(len(rows), dtype=np.float64)
            for i, row in enumerate(rows):
                X[i] = _fire_features(row, 0.0)
                eml = float(row.get("eml_after", 1.0))
                y[i] = 1.0 if eml > 1.5 or eml < 0.7 else 0.0

            try:
                self._coeffs, *_ = np.linalg.lstsq(X, y, rcond=None)
                self._last_fit_count = len(rows)

                # Derive target_category from most frequent action in high-EML rows
                high_eml = [r for r in rows if float(r.get("eml_after", 1.0)) > 1.3]
                if high_eml:
                    actions = [r.get("action", 0) for r in high_eml]
                    most_common = max(set(actions), key=actions.count)
                    cat_map = {0: "explore", 1: "compress", 2: "continue"}
                    self._target_category = cat_map.get(most_common, "explore")
                else:
                    self._target_category = "explore"

                logger.info(
                    "[TrajectoryController] fit on %d rows (R² check recommended)",
                    len(rows),
                )
                return True
            except Exception as exc:
                logger.warning("[TrajectoryController] fit failed: %s", exc)
                return False

    # ── Inference ──────────────────────────────────────────────────────

    def should_fire(
        self,
        x: float,
        y: float,
        xi: float,
        u: float,
        eml: float,
        time_since_last: float,
    ) -> Tuple[bool, Optional[str], float]:
        """
        Returns (should_fire, target_category, confidence).
        """
        # Bootstrap fallback when not fitted
        if self._coeffs is None:
            should = eml > 1.5 or eml < 0.7
            return should, None, 0.5

        features = np.array([x, y, xi, u, eml,
                             min(1.0, time_since_last / 3600.0), 1.0],
                            dtype=np.float64)
        raw = float(np.dot(features, self._coeffs))
        prob = float(1.0 / (1.0 + np.exp(-raw)))
        should = prob >= 0.35
        return should, self._target_category, prob

    def target_category(self) -> Optional[str]:
        """Return the last-computed target category, or None if not fitted."""
        return self._target_category
