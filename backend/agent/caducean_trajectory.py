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
    id              INTEGER PRIMARY KEY,
    ts              REAL,
    session_id      TEXT,
    step_num        INTEGER,
    x               REAL,
    y               REAL,
    xi              REAL,
    u               REAL,
    action          INTEGER,
    outcome         TEXT,
    eml_after       REAL,
    recommendation  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ct_session ON caducean_trajectories(session_id);
CREATE INDEX IF NOT EXISTS idx_ct_ts      ON caducean_trajectories(ts);

-- DER Phase 0 (D0.8): fan-trace store. When DCP prunes/dedups a tool-call message, we
-- write a compact structural trace so the agent "still sees the fanning" after compaction.
-- This is a STORE write, never a prompt injection (zero standing token cost).
CREATE TABLE IF NOT EXISTS der_fan_traces (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL,
    session_id  TEXT,
    step_id     TEXT,
    tool        TEXT,
    args_hash   TEXT,
    outcome     TEXT,
    u           REAL,
    xi          REAL
);
CREATE INDEX IF NOT EXISTS idx_ft_session ON der_fan_traces(session_id);
"""

# Idempotent ALTER TABLE for existing DBs that predate the v2 column.
# Wrapped in try/except by callers — error means column already exists.
_SQL_ADD_RECOMMENDATION_COLUMN = (
    "ALTER TABLE caducean_trajectories ADD COLUMN recommendation INTEGER"
)


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
        # v2: idempotent ALTER TABLE for existing DBs (pre-v2 schemas).
        # Error = column already exists — safe to ignore.
        try:
            self._conn.execute(_SQL_ADD_RECOMMENDATION_COLUMN)
            self._conn.commit()
        except Exception:
            pass  # column already exists — expected on v2+ fresh installs

    def record(
        self,
        session_id: str,
        step_num: int,
        x: float,
        y: float,
        xi: float,
        u: float,
        action: int,
        outcome: str,
        eml_after: float,
        recommendation: int = 2,  # default CONTINUE
    ) -> None:
        """Write one transition record. <2ms on WAL-mode SSD.

        v2: now takes xi, u, recommendation as required params (previously
        hardcoded to 0.0). The agent kernel calls this after every update.
        """
        try:
            self._conn.execute(
                "INSERT INTO caducean_trajectories "
                "(ts, session_id, step_num, x, y, xi, u, action, outcome, eml_after, recommendation) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    time.time(),
                    session_id,
                    step_num,
                    x,
                    y,
                    xi,
                    u,
                    action,
                    outcome,
                    eml_after,
                    recommendation,
                ),
            )
            self._conn.commit()
            CaduceanTrajectoryRecorder._eml_cache = float(eml_after)
        except Exception as exc:
            logger.warning("[CaduceanTrajectory] record failed: %s", exc)

    def record_fan_trace(
        self,
        session_id: str,
        step_id: str,
        tool: str,
        args_hash: str,
        outcome: str,
        u: Optional[float] = None,
        xi: Optional[float] = None,
    ) -> None:
        """DER Phase 0 (D0.8): write a structural trace of a tool call that DCP is about
        to prune/drop. Preserves the fan shape without bloating the prompt. Cheap, WAL-safe."""
        try:
            self._conn.execute(
                "INSERT INTO der_fan_traces "
                "(ts, session_id, step_id, tool, args_hash, outcome, u, xi) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (time.time(), session_id, step_id, tool, args_hash, outcome, u, xi),
            )
            self._conn.commit()
        except Exception as exc:
            logger.warning("[CaduceanTrajectory] record_fan_trace failed: %s", exc)

    def trajectory_count(self) -> int:
        try:
            cur = self._conn.execute("SELECT COUNT(*) FROM caducean_trajectories")
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
                    "ORDER BY ts",
                    (session_id,),
                ).fetchall()
            else:
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
            logger.warning("[CaduceanTrajectory] get_trajectories failed: %s", exc)
            return []

    @classmethod
    def get_cached_eml(cls) -> float:
        """Thread-safe read of last recorded EML (no FFI from async context)."""
        return cls._eml_cache

    def get_latest_coordinate(
        self, session_id: str
    ) -> Optional[Dict[str, float]]:
        """Return the most recent 4D coordinate (x, y, xi, u) for a session.

        Used to place a document on the Immortus chain at the agent's actual
        reasoning-state position (coords_from), so trajectory-proximity queries
        (W7/O1) can later recall "data gathered while thinking like this".
        Returns None if no trajectory has been recorded yet for the session.
        """
        try:
            row = self._conn.execute(
                "SELECT x, y, xi, u FROM caducean_trajectories "
                "WHERE session_id = ? ORDER BY ts DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return {"x": float(row[0]), "y": float(row[1]), "xi": float(row[2]), "u": float(row[3])}
        except Exception as exc:
            logger.warning("[CaduceanTrajectory] get_latest_coordinate failed: %s", exc)
            return None


def get_trajectory_recorder(memory_interface: Any) -> CaduceanTrajectoryRecorder:
    """Return (or create) the singleton recorder for this MemoryInterface."""
    key = id(memory_interface)
    if key not in _recorders:
        episodic = getattr(memory_interface, "episodic", None)
        conn = episodic.db if episodic is not None else None
        if conn is None:
            raise RuntimeError("MemoryInterface must have an active SQLite connection")
        _recorders[key] = CaduceanTrajectoryRecorder(conn)
    return _recorders[key]
