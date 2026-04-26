"""
SQLite CRUD for task_collaboration and swarm_join_signals tables.
Tables are created by initialise_mycelium_schema() in backend/memory/db.py.
Uses the shared Mycelium SQLite connection — never opens its own.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

_COLLAB_COLS = [
    "collab_id", "task_id", "session_id", "status", "primary_agent",
    "helper_agents", "max_helpers", "task_summary", "context_pin_id",
    "created_at", "opened_at", "completed_at",
]
_COLLAB_SELECT = (
    "SELECT collab_id, task_id, session_id, status, primary_agent, "
    "helper_agents, max_helpers, task_summary, context_pin_id, "
    "created_at, opened_at, completed_at FROM task_collaboration"
)


def create_collaboration(conn, task_id: str, session_id: str,
                         primary_agent: str, task_summary: str,
                         max_helpers: int = 2) -> str:
    """INSERT a new working collaboration. Returns collab_id."""
    collab_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO task_collaboration
           (collab_id, task_id, session_id, status, primary_agent,
            helper_agents, max_helpers, task_summary, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (collab_id, task_id, session_id, "working", primary_agent,
         "[]", max_helpers, task_summary[:500], time.time()),
    )
    conn.commit()
    return collab_id


def open_compound(conn, collab_id: str, context_pin_id: str = None) -> None:
    """Set status='compound_open' and record opened_at timestamp."""
    conn.execute(
        """UPDATE task_collaboration
           SET status='compound_open', opened_at=?, context_pin_id=?
           WHERE collab_id=?""",
        (time.time(), context_pin_id, collab_id),
    )
    conn.commit()


def join_as_helper(conn, collab_id: str, agent_id: str) -> bool:
    """
    Append agent_id to helper_agents JSON array.
    Returns False if already joined or max_helpers reached.
    """
    row = conn.execute(
        "SELECT helper_agents, max_helpers FROM task_collaboration WHERE collab_id=?",
        (collab_id,),
    ).fetchone()
    if not row:
        return False
    helpers = json.loads(row[0] or "[]")
    if agent_id in helpers or len(helpers) >= row[1]:
        return False
    helpers.append(agent_id)
    conn.execute(
        "UPDATE task_collaboration SET helper_agents=? WHERE collab_id=?",
        (json.dumps(helpers), collab_id),
    )
    conn.commit()
    return True


def complete_collaboration(conn, collab_id: str) -> None:
    """Set status='completed' and record completed_at timestamp."""
    conn.execute(
        """UPDATE task_collaboration
           SET status='completed', completed_at=?
           WHERE collab_id=?""",
        (time.time(), collab_id),
    )
    conn.commit()


def get_open_tasks(conn, session_id: str = None) -> list[dict]:
    """Return all compound_open collaborations, optionally filtered by session."""
    q = _COLLAB_SELECT + " WHERE status='compound_open'"
    params: list = []
    if session_id:
        q += " AND session_id=?"
        params.append(session_id)
    q += " ORDER BY opened_at DESC"
    rows = conn.execute(q, params).fetchall()
    return [dict(zip(_COLLAB_COLS, r)) for r in rows]


def get_collaboration(conn, collab_id: str) -> Optional[dict]:
    """Fetch a single collaboration record by ID."""
    row = conn.execute(
        _COLLAB_SELECT + " WHERE collab_id=?", (collab_id,)
    ).fetchone()
    return dict(zip(_COLLAB_COLS, row)) if row else None
