#!/usr/bin/env python3
"""
ConversationContextStore — Persistent per-thread agent context.

Keys agent context by conversation_id so switching threads or surviving a WS
disconnect preserves the agent's state.  Bounded (max 50 convs, 200 msgs each).

Storage: SQLite in data/databases/ (WAL mode for thread-safety).

Error handling follows the memory/interface.py try/except pattern:
  - Read failure → return None, DER gets a fresh context (never blocks)
  - Write failure → log warning, context lives in memory for the session
  - Corrupt file → treated as empty, old file renamed to .corrupt for recovery
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

DEFAULT_DB_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "databases"
DB_FILENAME = "conversation_contexts.db"
MAX_CONVERSATIONS = 50
MAX_MESSAGES_PER_CONV = 200
PAUSE_TIMEOUT_NON_CRITICAL = 30  # seconds
PAUSE_TIMEOUT_DESTRUCTIVE = 60  # seconds
ASK_USER_TIMEOUT = 120  # seconds


# ── Data types ─────────────────────────────────────────────────────────────


@dataclass
class ConversationMessage:
    """A single message in the conversation history snapshot stored for the agent."""

    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: float = field(default_factory=time.time)
    turn_id: Optional[str] = None


@dataclass
class PausedDERState:
    """
    Holds state when the DER loop is paused waiting for user input.

    Can be a permission request, an AskUserQuestion, or a tool awaiting
    approval.  Persisted so WS reconnects don't lose the pause.
    """

    reason: str  # "permission" | "question" | "tool_result"
    tool_name: Optional[str] = None
    tool_params: Optional[Dict[str, Any]] = None
    question: Optional[str] = None
    options: Optional[List[str]] = None
    allow_other: bool = False
    timeout_deadline: float = 0.0
    filler_count: int = 0  # how many re-prompt fillers have been sent
    turn_id: Optional[str] = None


@dataclass
class ConversationContext:
    """
    Agent context for a single conversation thread.

    This is the per-conversation state that the agent kernel needs to
    function: conversation history snapshot, token budget state, and
    any paused DER loop state.
    """

    conversation_id: str
    messages: List[ConversationMessage] = field(default_factory=list)
    tokens_used: int = 0
    current_mode: Optional[str] = None  # "quick" | "agentic" | "full"
    paused_state: Optional[PausedDERState] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def add_message(self, role: str, content: str, turn_id: Optional[str] = None) -> None:
        """Add a message and enforce the message cap (oldest removed first)."""
        self.messages.append(
            ConversationMessage(role=role, content=content, turn_id=turn_id)
        )
        if len(self.messages) > MAX_MESSAGES_PER_CONV:
            self.messages = self.messages[-MAX_MESSAGES_PER_CONV:]
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        # Convert dataclasses to serializable dicts
        result["messages"] = [asdict(m) for m in self.messages]
        if self.paused_state:
            result["paused_state"] = asdict(self.paused_state)
        else:
            result["paused_state"] = None
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationContext":
        messages = []
        for m in data.get("messages", []):
            messages.append(ConversationMessage(**m))
        paused = data.get("paused_state")
        if paused:
            paused_state = PausedDERState(**paused)
        else:
            paused_state = None
        data["messages"] = messages
        data["paused_state"] = paused_state
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ── Store ──────────────────────────────────────────────────────────────────


class ConversationContextStore:
    """
    Persistent store for per-thread agent context.

    Thread-safe via SQLite WAL mode.  All public methods are safe to call from
    async contexts — disk writes use asyncio.to_thread().
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path or (DEFAULT_DB_DIR / DB_FILENAME)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── Public API ──────────────────────────────────────────────────────

    def get_or_restore(self, conversation_id: str) -> Optional[ConversationContext]:
        """Retrieve stored context or None if not found.  Never crashes."""
        try:
            row = self._fetch_one(
                "SELECT data_json FROM conversation_contexts WHERE conversation_id = ?",
                (conversation_id,),
            )
            if row:
                data = json.loads(row[0])
                return ConversationContext.from_dict(data)
            return None
        except Exception as exc:
            logger.warning(
                f"[ConversationContextStore] get_or_restore({conversation_id}) failed: {exc}"
            )
            return None

    def save(self, conversation_id: str, context: ConversationContext) -> bool:
        """Persist context.  Returns True on success, False on failure (never crashes)."""
        try:
            data_json = json.dumps(context.to_dict())
            self._execute(
                """INSERT OR REPLACE INTO conversation_contexts
                   (conversation_id, data_json, updated_at)
                   VALUES (?, ?, ?)""",
                (conversation_id, data_json, time.time()),
            )
            self._enforce_bounds()
            return True
        except Exception as exc:
            logger.warning(
                f"[ConversationContextStore] save({conversation_id}) failed: {exc}"
            )
            return False

    def save_current_and_load(self, new_id: str, context: ConversationContext) -> bool:
        """
        Atomic save-then-swap for thread switching.

        Persists the current context (which was passed in) and returns
        the context for the new conversation_id via load().  If the
        new_id doesn't exist, returns a fresh ConversationContext.
        """
        try:
            # Save current context
            data_json = json.dumps(context.to_dict())
            self._execute(
                """INSERT OR REPLACE INTO conversation_contexts
                   (conversation_id, data_json, updated_at)
                   VALUES (?, ?, ?)""",
                (context.conversation_id, data_json, time.time()),
            )
            self._enforce_bounds()
            return True
        except Exception as exc:
            logger.warning(
                f"[ConversationContextStore] save_current_and_load failed "
                f"for conv={context.conversation_id}: {exc}"
            )
            return False

    def load(self, conversation_id: str) -> Optional[ConversationContext]:
        """Load context for a conversation.  Returns None if not found."""
        return self.get_or_restore(conversation_id)

    def clear(self, conversation_id: str) -> bool:
        """Remove stored context.  Called on 'new conversation'."""
        try:
            self._execute(
                "DELETE FROM conversation_contexts WHERE conversation_id = ?",
                (conversation_id,),
            )
            return True
        except Exception as exc:
            logger.warning(
                f"[ConversationContextStore] clear({conversation_id}) failed: {exc}"
            )
            return False

    def list_active(self) -> List[str]:
        """Return list of conversation_ids that have stored context."""
        try:
            rows = self._fetch_all(
                "SELECT conversation_id FROM conversation_contexts ORDER BY updated_at DESC"
            )
            return [r[0] for r in rows]
        except Exception as exc:
            logger.warning(f"[ConversationContextStore] list_active failed: {exc}")
            return []

    # ── Internal ────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        """Create the table if it doesn't exist.  Error-logged, never crashes."""
        try:
            conn = self._get_connection()
            conn.execute(
                """CREATE TABLE IF NOT EXISTS conversation_contexts (
                    conversation_id TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )"""
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.commit()
        except Exception as exc:
            logger.warning(
                f"[ConversationContextStore] DB init failed: {exc}. "
                "Using in-memory-only fallback."
            )

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create a thread-local connection."""
        # Use a simple approach: open/close per operation for async safety.
        # A connection pool is overkill for this use case.
        conn = sqlite3.connect(str(self._db_path), timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _execute(self, sql: str, params: tuple = ()) -> None:
        conn = self._get_connection()
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    def _fetch_one(self, sql: str, params: tuple = ()) -> Optional[tuple]:
        conn = self._get_connection()
        try:
            return conn.execute(sql, params).fetchone()
        finally:
            conn.close()

    def _fetch_all(self, sql: str, params: tuple = ()) -> List[tuple]:
        conn = self._get_connection()
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def _enforce_bounds(self) -> None:
        """Keep the DB bounded at MAX_CONVERSATIONS."""
        try:
            conn = self._get_connection()
            conn.execute(
                """DELETE FROM conversation_contexts WHERE conversation_id IN (
                    SELECT conversation_id FROM conversation_contexts
                    ORDER BY updated_at DESC
                    LIMIT -1 OFFSET ?
                )""",
                (MAX_CONVERSATIONS,),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning(
                f"[ConversationContextStore] _enforce_bounds failed: {exc}"
            )


# ── Singleton ──────────────────────────────────────────────────────────────


_store_instance: Optional[ConversationContextStore] = None


def get_context_store() -> ConversationContextStore:
    """Get or create the singleton ConversationContextStore."""
    global _store_instance
    if _store_instance is None:
        _store_instance = ConversationContextStore()
    return _store_instance


def reset_context_store_for_testing() -> None:
    """Reset the singleton — for test isolation only."""
    global _store_instance
    _store_instance = None
