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
import weakref
from typing import Any, List, Optional, Dict, Tuple

logger = logging.getLogger(__name__)


class _NullMemoryInterfaceMarker:
    """Stable weakref-able stand-in for ``get_trajectory_recorder(None)``.

    ``None`` is not weakref-able, and keying the cache on ``id(None)`` made
    every unbound call share one bucket. Using one stable marker object keeps
    the no-op-recorder singleton semantics without an id() key.
    """

    def __repr__(self) -> str:
        return "<NullMemoryInterface>"


# Cached singleton per MemoryInterface OBJECT (weak key — entry drops when the
# interface is GC'd; never keyed on id(), whose reuse would hand a stale
# recorder bound to the WRONG store to a new interface).
_recorders: "weakref.WeakKeyDictionary[Any, Any]" = weakref.WeakKeyDictionary()

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

# REQ-12 (T10): existing DBs that predate the `domain` column (BUILD store has
# it, app store did not — baseline-report §8) need the idempotent ALTER. The
# _SQL_CREATE covers fresh installs; this covers pre-domain stores. Wrapped in
# try/except by the caller — error means the column already exists.
_SQL_ADD_DOMAIN_COLUMN = (
    "ALTER TABLE caducean_trajectories ADD COLUMN domain TEXT DEFAULT 'general'"
)

# REQ-21 (T22): per-domain physics aggregation needs the two ontology axes on
# the trajectory row itself — execution_domain (how it ran: voice|der|research)
# and topic_domain (what it is about: DOMAIN_IDS registry). Same idempotent
# ALTER pattern as above — error means the column already exists.
_SQL_ADD_EXECUTION_DOMAIN_COLUMN = (
    "ALTER TABLE caducean_trajectories ADD COLUMN execution_domain TEXT DEFAULT 'der'"
)
_SQL_ADD_TOPIC_DOMAIN_COLUMN = (
    "ALTER TABLE caducean_trajectories ADD COLUMN topic_domain TEXT DEFAULT 'general'"
)


class CaduceanTrajectoryRecorder:
    """
    Lightweight recorder for Caducean trajectory / DER-commit / session-exit rows.

    REQ-20 binding rule: application call sites MUST bind to the APPLICATION
    store via ``get_trajectory_recorder(memory_interface)`` (which resolves
    ``memory_interface.episodic.db``) or by passing an explicit ``db_conn``.
    Constructing without a connection now RAISES — it must never silently bind
    to the BUILD-memory database (``MCM_DB_PATH`` / ``.mcm/coordinates.db``),
    which previously received every bare-constructed recorder's writes and
    starved ``backend/data/memory.db`` (REQ-20 AC2).
    """

    # REQ-16: per-session EML cache. _eml_cache is kept as a class-level
    # scalar fallback for backward compatibility with existing tests.
    # _eml_cache_per_session provides per-session isolation.
    _eml_cache: float = 1.0
    _eml_cache_per_session: Dict[str, Tuple[float, float, float]] = {}
    _eml_cache_timestamps: Dict[str, float] = {}
    MAX_EML_SESSIONS = 128

    def __init__(self, db_conn: sqlite3.Connection = None) -> None:
        # REQ-20 AC2: a bare constructor used to fall back to the BUILD-memory
        # database (MCM_DB_PATH / .mcm/coordinates.db). That silent alternate
        # binding is removed: every application call site must go through
        # get_trajectory_recorder(memory_interface) (app store) or pass an
        # explicit db_conn. Failing loudly beats writing to the wrong store.
        if db_conn is None:
            raise ValueError(
                "CaduceanTrajectoryRecorder requires an explicit sqlite3 "
                "Connection. Application call sites must use "
                "get_trajectory_recorder(memory_interface) to bind to the "
                "APPLICATION store (memory_config.json db_path — the "
                "repo-root-anchored data/memory.db, resolved via "
                "backend.memory.config.resolve_memory_store_path); bare "
                "construction previously wrote to the BUILD-memory "
                ".mcm/coordinates.db (REQ-20 AC2)."
            )
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
        # REQ-12 (T10): idempotent ALTER for pre-domain stores (baseline-report
        # §8 schema delta). Error = column already exists — safe to ignore.
        try:
            self._conn.execute(_SQL_ADD_DOMAIN_COLUMN)
            self._conn.commit()
        except Exception:
            pass  # column already exists — expected on fresh installs
        # REQ-21 (T22): idempotent ALTERs for the two ontology axes on the
        # trajectory row. Error = column already exists — safe to ignore.
        for _alter in (_SQL_ADD_EXECUTION_DOMAIN_COLUMN,
                       _SQL_ADD_TOPIC_DOMAIN_COLUMN):
            try:
                self._conn.execute(_alter)
                self._conn.commit()
            except Exception:
                pass  # column already exists — expected on fresh installs
        # REQ-1 / REQ-2: add new ledger columns to existing DBs. Each wrapped
        # individually so one missing column doesn't block the others.
        for _alter in (
            "ALTER TABLE der_commits ADD COLUMN verified_label TEXT",
            "ALTER TABLE caducean_session_exits ADD COLUMN tokens_total REAL",
            "ALTER TABLE caducean_session_exits ADD COLUMN verified_count INTEGER",
            "ALTER TABLE caducean_session_exits ADD COLUMN executed_steps INTEGER",
            # GROUND TRUTH T19 (REQ-9 AC2/AC3): WHY the run stopped, plus the
            # bound's configured and measured values so "how close was it" is
            # answerable without a reproduction. Additive, idempotent, and it
            # adds NO new bound (REQ-9 AC5) - it records the eight-plus that
            # already exist across four modules.
            "ALTER TABLE caducean_session_exits ADD COLUMN termination_cause TEXT",
            "ALTER TABLE caducean_session_exits ADD COLUMN bound_configured REAL",
            "ALTER TABLE caducean_session_exits ADD COLUMN bound_measured REAL",
            "ALTER TABLE caducean_session_exits ADD COLUMN co_occurring_cause TEXT",
            "ALTER TABLE caducean_session_exits ADD COLUMN bound_disabled INTEGER",
            # GROUND TRUTH Finding 10: exits were attributable to NOTHING. The
            # ledger held 431 rows over TWO session ids while `episodes` spanned
            # 47, overlapping on one - because exits carry the kernel's
            # process-level session_id while episodes carry a per-conversation
            # id. The outer loop's held-out metric (natural_exit_rate) is
            # computed over this ledger, so it was measuring a placeholder.
            # ADDITIVE: session_id is untouched, so the 431 existing rows and
            # every existing query keep working; joins move to conversation_id.
            "ALTER TABLE caducean_session_exits ADD COLUMN conversation_id TEXT",
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
        execution_domain: Optional[str] = None,  # REQ-21 (T22): voice|der|research
        topic_domain: Optional[str] = None,      # REQ-21 (T22): DOMAIN_IDS registry
    ) -> None:
        """Write one transition record. <2ms on WAL-mode SSD.

        v2: now takes xi, u, recommendation as required params (previously
        hardcoded to 0.0). The agent kernel calls this after every update.

        v2.1 (T22): carries the two ontology axes (execution_domain /
        topic_domain) so REQ-21 per-domain aggregation can key on them. When
        either is None they default to the legacy ``domain`` value, so a
        pre-ontology caller (auto_research, tests) still lands a taggable row.
        """
        try:
            _exec_domain = execution_domain if execution_domain is not None else domain
            _topic_domain = topic_domain if topic_domain is not None else domain
            with self._write_lock:
                self._conn.execute(
                    "INSERT INTO caducean_trajectories "
                    "(ts, session_id, step_num, x, y, xi, u, action, outcome, eml_after, recommendation, domain, execution_domain, topic_domain) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                        _exec_domain,
                        _topic_domain,
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

    def compute_domain_aggregates(
        self, session_id: str, axis: str = "execution_domain"
    ) -> Dict[str, "PhysicsAggregate"]:
        """REQ-21 (T22): per-domain physics aggregates for a session.

        Aggregates avg |u|, oscillation rate, convergence rate, and
        split/collapse counts per ``execution_domain`` (default) or per
        ``topic_domain``, read from the session's trajectory rows.

        - Off the hot path (AC3): computed at session boundaries / on demand,
          never per-step.
        - One-sample domain -> reported with n=1 (edge case: reported, not
          hidden).
        - No rows / pre-ontology store -> empty dict (AC3 edge: absent, not
          zero) — never raises.
        - Aggregation failure -> logged and skipped, never errors the turn.

        Returns a mapping ``{domain_value: PhysicsAggregate}``; callers use
        ``.as_dict()`` for the read-only signal.
        """
        result: Dict[str, PhysicsAggregate] = {}
        try:
            _cols = {
                r[1] for r in self._conn.execute(
                    "PRAGMA table_info(caducean_trajectories)"
                )
            }
            if axis not in _cols:
                logger.debug(
                    "[CaduceanTrajectory] domain axis %s absent — "
                    "aggregation skipped (pre-T22 store)",
                    axis,
                )
                return result
            rows = self._conn.execute(
                "SELECT u, {} FROM caducean_trajectories "
                "WHERE session_id = ?".format(axis),
                (session_id,),
            ).fetchall()
            per_domain: Dict[str, list] = {}
            for (u, dom) in rows:
                key = (dom or "").strip() or "general"
                per_domain.setdefault(key, []).append(abs(float(u or 0.0)))
            for dom, mags in per_domain.items():
                n = len(mags)
                osc = sum(1 for m in mags if _u_band(m) == "oscillating")
                conv = sum(1 for m in mags if _u_band(m) == "converged")
                split_zone = sum(1 for m in mags if _u_band(m) == "split_zone")
                # split_count: rows in the below-split deep-oscillation zone
                # (the growth-width trigger); collapse_count: rows converged
                # (folded back to an answer). Both count OCCURRENCES over the
                # session's trajectory, so a volatile domain shows high counts.
                result[dom] = PhysicsAggregate(
                    domain=dom,
                    axis=axis,
                    n=n,
                    avg_u_mag=sum(mags) / n,
                    oscillation_rate=osc / n,
                    convergence_rate=conv / n,
                    split_count=split_zone,
                    collapse_count=conv,
                )
        except Exception as exc:
            logger.debug(
                "[CaduceanTrajectory] domain aggregation skipped: %s", exc
            )
        return result

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
        termination: Optional[Any] = None,
        conversation_id: Optional[str] = None,
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

        GROUND TRUTH T19 (REQ-9): ``termination`` is an optional
        ``TerminationRecord`` naming WHICH bound ended the run, with that bound's
        configured and measured values. Optional so every existing caller keeps
        working unchanged; when absent the cause columns stay NULL and the REQ-6
        invariant reports that honestly rather than inventing one.
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
            # GROUND TRUTH T19 (REQ-9): unpack the termination record when the
            # caller supplied one. Never raises on a malformed record - a bad
            # cause is worth less than the exit row it would take down with it.
            _tc = _bc = _bm = _cc = None
            _bd = 0
            if termination is not None:
                try:
                    _d = termination.to_dict()
                    _tc = _d.get("termination_cause")
                    _bc = _d.get("bound_configured")
                    _bm = _d.get("bound_measured")
                    _cc = _d.get("co_occurring_cause")
                    _bd = int(_d.get("bound_disabled") or 0)
                except Exception:
                    _tc = "unexpected"
            with self._write_lock:
                self._conn.execute(
                    """
                    INSERT INTO caducean_session_exits
                        (ts, session_id, domain, natural_exit, route_score, drift,
                         tokens_total, verified_count, executed_steps,
                         termination_cause, bound_configured, bound_measured,
                         co_occurring_cause, bound_disabled, conversation_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (time.time(), session_id, domain,
                     int(bool(natural_exit)), float(route_score), float(drift),
                     float(tokens_total), int(verified_count), int(executed_steps),
                     _tc, _bc, _bm, _cc, _bd, conversation_id),
                )
                self._conn.commit()
        except Exception as exc:
            logger.warning("[CaduceanTrajectory] record_session_exit failed: %s", exc)

    def record_topic_domain_coverage(self, session_id: str) -> Optional[bool]:
        """REQ-18 AC1c (T19): run the topic_domain coverage check at a session
        boundary and persist the finding to the session-exit ledger.

        Called from the same session-end hook as ``record_session_exit`` — the
        outer loop's measurement point. Returns the check outcome
        (True = discriminating / False = modal bucket dominates) or None when
        the store predates the typed columns. Off the hot path; never raises.
        """
        try:
            report = DomainCoverageReport(self._conn)
            dist = report.report_distribution(session_id)
            ok, detail = DomainCoverageReport.check_coverage(dist)
            logger.info(
                "[CaduceanTrajectory] session %s topic_domain coverage: %s "
                "(%s)",
                session_id, "OK" if ok else "FAIL", detail,
            )
            return ok
        except Exception as exc:
            logger.debug(
                "[CaduceanTrajectory] topic_domain coverage check skipped: %s",
                exc,
            )
            return None

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


# ── REQ-18 AC1c (T19): per-session topic_domain distribution + coverage ───


class DomainCoverageReport:
    """REQ-18 AC1c (T19): the DISCRIMINATION check for the topic_domain axis.

    Registry-backing prevents free text (AC2) but does NOT guarantee the axis
    carries information — the pre-T19 failure was EVERY row being "general".
    This is the falsifiable measurement: report the per-session distribution
    of ``topic_domain`` across DER nodes (memory_chain rows) and FAIL the
    coverage check when the modal domain exceeds the observed-data threshold.
    Same falsifiability pattern as REQ-5 AC5 (measured-then-tuned): the
    initial limit is conservative; the measured distribution from the first
    real multi-topic session (T24) tunes it.
    """

    DEFAULT_MODAL_SHARE_LIMIT = 0.95

    def __init__(self, conn=None):
        self._conn = conn

    def report_distribution(self, session_id: str) -> Dict[str, int]:
        """Distribution of ``topic_domain`` over the session's DER chain rows.

        Rows written before the T19 typed columns (NULL) are counted under
        the registry's ``general`` bucket — normalization at query time, never
        an in-place rewrite of legacy rows (REQ-18 Edge Cases). Read-only.
        """
        dist: Dict[str, int] = {}
        if self._conn is None:
            return dist
        try:
            _cols = {
                r[1] for r in self._conn.execute("PRAGMA table_info(memory_chain)")
            }
            if "topic_domain" not in _cols:
                # Pre-T19 store — every node is untyped; report the degenerate
                # distribution as all-general so the coverage check fails
                # loudly instead of silently passing on a schema gap.
                _n = self._conn.execute(
                    "SELECT COUNT(*) FROM memory_chain WHERE thread_id = ?",
                    (session_id,),
                ).fetchone()
                if _n and _n[0]:
                    return {"general": int(_n[0])}
                return {}
            rows = self._conn.execute(
                "SELECT topic_domain FROM memory_chain WHERE thread_id = ?",
                (session_id,),
            ).fetchall()
            for (td,) in rows:
                key = (td or "").strip() or "general"
                dist[key] = dist.get(key, 0) + 1
        except Exception as exc:
            logger.debug(
                "[trajectory] topic_domain distribution unavailable: %s", exc
            )
        return dist

    @classmethod
    def check_coverage(
        cls,
        dist: Dict[str, int],
        modal_share_limit: float = DEFAULT_MODAL_SHARE_LIMIT,
    ) -> Tuple[bool, Dict[str, Any]]:
        """FAIL when the modal ``topic_domain`` exceeds ``modal_share_limit``.

        Returns ``(ok, detail)`` where detail carries the modal bucket, its
        share, the limit, and n — so a failure names the problem (e.g.
        'modal general 1.00 > 0.95') instead of asserting in the dark.
        """
        total = sum(dist.values())
        if total == 0:
            return False, {"modal": None, "share": 0.0, "n": 0}
        modal = max(dist, key=lambda k: dist[k])
        share = dist[modal] / total
        ok = share <= modal_share_limit
        return ok, {
            "modal": modal,
            "share": round(share, 4),
            "n": total,
            "limit": modal_share_limit,
        }


# ── REQ-21 (T22): per-domain physics aggregation ──────────────────────────


class PhysicsAggregate:
    """REQ-21 (T22): one domain's physics summary for a session.

    The signal the outer loop (REQ-16) and the narration tuning gate (REQ-15)
    read: which domains oscillate and which converge. Computed OFF the hot
    path (batched at session boundary, never per-step).

    Bands reuse the production narration thresholds (der_constants U_SPLIT /
    U_CONVERGED) so the aggregation and the narration speak the same physics:
      - oscillating  : U_SPLIT < |u| < U_CONVERGED
      - converged    : |u| >= U_CONVERGED
      - split zone   : |u| <= U_SPLIT (below split — the deep-oscillation
                       zone that drives growth-width splits)
    """

    def __init__(
        self,
        domain: str,
        axis: str,  # "execution_domain" | "topic_domain"
        n: int = 0,
        avg_u_mag: float = 0.0,
        oscillation_rate: float = 0.0,
        convergence_rate: float = 0.0,
        split_count: int = 0,
        collapse_count: int = 0,
    ):
        self.domain = domain
        self.axis = axis
        self.n = n
        self.avg_u_mag = avg_u_mag
        self.oscillation_rate = oscillation_rate
        self.convergence_rate = convergence_rate
        self.split_count = split_count
        self.collapse_count = collapse_count

    def as_dict(self) -> Dict[str, Any]:
        """Read-only dict surface (REQ-21 AC2) — never mutated by callers."""
        return {
            "domain": self.domain,
            "axis": self.axis,
            "n": self.n,
            "avg_u_mag": round(self.avg_u_mag, 4),
            "oscillation_rate": round(self.oscillation_rate, 4),
            "convergence_rate": round(self.convergence_rate, 4),
            "split_count": self.split_count,
            "collapse_count": self.collapse_count,
        }

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"<PhysicsAggregate {self.axis}={self.domain} n={self.n} "
            f"avg|u|={self.avg_u_mag:.3f} osc={self.oscillation_rate:.2f} "
            f"conv={self.convergence_rate:.2f} split={self.split_count} "
            f"collapse={self.collapse_count}>"
        )


def _u_band(u_mag: float) -> str:
    """Classify |u| into a narration band (same thresholds as der_constants).

    Imported lazily so a constants import cycle can never break aggregation.
    """
    try:
        from backend.agent.der_constants import U_CONVERGED, U_SPLIT
    except Exception:
        U_SPLIT, U_CONVERGED = 0.5, 0.85  # production defaults (never drift)
    if u_mag >= U_CONVERGED:
        return "converged"
    if u_mag > U_SPLIT:
        return "oscillating"
    return "split_zone"


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


class _NoopTrajectoryRecorder:
    """Disconnected recorder (pin_42ddd255162d).

    The Caducean update block must never be poisoned by an unopenable episodic
    store. Reads return None/empty, writes are no-ops — coordinates stay honestly
    UNEXERCISED (CADUCEAN_ARCHITECTURE.md §8) until the store is openable.
    REQ-20: this is the honest degradation for an app-store binding that cannot
    open memory.db — never a fallback to the BUILD-memory database.
    """

    def get_latest_coordinate(self, session_id: str) -> Optional[str]:
        return None

    def record(self, **kwargs) -> None:
        return None

    def record_commit(self, **kwargs) -> None:
        return None

    def record_session_exit(self, **kwargs) -> None:
        return None

    def get_session_exits(self, domain: Optional[str] = None, limit: int = 200) -> list:
        return []

    def compute_domain_aggregates(self, session_id: str, axis: str = "execution_domain") -> dict:
        return {}


def get_trajectory_recorder(memory_interface: Any) -> CaduceanTrajectoryRecorder:
    """Return (or create) the singleton recorder for this MemoryInterface.

    Keyed on the MemoryInterface OBJECT (weakly), not ``id()``: an id-keyed
    cache returns a stale recorder bound to the WRONG store when a collector
    object is GC'd and its id is reused (REQ-20 binding correctness). The
    weak key also frees the entry when the interface is dropped (no leak).
    """
    if memory_interface is None:
        memory_interface = _NullMemoryInterfaceMarker()  # id(None) was a single
        # shared bucket; None is not weakref-able, so use a stable marker object.
    recorder = _recorders.get(memory_interface)
    if recorder is None:
        episodic = getattr(memory_interface, "episodic", None)
        conn = None
        if episodic is not None:
            try:
                conn = episodic.db  # lazy-open property; may raise per context
            except Exception:
                conn = None
        if conn is None:
            # pin_42ddd255162d: a recorder we cannot bind must not poison the
            # whole Caducean update block (it did — every DER finalize skipped
            # the physics update AND, via the kernel's broad try, the u/xi
            # bindings, which is what made narration mute). Return a no-op
            # recorder: reads are None, writes are no-ops, so coordinates stay
            # honestly UNEXERCISED (CADUCEAN_ARCHITECTURE.md §8) until the
            # store is actually openable.
            logger.warning(
                "[trajectory] episodic store not openable for %s — "
                "no-op recorder in use (coords stay UNEXERCISED)",
                type(memory_interface).__name__,
            )
            recorder = _NoopTrajectoryRecorder()  # type: ignore[assignment]
        else:
            recorder = CaduceanTrajectoryRecorder(conn)
        _recorders[memory_interface] = recorder
    return recorder


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
