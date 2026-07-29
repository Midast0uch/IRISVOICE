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
import threading
import time
from typing import Any, List, Optional, Dict, Tuple

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
    recommendation  INTEGER,
    domain          TEXT DEFAULT 'general'
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

-- DER Phase 3 (D3.3 G5): verified-commit ledger. A commit is recorded ONLY when
-- a step reaches the VERIFIED state (rubric pass). This is the honest audit trail
-- that replaces the former "auto-commit on completion" behavior — no commit is
-- written unless the work was actually verified. Store write, never a prompt inject.
CREATE TABLE IF NOT EXISTS der_commits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL,
    session_id  TEXT,
    step_id     TEXT,
    commit_hash TEXT,
    message     TEXT,
    u           REAL,
    xi          REAL,
    verified_label TEXT
);
CREATE INDEX IF NOT EXISTS idx_dc_session ON der_commits(session_id);

-- DER Phase 4 (D4.0): session-exit ledger. Written by record_session_exit when a
-- session ends (hooked from ConversationMemory.archive_on_session_end). The outer
-- loop (AIDE^2) reads this to compute the held-out metric (natural_exit_rate) and
-- to learn U_SPLIT/width/verify-strictness. Store write — never a prompt inject.
CREATE TABLE IF NOT EXISTS caducean_session_exits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL,
    session_id  TEXT,
    domain      TEXT,
    natural_exit INTEGER,   -- 1 if the session ended via a natural exit, else 0
    route_score  REAL,
    drift        REAL,
    tokens_total  REAL,     -- total LLM tokens consumed in the session
    verified_count INTEGER, -- count of VERIFIED steps (from der_commits)
    executed_steps INTEGER  -- REQ-2 AC5: total steps that reached execution
                             -- (from der_commits) — the denominator for
                             -- verified_fraction. NULL/0 means "no steps yet",
                             -- treated as neutral and excluded (REQ-2 AC6).
);
CREATE INDEX IF NOT EXISTS idx_se_session ON caducean_session_exits(session_id);
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

    # REQ-16: per-session EML cache. _eml_cache is kept as a class-level
    # scalar fallback for backward compatibility with existing tests.
    # _eml_cache_per_session provides per-session isolation.
    _eml_cache: float = 1.0
    _eml_cache_per_session: Dict[str, Tuple[float, float, float]] = {}
    _eml_cache_timestamps: Dict[str, float] = {}
    MAX_EML_SESSIONS = 128

    def __init__(self, db_conn: sqlite3.Connection = None) -> None:
        # Spec: the recorder is backed by the SAME SQLite DB as MemoryInterface.
        # When no conn is supplied (ad-hoc call sites), fall back to the project
        # coordinate DB so the recorder is always usable. This keeps the G5 commit
        # ledger and D4.0 session-exit ledger writable from any call site.
        if db_conn is None:
            import os

            _db_path = os.environ.get(
                "MCM_DB_PATH",
                os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                    ".mcm", "coordinates.db",
                ),
            )
            os.makedirs(os.path.dirname(_db_path), exist_ok=True)
            db_conn = sqlite3.connect(_db_path)
        self._conn = db_conn
        self._write_lock = threading.Lock()
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
        # REQ-1 / REQ-2: add new ledger columns to existing DBs. Each wrapped
        # individually so one missing column doesn't block the others.
        for _alter in (
            "ALTER TABLE der_commits ADD COLUMN verified_label TEXT",
            "ALTER TABLE caducean_session_exits ADD COLUMN tokens_total REAL",
            "ALTER TABLE caducean_session_exits ADD COLUMN verified_count INTEGER",
            "ALTER TABLE caducean_session_exits ADD COLUMN executed_steps INTEGER",
        ):
            try:
                self._conn.execute(_alter)
                self._conn.commit()
            except Exception:
                pass  # column already exists — expected on fresh installs

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
        domain: str = "general",  # DER Phase 4 (D4.1c): domain tag for outer-loop learning
    ) -> None:
        """Write one transition record. <2ms on WAL-mode SSD.

        v2: now takes xi, u, recommendation as required params (previously
        hardcoded to 0.0). The agent kernel calls this after every update.
        """
        try:
            with self._write_lock:
                self._conn.execute(
                    "INSERT INTO caducean_trajectories "
                    "(ts, session_id, step_num, x, y, xi, u, action, outcome, eml_after, recommendation, domain) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                        domain,
                    ),
                )
                self._conn.commit()
            CaduceanTrajectoryRecorder._eml_cache = float(eml_after)
            CaduceanTrajectoryRecorder._eml_cache_per_session[session_id] = (
                float(eml_after), float(x), float(y),
            )
            CaduceanTrajectoryRecorder._eml_cache_timestamps[session_id] = time.time()
            while len(CaduceanTrajectoryRecorder._eml_cache_per_session) > CaduceanTrajectoryRecorder.MAX_EML_SESSIONS:
                _oldest = min(
                    CaduceanTrajectoryRecorder._eml_cache_timestamps,
                    key=lambda k: CaduceanTrajectoryRecorder._eml_cache_timestamps[k],
                )
                CaduceanTrajectoryRecorder._eml_cache_per_session.pop(_oldest, None)
                CaduceanTrajectoryRecorder._eml_cache_timestamps.pop(_oldest, None)
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
            with self._write_lock:
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
        self,
        min_count: int = 100,
        session_id: Optional[str] = None,
        domain: Optional[str] = None,  # DER Phase 4 (D4.1c): filter by domain
    ) -> List[Dict[str, Any]]:
        """Return list of trajectory dicts, optionally filtered by session/domain."""
        try:
            if session_id:
                rows = self._conn.execute(
                    "SELECT * FROM caducean_trajectories WHERE session_id = ? "
                    "ORDER BY ts",
                    (session_id,),
                ).fetchall()
            elif domain:
                rows = self._conn.execute(
                    "SELECT * FROM caducean_trajectories WHERE domain = ? "
                    "ORDER BY ts",
                    (domain,),
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
    def get_cached_eml(cls, session_id: Optional[str] = None):
        """Return cached (eml, x, y) for the session, or process-wide eml.

        Per-session lookup (*session_id* given):
            Returns ``(eml, x, y)`` — the triple cached by ``record()`` for
            this session.  On a cache MISS makes ONE live FFI call
            (``ffi_caducean_get_state``) to obtain ``(x, y)``; eml is ``None``
            (caller should treat as neutral).  AC3: miss → live FFI, never
            another session's value.

        No-arg lookup (*session_id* is ``None``, backward compat):
            Returns ``cls._eml_cache`` — the process-wide latest eml written by
            any session's ``record()``.  This is NOT per-session; preserved for
            backward compatibility.
        """
        if session_id is None:
            return cls._eml_cache  # backward compat, process-wide latest eml

        cached = cls._eml_cache_per_session.get(session_id)
        if cached is not None:
            return cached  # (eml, x, y) triple

        # Cache miss: ONE live FFI call (AC3).
        try:
            from backend.gateway.iris_ffi import ffi_caducean_get_state
            state = ffi_caducean_get_state(session_id)
            x, y = state.get("x", 0.0), state.get("y", 0.0)
            return (None, float(x), float(y))
        except Exception:
            return (None, 0.0, 0.0)

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

    def record_commit(
        self,
        session_id: str,
        step_id: str,
        commit_hash: str,
        message: str,
        u: Optional[float] = None,
        xi: Optional[float] = None,
        verified_label: str = "VERIFIED",
    ) -> None:
        """DER Phase 3 (D3.3 G5): write a commit-ledger entry for EVERY executed action.

        REQ-1: called for VERIFIED / UNVERIFIED / FAILED alike (the label is recorded,
        not used to gate the write). This is the honest audit trail + learning signal
        the outer loop and the AVOID/edge-miss path consume. Crystallization + hit-
        scoring stay gated on VERIFIED at the caller. Store write — never injected
        into a prompt.
        """
        try:
            with self._write_lock:
                self._conn.execute(
                    """
                    INSERT INTO der_commits
                        (ts, session_id, step_id, commit_hash, message, u, xi, verified_label)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (time.time(), session_id, step_id, commit_hash, message,
                     u if u is not None else 0.0, xi if xi is not None else 0.0,
                     verified_label),
                )
                self._conn.commit()
        except Exception as exc:
            logger.warning("[CaduceanTrajectory] record_commit failed: %s", exc)

    def record_session_exit(
        self,
        session_id: str,
        domain: str,
        natural_exit: bool,
        route_score: float = 0.0,
        drift: float = 0.0,
        tokens_total: float = 0.0,
        verified_count: int = 0,
        executed_steps: int = 0,
    ) -> None:
        """DER Phase4 (D4.0): write a session-exit ledger entry.

        Called when a session ends (hooked from ConversationMemory.archive_on_
        session_end). The outer loop reads these to compute the held-out metric
        (natural_exit_rate) and to learn the physics parameters. Store write —
        never injected into a prompt.

        REQ-2: tokens_total + verified_count let the outer loop compute
        tokens_per_verified_step and verified_fraction for the compound gate.
        REQ-2 AC5: executed_steps is the denominator for verified_fraction — the
        total step count (any label) for this session, from the SAME honest
        der_commits ledger verified_count is derived from.
        """
        try:
            # REQ-2: derive verified_count / executed_steps from the honest commit
            # ledger so the outer loop's verified_fraction / tokens_per_verified_step
            # metrics are computed from the same source of truth as the ledger write.
            if verified_count <= 0:
                try:
                    _vc = self._conn.execute(
                        "SELECT COUNT(*) FROM der_commits "
                        "WHERE session_id = ? AND verified_label = 'VERIFIED'",
                        (session_id,),
                    ).fetchone()
                    verified_count = int(_vc[0]) if _vc else 0
                except Exception:
                    verified_count = 0
            if executed_steps <= 0:
                try:
                    _es = self._conn.execute(
                        "SELECT COUNT(*) FROM der_commits WHERE session_id = ?",
                        (session_id,),
                    ).fetchone()
                    executed_steps = int(_es[0]) if _es else 0
                except Exception:
                    executed_steps = 0
            with self._write_lock:
                self._conn.execute(
                    """
                    INSERT INTO caducean_session_exits
                        (ts, session_id, domain, natural_exit, route_score, drift,
                         tokens_total, verified_count, executed_steps)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (time.time(), session_id, domain,
                     int(bool(natural_exit)), float(route_score), float(drift),
                     float(tokens_total), int(verified_count), int(executed_steps)),
                )
                self._conn.commit()
        except Exception as exc:
            logger.warning("[CaduceanTrajectory] record_session_exit failed: %s", exc)

    def get_session_exits(
        self, domain: Optional[str] = None, limit: int = 200
    ) -> List[Dict[str, Any]]:
        """DER Phase 4: read session-exit ledger rows (optionally by domain)."""
        try:
            if domain:
                cur = self._conn.execute(
                    "SELECT session_id, domain, natural_exit, route_score, drift, "
                    "tokens_total, verified_count, executed_steps "
                    "FROM caducean_session_exits WHERE domain = ? "
                    "ORDER BY id DESC LIMIT ?",
                    (domain, limit),
                )
            else:
                cur = self._conn.execute(
                    "SELECT session_id, domain, natural_exit, route_score, drift, "
                    "tokens_total, verified_count, executed_steps "
                    "FROM caducean_session_exits ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
            return [
                {
                    "session_id": r[0],
                    "domain": r[1],
                    "natural_exit": bool(r[2]),
                    "route_score": r[3],
                    "drift": r[4],
                    "tokens_total": float(r[5] or 0.0),
                    "verified_count": int(r[6] or 0),
                    "executed_steps": int(r[7] or 0),
                }
                for r in cur.fetchall()
            ]
        except Exception as exc:
            logger.warning("[CaduceanTrajectory] get_session_exits failed: %s", exc)
            return []


# ── REQ-5: canonical 4D coordinate serialization ──────────────────────────


def format_coords(x: float, y: float, xi: float, u: float) -> str:
    """Canonical 4D coordinate string with 2 fixed decimal places.

    Format: ``"x.xx,y.yy,xi.xx,u.xx"``

    Used by the Immortus chain and document storage for trajectory-proximity
    queries.  Round-trips through ``parse_coords`` with no precision loss
    beyond the 2 decimal places.
    """
    return f"{x:.2f},{y:.2f},{xi:.2f},{u:.2f}"


def parse_coords(s: str) -> Tuple[float, float, float, float]:
    """Reverse ``format_coords``.

    Accepts only the exact format produced by ``format_coords``: 4 comma-separated
    numeric values with no extra whitespace.

    Returns:
        ``(x, y, xi, u)``

    Raises:
        TypeError: If ``s`` is ``None``.
        ValueError: If the string has the wrong field count, contains
        non-numeric values, or includes unexpected whitespace.
    """
    if s is None:
        raise TypeError("coordinate string must be str, not None")
    parts = s.split(",")
    if len(parts) != 4:
        raise ValueError(
            f"Expected 4 comma-separated values, got {len(parts)}: {s!r}"
        )
    for p in parts:
        if p != p.strip():
            raise ValueError(
                f"Unexpected whitespace in coordinate part {p!r}: {s!r}"
            )
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))
    except ValueError:
        raise ValueError(f"Non-numeric value in coordinate string: {s!r}")


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


def reset_eml_cache_for_testing() -> None:
    """Clear the EML cache (process-wide + per-session) for test isolation.

    REQ-20 AC2 — every new global store exposes a reset accessor so the shared
    autouse fixture can return the suite to identical state between tests. The
    cache lives on the CaduceanTrajectoryRecorder class, so we reset the class
    attributes directly (not a module-level alias).
    """
    CaduceanTrajectoryRecorder._eml_cache = 1.0
    CaduceanTrajectoryRecorder._eml_cache_per_session = {}
    CaduceanTrajectoryRecorder._eml_cache_timestamps = {}
