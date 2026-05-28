"""
CaduceanTrajectoryRecorder — records 4D state transitions during DER execution.

Each DER step produces one trajectory record: (x, y, xi, u, action, outcome, eml_after).
Records accumulate in the MemoryInterface SQLite DB and feed the TrajectoryController.

Usage:
    from backend.agent.caducean_trajectory import get_trajectory_recorder
    recorder = get_trajectory_recorder(memory_interface)
    recorder.record(session_id="sess_1", step_num=0, x=0.0, y=0.0,
                    action=0, outcome="success", eml_after=1.2)
"""

import logging
import sqlite3
import time
from typing import Any, List, Optional, Dict

logger = logging.getLogger(__name__)

# Cached singleton per MemoryInterface instance id()
_recorders: Dict[int, "CaduceanTrajectoryRecorder"] = {}

_SQL_CREATE = """
CREATE TABLE IF NOT EXISTS caducean_trajectories (
    id          INTEGER PRIMARY KEY,
    ts          REAL,
    session_id  TEXT,
    step_num    INTEGER,
    x           REAL,
    y           REAL,
    xi          REAL,
    u           REAL,
    action      INTEGER,
    outcome     TEXT,
    eml_after   REAL
);
CREATE INDEX IF NOT EXISTS idx_ct_session ON caducean_trajectories(session_id);
CREATE INDEX IF NOT EXISTS idx_ct_ts      ON caducean_trajectories(ts);
"""


class CaduceanTrajectoryRecorder:
    """
    Lightweight recorder backed by the same SQLite DB as MemoryInterface.
    WAL mode (set by MemoryInterface init) keeps concurrent writes safe.
    """

    _eml_cache: float = 1.0

    def __init__(self, db_conn: sqlite3.Connection) -> None:
        self._conn = db_conn
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            self._conn.executescript(_SQL_CREATE)
            self._conn.commit()
        except Exception as exc:
            logger.warning("[CaduceanTrajectory] ensure_table failed: %s", exc)

    def record(
        self,
        session_id: str,
        step_num: int,
        x: float,
        y: float,
        action: int,
        outcome: str,
        eml_after: float,
    ) -> None:
        """Write one transition record. <2ms on WAL-mode SSD."""
        try:
            self._conn.execute(
                "INSERT INTO caducean_trajectories "
                "(ts, session_id, step_num, x, y, xi, u, action, outcome, eml_after) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (time.time(), session_id, step_num, x, y, 0.0, 0.0,
                 action, outcome, eml_after),
            )
            self._conn.commit()
            CaduceanTrajectoryRecorder._eml_cache = float(eml_after)
        except Exception as exc:
            logger.warning("[CaduceanTrajectory] record failed: %s", exc)

    def trajectory_count(self) -> int:
        try:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM caducean_trajectories"
            )
            row = cur.fetchone()
            return row[0] if row else 0
        except Exception as exc:
            logger.warning("[CaduceanTrajectory] trajectory_count failed: %s", exc)
            return 0

    def get_trajectories(
        self, min_count: int = 100, session_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return list of trajectory dicts, optionally filtered by session."""
        try:
            if session_id:
                rows = self._conn.execute(
                    "SELECT * FROM caducean_trajectories WHERE session_id = ? "
                    "ORDER BY ts", (session_id,)
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM caducean_trajectories ORDER BY ts"
                ).fetchall()
            cols = [d[0] for d in self._conn.execute(
                "SELECT * FROM caducean_trajectories LIMIT 0"
            ).description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception as exc:
            logger.warning("[CaduceanTrajectory] get_trajectories failed: %s", exc)
            return []

    @classmethod
    def get_cached_eml(cls) -> float:
        """Thread-safe read of last recorded EML (no FFI from async context)."""
        return cls._eml_cache


def get_trajectory_recorder(memory_interface: Any) -> CaduceanTrajectoryRecorder:
    """Return (or create) the singleton recorder for this MemoryInterface."""
    key = id(memory_interface)
    if key not in _recorders:
        episodic = getattr(memory_interface, "episodic", None)
        conn = episodic.db if episodic is not None else None
        if conn is None:
            raise RuntimeError(
                "MemoryInterface must have an active SQLite connection"
            )
        _recorders[key] = CaduceanTrajectoryRecorder(conn)
    return _recorders[key]
