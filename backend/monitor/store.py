"""
Monitor Store — SQLite persistence layer for analytics/monitor data.

Completely isolated from the agent memory DB. Uses a separate file:
    data/monitor.db

Tables:
    usage_records  — one row per LLM call (tokens, model, latency, mode, timestamp)
    model_summary  — aggregated per-model totals (maintained via triggers)

Thread-safe: uses check_same_thread=False and a threading.Lock for writes.
WAL mode for concurrent reads.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Schema ───────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       REAL    NOT NULL,           -- Unix epoch seconds
    session_id      TEXT    NOT NULL DEFAULT '',
    model           TEXT    NOT NULL DEFAULT 'unknown',
    prompt_tokens   INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    audio_tokens    INTEGER NOT NULL DEFAULT 0,
    latency_ms      REAL    NOT NULL DEFAULT 0,
    mode            TEXT    NOT NULL DEFAULT 'conversation',  -- conversation | tool | voice
    estimated_cost  REAL    NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_usage_ts     ON usage_records(timestamp);
CREATE INDEX IF NOT EXISTS idx_usage_model  ON usage_records(model);
CREATE INDEX IF NOT EXISTS idx_usage_session ON usage_records(session_id);

-- Aggregated model summary (fast lookups without full-table scans)
CREATE TABLE IF NOT EXISTS model_summary (
    model              TEXT    PRIMARY KEY,
    total_calls        INTEGER NOT NULL DEFAULT 0,
    total_prompt_tokens   INTEGER NOT NULL DEFAULT 0,
    total_completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens       INTEGER NOT NULL DEFAULT 0,
    total_audio_tokens INTEGER NOT NULL DEFAULT 0,
    total_cost         REAL    NOT NULL DEFAULT 0,
    total_latency_ms   REAL    NOT NULL DEFAULT 0,
    first_seen         REAL    NOT NULL,
    last_seen          REAL    NOT NULL
);
"""


# ── Cost table (approximate, per 1K tokens) ──────────────────────────────────

_COST_PER_1K = {
    "text_input": 0.0015,
    "text_output": 0.002,
    "audio": 0.006,
}


def _estimate_cost(prompt_tokens: int, completion_tokens: int, audio_tokens: int = 0) -> float:
    """Estimate cost in USD."""
    return round(
        (prompt_tokens / 1000) * _COST_PER_1K["text_input"]
        + (completion_tokens / 1000) * _COST_PER_1K["text_output"]
        + (audio_tokens / 1000) * _COST_PER_1K["audio"],
        6,
    )


# ── Store ────────────────────────────────────────────────────────────────────

class MonitorStore:
    """
    Thread-safe SQLite store for monitor analytics data.

    Singleton — one connection shared across the process.
    WAL mode for concurrent reads; writes are serialized via a Lock.
    """

    _instance: Optional["MonitorStore"] = None
    _initialized: bool = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, db_path: Optional[str] = None):
        if MonitorStore._initialized:
            return

        if db_path is None:
            # Default: data/monitor.db relative to project root
            project_root = Path(__file__).resolve().parent.parent.parent
            db_path = str(project_root / "data" / "monitor.db")

        # Ensure parent dir exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            isolation_level=None,  # autocommit mode
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)

        MonitorStore._initialized = True

    # ── Write ─────────────────────────────────────────────────────────────────

    def record_usage(
        self,
        *,
        session_id: str = "",
        model: str = "unknown",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        audio_tokens: int = 0,
        latency_ms: float = 0,
        mode: str = "conversation",
    ) -> None:
        """Insert a usage record and update the model summary atomically."""
        total_tokens = prompt_tokens + completion_tokens
        cost = _estimate_cost(prompt_tokens, completion_tokens, audio_tokens)
        ts = time.time()

        with self._lock:
            conn = self._conn
            try:
                conn.execute("BEGIN")
                # Insert record
                conn.execute(
                    """
                    INSERT INTO usage_records
                        (timestamp, session_id, model, prompt_tokens,
                         completion_tokens, total_tokens, audio_tokens,
                         latency_ms, mode, estimated_cost)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (ts, session_id, model, prompt_tokens,
                     completion_tokens, total_tokens, audio_tokens,
                     latency_ms, mode, cost),
                )
                # Upsert model summary
                conn.execute(
                    """
                    INSERT INTO model_summary
                        (model, total_calls, total_prompt_tokens,
                         total_completion_tokens, total_tokens,
                         total_audio_tokens, total_cost, total_latency_ms,
                         first_seen, last_seen)
                    VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(model) DO UPDATE SET
                        total_calls = total_calls + 1,
                        total_prompt_tokens = total_prompt_tokens + ?,
                        total_completion_tokens = total_completion_tokens + ?,
                        total_tokens = total_tokens + ?,
                        total_audio_tokens = total_audio_tokens + ?,
                        total_cost = total_cost + ?,
                        total_latency_ms = total_latency_ms + ?,
                        last_seen = ?
                    """,
                    (model, prompt_tokens, completion_tokens, total_tokens,
                     audio_tokens, cost, latency_ms, ts, ts,
                     prompt_tokens, completion_tokens, total_tokens,
                     audio_tokens, cost, latency_ms, ts),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get_session_stats(self) -> Dict[str, Any]:
        """Aggregate stats across all records."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT
                    COUNT(*) as total_calls,
                    COALESCE(SUM(prompt_tokens), 0) as total_prompt,
                    COALESCE(SUM(completion_tokens), 0) as total_completion,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(SUM(audio_tokens), 0) as total_audio,
                    COALESCE(SUM(estimated_cost), 0) as total_cost,
                    COALESCE(SUM(latency_ms), 0) as total_latency,
                    COALESCE(MIN(timestamp), 0) as first_ts,
                    COALESCE(MAX(timestamp), 0) as last_ts
                FROM usage_records
                """
            ).fetchone()

        total_calls, total_prompt, total_completion, total_tokens, \
            total_audio, total_cost, total_latency, first_ts, last_ts = row

        avg_latency = (total_latency / total_calls) if total_calls > 0 else 0
        duration_min = (last_ts - first_ts) / 60 if first_ts > 0 and last_ts > 0 else 0

        return {
            "total_calls": total_calls or 0,
            "total_prompt_tokens": total_prompt or 0,
            "total_completion_tokens": total_completion or 0,
            "total_tokens": total_tokens or 0,
            "total_audio_tokens": total_audio or 0,
            "estimated_cost": round(total_cost or 0, 4),
            "avg_latency_ms": round(avg_latency, 2),
            "session_duration_minutes": round(duration_min, 2),
        }

    def get_model_breakdown(self) -> List[Dict[str, Any]]:
        """Per-model aggregated stats with percentage of total tokens."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT model, total_calls, total_prompt_tokens,
                       total_completion_tokens, total_tokens,
                       total_audio_tokens, total_cost,
                       total_latency_ms, first_seen, last_seen
                FROM model_summary
                ORDER BY total_tokens DESC
                """
            ).fetchall()

        grand_total = sum(r[4] for r in rows)  # total_tokens
        result = []
        for r in rows:
            (model, calls, prompt_tok, comp_tok, total_tok,
             audio_tok, cost, latency, first_seen, last_seen) = r
            pct = (total_tok / grand_total * 100) if grand_total > 0 else 0
            avg_lat = (latency / calls) if calls > 0 else 0
            result.append({
                "model": model,
                "total_calls": calls,
                "prompt_tokens": prompt_tok,
                "completion_tokens": comp_tok,
                "total_tokens": total_tok,
                "audio_tokens": audio_tok,
                "estimated_cost": round(cost, 4),
                "avg_latency_ms": round(avg_lat, 2),
                "percentage": round(pct, 1),
                "first_seen": first_seen,
                "last_seen": last_seen,
            })
        return result

    def get_latency_metrics(self) -> Dict[str, Any]:
        """Detailed latency distribution."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT latency_ms FROM usage_records WHERE latency_ms > 0 ORDER BY latency_ms"
            ).fetchall()

        if not rows:
            return {"count": 0, "min_ms": 0, "max_ms": 0, "avg_ms": 0, "p50_ms": 0, "p95_ms": 0}

        latencies = [r[0] for r in rows]
        n = len(latencies)
        p95_idx = min(n - 1, int(n * 0.95))

        return {
            "count": n,
            "min_ms": round(latencies[0], 2),
            "max_ms": round(latencies[-1], 2),
            "avg_ms": round(sum(latencies) / n, 2),
            "p50_ms": round(latencies[n // 2], 2),
            "p95_ms": round(latencies[p95_idx], 2),
        }

    def get_recent_records(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Most recent usage records for activity feed."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT timestamp, session_id, model, prompt_tokens,
                       completion_tokens, total_tokens, latency_ms, mode, estimated_cost
                FROM usage_records
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            {
                "timestamp": r[0],
                "session_id": r[1],
                "model": r[2],
                "prompt_tokens": r[3],
                "completion_tokens": r[4],
                "total_tokens": r[5],
                "latency_ms": round(r[6], 2),
                "mode": r[7],
                "estimated_cost": round(r[8], 6),
            }
            for r in rows
        ]

    def get_all_analytics(self) -> Dict[str, Any]:
        """Everything the frontend needs in one call."""
        return {
            "stats": self.get_session_stats(),
            "models": self.get_model_breakdown(),
            "latency": self.get_latency_metrics(),
            "recent": self.get_recent_records(20),
        }

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the DB connection."""
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None  # type: ignore


# ── Singleton accessor ───────────────────────────────────────────────────────

def get_monitor_store() -> MonitorStore:
    """Get the singleton MonitorStore instance."""
    return MonitorStore()
