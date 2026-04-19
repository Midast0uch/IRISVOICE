"""
SwarmCoordinator — manages compound multi-agent collaboration.

Agents self-join compound_open tasks by polling Mycelium SQLite DB.
Context is loaded from Mycelium pins + PAC-MAN episodic memory.
All thresholds/rules come from collaboration_rules.json via MCMProtocol.
No HTTP, no agent cards — pure DB coordination.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Optional

from .constants import (
    SWARM_MAX_HELPERS_DEFAULT,
    SWARM_OPEN_AFTER_PCT,
    SWARM_FINISHED_EARLY_PCT,
    SWARM_SIGNAL_FINISHED_EARLY,
    SWARM_SIGNAL_HELPER_JOINED,
    SWARM_SIGNAL_HELPER_DONE,
)
from .signals import post_signal

logger = logging.getLogger(__name__)


class SwarmCoordinator:
    """Manages compound task collaboration via Mycelium DB."""

    def __init__(self, memory_interface, session_id: str,
                 agent_id: str, protocol=None) -> None:
        self._mi        = memory_interface
        self.session_id = session_id
        self.agent_id   = agent_id or session_id
        self._protocol  = protocol   # MCMProtocol | None

    # ── Task lifecycle ────────────────────────────────────────────────────

    def create_collaboration(self, task_id: str, task_summary: str,
                             max_helpers: int = None) -> str:
        """Create a new working collaboration record. Returns collab_id."""
        conn = self._conn()
        if not conn:
            return ""
        from backend.memory.swarm_db import create_collaboration as _create
        return _create(
            conn, task_id, self.session_id, self.agent_id,
            task_summary, max_helpers or self._max_helpers(),
        )

    def open_for_compound(self, collab_id: str,
                          context_pin_id: str = None) -> None:
        """Mark task compound_open so helpers can self-join."""
        conn = self._conn()
        if not conn or not collab_id:
            return
        from backend.memory.swarm_db import open_compound as _open
        _open(conn, collab_id, context_pin_id)
        logger.info("[swarm] Task %s open for compound joining", collab_id)

    def maybe_open(self, collab_id: str, progress_pct: float,
                   context_pin_id: str = None) -> bool:
        """Open compound mode when progress_pct >= threshold. Returns True if opened."""
        if progress_pct >= self._open_after_pct():
            self.open_for_compound(collab_id, context_pin_id)
            if progress_pct >= self._finished_early_pct():
                self.signal_finished_early(
                    collab_id, progress_pct,
                    f"Agent reached {progress_pct:.0%} — available for compound join",
                )
            return True
        return False

    def signal_finished_early(self, collab_id: str, progress_pct: float,
                              context_summary: str) -> None:
        """Post finished_early signal — idle agents can join this task."""
        conn = self._conn()
        if not conn or not collab_id:
            return
        post_signal(conn, collab_id, self.agent_id, SWARM_SIGNAL_FINISHED_EARLY,
                    {"progress_pct": progress_pct,
                     "summary": context_summary[:200]})

    def find_joinable_tasks(self) -> list[dict]:
        """Return compound_open tasks this agent is eligible to join."""
        conn = self._conn()
        if not conn:
            return []
        from backend.memory.swarm_db import get_open_tasks
        tasks = get_open_tasks(conn, self.session_id)
        joinable = []
        for t in tasks:
            if t.get("primary_agent") == self.agent_id:
                continue
            helpers = json.loads(t.get("helper_agents", "[]") or "[]")
            if self.agent_id in helpers:
                continue
            if len(helpers) >= t.get("max_helpers", SWARM_MAX_HELPERS_DEFAULT):
                continue
            joinable.append(t)
        return joinable

    def join_task(self, collab_id: str) -> dict:
        """
        Self-assign as helper. Loads shared context from:
          1. context_pin_id in mycelium_pins
          2. PAC-MAN episodic assemble_episodic_context(task_summary)
        Returns {'context': str, 'pin_content': str, 'collab': dict}
        """
        conn = self._conn()
        if not conn:
            return {}
        from backend.memory.swarm_db import join_as_helper, get_collaboration
        collab = get_collaboration(conn, collab_id)
        if not collab:
            return {}
        if not join_as_helper(conn, collab_id, self.agent_id):
            return {}
        post_signal(conn, collab_id, self.agent_id, SWARM_SIGNAL_HELPER_JOINED,
                    {"agent_id": self.agent_id})
        pin_content = self._load_pin(conn, collab.get("context_pin_id"))
        ep_context  = self._load_episodic(collab.get("task_summary", ""))
        context = "\n\n".join(filter(None, [pin_content, ep_context]))
        logger.info("[swarm] Joined task %s as helper", collab_id)
        return {"context": context, "pin_content": pin_content, "collab": collab}

    def complete_helper(self, collab_id: str) -> None:
        """Signal that this helper's contribution is done."""
        conn = self._conn()
        if conn and collab_id:
            post_signal(conn, collab_id, self.agent_id,
                        SWARM_SIGNAL_HELPER_DONE, {})

    def complete_task(self, collab_id: str) -> None:
        """Mark collaboration completed."""
        conn = self._conn()
        if not conn or not collab_id:
            return
        from backend.memory.swarm_db import complete_collaboration
        complete_collaboration(conn, collab_id)

    def save_context_pin(self, collab_id: str, content: str,
                         tags: list[str] = None) -> str:
        """Pin current work artifact to mycelium_pins. Returns pin_id."""
        conn = self._conn()
        if not conn:
            return ""
        pin_id = str(uuid.uuid4())
        now = time.time()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO mycelium_pins
                   (pin_id, title, pin_type, content, tags,
                    file_refs, project_id, origin_id,
                    created_at, updated_at, is_permanent)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (pin_id, f"Swarm context {collab_id[:8]}", "fragment",
                 content, json.dumps(tags or ["swarm", "context"]),
                 "[]", "IRISVOICE", collab_id, now, now, 0),
            )
            conn.commit()
            return pin_id
        except Exception as exc:
            logger.warning("[swarm] save_context_pin failed: %s", exc)
            return ""

    # ── Internal helpers ──────────────────────────────────────────────────

    def _conn(self):
        try:
            return getattr(getattr(self._mi, "_mycelium", None), "_conn", None)
        except Exception:
            return None

    def _load_pin(self, conn, pin_id: str) -> str:
        if not conn or not pin_id:
            return ""
        try:
            row = conn.execute(
                "SELECT content FROM mycelium_pins WHERE pin_id = ?", (pin_id,)
            ).fetchone()
            return row[0] or "" if row else ""
        except Exception:
            return ""

    def _load_episodic(self, task_summary: str) -> str:
        try:
            if self._mi and hasattr(self._mi, "episodic") and task_summary:
                return self._mi.episodic.assemble_episodic_context(task_summary) or ""
        except Exception:
            pass
        return ""

    def _max_helpers(self) -> int:
        try:
            return self._protocol.collaboration.compound_mode.max_helpers_per_task
        except Exception:
            return SWARM_MAX_HELPERS_DEFAULT

    def _open_after_pct(self) -> float:
        try:
            return self._protocol.collaboration.compound_mode.open_after_pct
        except Exception:
            return SWARM_OPEN_AFTER_PCT

    def _finished_early_pct(self) -> float:
        try:
            signals = self._protocol.collaboration.signals or {}
            return signals.get("finished_early_threshold_pct", SWARM_FINISHED_EARLY_PCT)
        except Exception:
            return SWARM_FINISHED_EARLY_PCT
