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

from backend.agent.param_homeostasis import get_param_homeostasis

logger = logging.getLogger(__name__)

_MIN_FOR_FIT = 100
_REFIT_MILESTONES = (100, 500, 1000)


def _fire_features(row: Dict[str, Any], time_since_last: float) -> np.ndarray:
    """Build feature vector from a trajectory record + time delta."""
    return np.array(
        [
            float(row.get("x", 0.5)),
            float(row.get("y", 0.5)),
            float(row.get("xi", 0.0)),
            float(row.get("u", 0.0)),
            float(row.get("eml_after", 1.0)),
            min(1.0, time_since_last / 3600.0),  # normalized to hours
            1.0,  # bias
        ],
        dtype=np.float64,
    )


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
        # High-water mark of violation row ids already charged, per session.
        # Prevents re-charging the same violation on every call (a compounding
        # ratchet). See REQ-21.
        self._last_charged_violation_id: Dict[str, int] = {}

    # ── Data access ───────────────────────────────────────────────────

    def _trajectory_count(self) -> int:
        try:
            cur = self._conn.execute("SELECT COUNT(*) FROM caducean_trajectories")
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
            cols = [
                d[0]
                for d in self._conn.execute(
                    "SELECT * FROM caducean_trajectories LIMIT 0"
                ).description
            ]
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

        features = np.array(
            [x, y, xi, u, eml, min(1.0, time_since_last / 3600.0), 1.0],
            dtype=np.float64,
        )
        raw = float(np.dot(features, self._coeffs))
        prob = float(1.0 / (1.0 + np.exp(-raw)))
        should = prob >= 0.35
        return should, self._target_category, prob

    def target_category(self) -> Optional[str]:
        """Return the last-computed target category, or None if not fitted."""
        return self._target_category

    # ── v2: Caducean Duffing parameter tuning ──────────────────────────
    #
    # When the adaptive safety net fires TOPO_VIOLATION, the engine
    # parameters (a, b, s) may need adjustment to recover stability.
    # The rule (per plan §3.3 and the architecture doc):
    #   violation_count > 0:
    #     new_a = clamp(prev_a + 0.10 * violation_count, 1.0, 4.0)
    #     new_b = clamp(prev_b + 0.05 * violation_count, 1.0, 4.0)
    #     new_s = clamp(prev_s - 0.01 * violation_count, 0.1, 0.8)
    # Rationale:
    #   a,b ∈ [1, 4]: below 1 flattens wells (no attractors); above 4
    #     creates chaotic deep wells (instability). Gate 1 baseline = 2.0.
    #   s ∈ [0.1, 0.8]: below 0.1 essentially static; above 0.8 chaotic
    #     exploration.

    def tune_dffing_params(
        self,
        session_id: str,
        lookback: int = 100,
    ) -> Optional[Tuple[float, float, float]]:
        """v2: tune (a, b, s) for a session based on recent TOPO_VIOLATIONs.

        Reads the last `lookback` trajectory rows for `session_id`, counts
        rows where recommendation == 3 (TOPO_VIOLATION), and calls
        ffi_caducean_set_params with adjusted values clamped to safe
        ranges. Persists tuned values by calling set_params (which the
        C++ side applies per-session).

        Returns (new_a, new_b, new_s) on success, None if no engine
        available or insufficient data.

        The tuned values are NOT persisted to disk in v2 (decision in
        the plan: log to file is simpler, table is more robust). We log
        to irisvoice.log for v2; a caducean_session_params table can be
        added in v3 if needed.
        """
        try:
            from backend.gateway.iris_ffi import (
                ffi_caducean_set_params,
                ffi_caducean_get_state,
            )
        except Exception:
            return None

        try:
            # Count only TOPO_VIOLATIONs NEW since the last charge for this
            # session (row id > high-water mark). Re-counting the whole lookback
            # on every call double-charges the same violation — a compounding
            # ratchet no relaxation constant can offset (REQ-21).
            last_id = self._last_charged_violation_id.get(session_id, 0)
            rows = self._conn.execute(
                "SELECT id FROM caducean_trajectories "
                "WHERE session_id = ? AND id > ? AND recommendation = 3 "
                "ORDER BY id DESC LIMIT ?",
                (session_id, last_id, lookback),
            ).fetchall()
            new_violation_ids = [r[0] for r in rows]
            new_count = len(new_violation_ids)
            if new_count == 0:
                # No NEW violations since last charge — idempotent, no action.
                return None

            # Fetch current params (or use defaults if session unknown).
            state = ffi_caducean_get_state(session_id)
            cur_a = state.get("a", 2.0)
            cur_b = state.get("b", 2.0)
            cur_s = state.get("s", 0.35)

            # Apply the v2 update rule with explicit clamp — charge ONLY the
            # new violations.
            new_a = max(1.0, min(4.0, cur_a + 0.10 * new_count))
            new_b = max(1.0, min(4.0, cur_b + 0.05 * new_count))
            new_s = max(0.1, min(0.8, cur_s - 0.01 * new_count))

            # Push to the engine.
            ok = ffi_caducean_set_params(session_id, new_a, new_b, new_s)
            if not ok:
                return None

            # Advance the high-water mark so these violations are not charged
            # again (REQ-21 idempotency). Only after the engine accepts the
            # write, so a failed write is retried, not silently dropped.
            self._last_charged_violation_id[session_id] = max(new_violation_ids)

            # Log the tuning (v2: log to file; v3: persist to table).
            logger.info(
                "[TrajectoryController] tuned %s: new_violations=%d a=%.2f->%.2f b=%.2f->%.2f s=%.2f->%.2f",
                session_id,
                new_count,
                cur_a,
                new_a,
                cur_b,
                new_b,
                cur_s,
                new_s,
            )
            # Register this perturbation with the homeostat (REQ-15 AC1).
            try:
                get_param_homeostasis().register_perturbation(
                    session_id, "violation_tune"
                )
            except Exception:  # noqa: BLE001
                pass
            return (new_a, new_b, new_s)
        except Exception as exc:
            logger.warning("[TrajectoryController] tune_dffing_params failed: %s", exc)
            return None
