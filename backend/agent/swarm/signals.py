"""
Swarm join signals — agents post readiness/completion to swarm_join_signals.
Other agents poll and self-assign as helpers when compound_open tasks exist.
Persists through Mycelium SQLite DB — no HTTP, no agent cards.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field

from backend.memory.db import app_flush, app_write

logger = logging.getLogger(__name__)


@dataclass
class JoinSignal:
    signal_id:   str
    collab_id:   str
    agent_id:    str
    signal_type: str
    payload:     dict  = field(default_factory=dict)
    created_at:  float = field(default_factory=time.time)


def post_signal(conn, collab_id: str, agent_id: str,
                signal_type: str, payload: dict = None) -> str:
    """Insert a join signal. Returns signal_id. Never raises."""
    try:
        signal_id = str(uuid.uuid4())
        app_write(
            conn,
            """INSERT INTO swarm_join_signals
               (signal_id, collab_id, agent_id, signal_type, payload, created_at, read_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (signal_id, collab_id, agent_id, signal_type,
             json.dumps(payload or {}), time.time(), "[]"),
        )
        return signal_id
    except Exception as exc:
        logger.warning("[swarm.signals] post_signal failed: %s", exc)
        return ""


def read_signals(conn, collab_id: str,
                 since_ts: float = None) -> list[JoinSignal]:
    """Return signals for a collab, optionally filtered by timestamp."""
    try:
        app_flush()  # one writer: a post_signal just queued must be read
        q = (
            "SELECT signal_id, collab_id, agent_id, signal_type, payload, created_at"
            " FROM swarm_join_signals WHERE collab_id = ?"
        )
        params: list = [collab_id]
        if since_ts is not None:
            q += " AND created_at > ?"
            params.append(since_ts)
        q += " ORDER BY created_at ASC"
        rows = conn.execute(q, params).fetchall()
        return [
            JoinSignal(
                signal_id=r[0], collab_id=r[1], agent_id=r[2],
                signal_type=r[3], payload=json.loads(r[4] or "{}"),
                created_at=r[5],
            )
            for r in rows
        ]
    except Exception as exc:
        logger.warning("[swarm.signals] read_signals failed: %s", exc)
        return []


def mark_read(conn, signal_id: str, agent_id: str) -> None:
    """Mark signal as read by agent_id. Never raises."""
    try:
        app_flush()  # one writer: read_by must include every queued mark_read
        row = conn.execute(
            "SELECT read_by FROM swarm_join_signals WHERE signal_id = ?",
            (signal_id,),
        ).fetchone()
        if row:
            readers = json.loads(row[0] or "[]")
            if agent_id not in readers:
                readers.append(agent_id)
                app_write(
                    conn,
                    "UPDATE swarm_join_signals SET read_by = ? WHERE signal_id = ?",
                    (json.dumps(readers), signal_id),
                )
    except Exception as exc:
        logger.warning("[swarm.signals] mark_read failed: %s", exc)


def expire_old_signals(conn, expiry_seconds: int = 300) -> int:
    """Delete signals older than expiry_seconds. Returns count deleted."""
    try:
        cutoff = time.time() - expiry_seconds
        # One writer: the count is returned to the caller, so count the rows
        # first (flush: queued posts must be counted), then queue the delete.
        app_flush()
        n = conn.execute(
            "SELECT COUNT(*) FROM swarm_join_signals WHERE created_at < ?", (cutoff,)
        ).fetchone()[0]
        app_write(
            conn, "DELETE FROM swarm_join_signals WHERE created_at < ?", (cutoff,)
        )
        return n
    except Exception as exc:
        logger.warning("[swarm.signals] expire_old_signals failed: %s", exc)
        return 0
