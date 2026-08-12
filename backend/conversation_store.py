"""Persistent conversation store for IRIS backend.

v2 (post-Domain 6.4): SQLite-backed persistence with in-memory hot cache.
Schema:
  conversations (id PK, title, created_at, updated_at, pinned)
  messages (id PK, conversation_id FK, role, text, turn_id, thinking, timestamp)

Public API is unchanged from the previous in-memory version, but now
every mutation also writes to SQLite. On startup, load_from_db() populates
the in-memory cache from disk so conversations survive restarts.

DB location: _DB_PATH (defaults to data/conversations.db in the project root)
WAL mode: enabled for concurrent read/write safety.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# In-memory hot cache (the dict is the primary read path; SQLite is the
# persistence layer). The cache is rebuilt from DB on load_from_db().
_conversations: dict[str, dict[str, Any]] = {}
# Highest "conv-N" suffix issued. Seeded from the persisted store by
# load_from_db() — see the note there for what leaving it at 0 across a restart
# actually did.
_counter = 0
_CONV_ID_RE = re.compile(r"conv-(\d+)")
_lock = threading.RLock()

# Database path — can be overridden via the IRIS_CONVERSATIONS_DB env var
# PATH FIX: this file is backend/conversation_store.py, so reaching the project
# root takes TWO dirname() calls (backend/ -> repo root). It had THREE, which
# resolved to the PARENT of the repo — every conversation and message was being
# written to C:\dev\data\conversations.db, outside the project entirely, while
# the in-repo stores sat empty (0 rows). Measured before the fix: 332
# conversations / 353 messages in the out-of-tree file. The docstring at the top
# of this module always said "data/conversations.db in the project root"; the
# code simply did not agree with it.
#
# Same defect shape as the backend/data/memory.db stray: a relative path
# resolved from __file__ with one level too many. Anchor it explicitly and name
# the intent so the next edit cannot silently re-break it.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DB_PATH = os.path.join(_REPO_ROOT, "data", "conversations.db")
_DB_PATH = os.environ.get("IRIS_CONVERSATIONS_DB", _DEFAULT_DB_PATH)
_conn: sqlite3.Connection | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_data_dir() -> None:
    """Create the data directory if it doesn't exist."""
    db_dir = os.path.dirname(_DB_PATH)
    if db_dir and not os.path.isdir(db_dir):
        os.makedirs(db_dir, exist_ok=True)


def _get_conn() -> sqlite3.Connection:
    """Get (or create) the SQLite connection. Thread-safe via lock.

    Enables WAL mode and foreign keys on first call. Reuses the same
    connection across calls (SQLite is fine with this for a single
    process; the connection is check_same_thread=False).
    """
    global _conn
    with _lock:
        if _conn is None:
            _ensure_data_dir()
            _conn = sqlite3.connect(
                _DB_PATH, check_same_thread=False, isolation_level=None
            )
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA foreign_keys=ON")
            _create_tables(_conn)
        return _conn


def _create_tables(conn: sqlite3.Connection) -> None:
    """Create the conversations and messages tables if they don't exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            pinned      INTEGER NOT NULL DEFAULT 0
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role            TEXT NOT NULL,
            text            TEXT NOT NULL,
            turn_id         TEXT,
            thinking        TEXT,
            timestamp       TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
    """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, timestamp)"
    )


def load_from_db() -> None:
    """Reload all conversations and messages from SQLite into the in-memory cache.

    Call this at backend startup so conversations persist across restarts.
    Tests call it to simulate a restart (clear in-memory, reload from disk).

    Restores ``_counter`` as well as the conversations. Reloading the threads but
    NOT the counter is what made every backend restart start issuing "conv-1"
    again: the id already existed with 15 messages behind it, so the first new
    conversation of each run was handed an OLD thread. The user's prompt landed
    in a previous conversation, that conversation's documents rehydrated
    alongside it, and the frontend rendered two entries with the same id
    ("Encountered two children with the same key, `conv-1`"). One unrestored
    global, three symptoms.
    """
    global _counter
    with _lock:
        conn = _get_conn()
        _conversations.clear()
        for row in conn.execute(
            "SELECT id, title, created_at, updated_at, pinned FROM conversations"
        ).fetchall():
            cid, title, created_at, updated_at, pinned = row
            _conversations[cid] = {
                "id": cid,
                "title": title,
                "created_at": created_at,
                "updated_at": updated_at,
                "pinned": bool(pinned),
                "messages": [],
            }
        for row in conn.execute(
            "SELECT id, conversation_id, role, text, turn_id, thinking, timestamp "
            "FROM messages ORDER BY id"
        ).fetchall():
            mid, cid, role, text, turn_id, thinking, timestamp = row
            if cid in _conversations:
                _conversations[cid]["messages"].append(
                    {
                        "id": f"msg-{mid}",
                        "role": role,
                        "text": text,
                        "turn_id": turn_id,
                        "thinking": thinking,
                        "timestamp": timestamp,
                    }
                )

        # Resume the auto-id sequence past every "conv-N" already on disk.
        # Derived from the ids themselves rather than from a stored counter, so
        # it is self-correcting: it cannot drift out of step with the data, and
        # it still holds for a store whose ids were minted before this existed.
        _highest = 0
        for _cid in _conversations:
            _m = _CONV_ID_RE.fullmatch(_cid)
            if _m:
                _highest = max(_highest, int(_m.group(1)))
        _counter = _highest
        logger.info(
            "[conversation_store] loaded %d conversations; auto-id counter resumes at %d",
            len(_conversations), _counter + 1,
        )


# Auto-load on import so existing conversations are available immediately
try:
    load_from_db()
except Exception:
    # If the DB doesn't exist yet (first run), _get_conn will create it
    pass


def create_conversation(
    title: str | None = None, conv_id: str | None = None
) -> dict[str, Any]:
    """Create a new conversation and return it.

    Args:
        title: Human-readable title. Defaults to "Conversation N".
        conv_id: Optional caller-supplied ID. If None, auto-generates
            "conv-N". When supplied (e.g., for Immortus threads), the
            caller controls the ID.
    """
    global _counter
    with _lock:
        if conv_id is None:
            # Skip ids already taken. `_counter` is seeded from the store on
            # load, but a store written before that seeding existed — or one
            # holding ids minted by another path — can still collide, and a
            # collision here is not cosmetic: it hands the caller a thread that
            # already has messages in it.
            _counter += 1
            conv_id = f"conv-{_counter}"
            while conv_id in _conversations:
                logger.warning(
                    "[conversation_store] auto id %s is already taken — skipping. "
                    "A new conversation must never be handed an existing thread.",
                    conv_id,
                )
                _counter += 1
                conv_id = f"conv-{_counter}"
        elif conv_id in _conversations:
            # Idempotent: return existing conversation
            return _conversations[conv_id]
        if conv_id in _conversations:
            # Belt-and-braces: never REPLACE a cached conversation with an empty
            # one. That is what merged threads even when the DB row survived —
            # `INSERT OR IGNORE` kept the row, but the cache entry (and with it
            # the loaded message list) was overwritten, so the existing thread
            # looked empty and the new turn appended into it.
            return _conversations[conv_id]
        conv = {
            "id": conv_id,
            # Was `_counter + 1`, which named the NEXT conversation rather than
            # this one — "conv-7" was titled "Conversation 8".
            "title": title or f"Conversation {_counter}",
            "created_at": _now(),
            "updated_at": _now(),
            "messages": [],
            "pinned": False,
        }
        _conversations[conv_id] = conv
        # Persist to SQLite
        conn = _get_conn()
        conn.execute(
            "INSERT OR IGNORE INTO conversations (id, title, created_at, updated_at, pinned) "
            "VALUES (?, ?, ?, ?, ?)",
            (conv_id, conv["title"], conv["created_at"], conv["updated_at"], 0),
        )
        return conv


def get_conversations() -> list[dict[str, Any]]:
    """Return all conversations sorted by updated_at (most recent first), pinned first."""
    with _lock:
        convs = list(_conversations.values())
    convs.sort(key=lambda c: (c["pinned"], c["updated_at"]), reverse=True)
    return convs


def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    """Return a single conversation by ID (returns a deep copy)."""
    with _lock:
        conv = _conversations.get(conversation_id)
    if conv is None:
        return None
    # Return a deep copy to prevent callers from mutating the cache
    import copy

    return copy.deepcopy(conv)


def add_message(
    conversation_id: str,
    role: str,
    text: str,
    **kwargs,
) -> dict[str, Any] | None:
    """Add a message to a conversation.

    Extra kwargs (turn_id, thinking, etc.) are stored verbatim in the
    message dict and in the SQLite messages table.
    """
    with _lock:
        conv = _conversations.get(conversation_id)
        if not conv:
            return None
        # Compute the next message id
        next_id = len(conv["messages"]) + 1
        timestamp = _now()
        msg = {
            "id": f"msg-{next_id}",
            "role": role,
            "text": text,
            "timestamp": timestamp,
            **kwargs,
        }
        conv["messages"].append(msg)
        conv["updated_at"] = timestamp
        # Persist to SQLite
        conn = _get_conn()
        conn.execute(
            "INSERT INTO messages (conversation_id, role, text, turn_id, thinking, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                role,
                text,
                kwargs.get("turn_id"),
                kwargs.get("thinking"),
                timestamp,
            ),
        )
        # Update conversation's updated_at
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (timestamp, conversation_id),
        )
        return msg


def delete_conversation(conversation_id: str) -> bool:
    """Delete a conversation by ID (from both dict and SQLite)."""
    with _lock:
        if conversation_id not in _conversations:
            return False
        del _conversations[conversation_id]
        conn = _get_conn()
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        # CASCADE in the schema deletes messages too
        return True


def update_conversation_title(conversation_id: str, title: str) -> bool:
    """Update the title of a conversation."""
    with _lock:
        conv = _conversations.get(conversation_id)
        if not conv:
            return False
        conv["title"] = title
        conv["updated_at"] = _now()
        conn = _get_conn()
        conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, conv["updated_at"], conversation_id),
        )
        return True


def toggle_pin_conversation(conversation_id: str) -> bool:
    """Toggle the pinned status of a conversation."""
    with _lock:
        conv = _conversations.get(conversation_id)
        if not conv:
            return False
        conv["pinned"] = not conv["pinned"]
        conv["updated_at"] = _now()
        conn = _get_conn()
        conn.execute(
            "UPDATE conversations SET pinned = ?, updated_at = ? WHERE id = ?",
            (1 if conv["pinned"] else 0, conv["updated_at"], conversation_id),
        )
        return True


def truncate_conversation(
    conversation_id: str, keep_until_message_id: str
) -> dict[str, Any]:
    """Delete all messages after `keep_until_message_id` in a conversation.

    Returns ``{"truncated": True, "kept_messages": N}`` on success,
    or raises a ``ValueError`` if the conversation or message is not found.
    """
    with _lock:
        conv = _conversations.get(conversation_id)
        if not conv:
            raise ValueError(f"Conversation {conversation_id} not found")

        messages = conv["messages"]
        # Find the index of the message to keep until
        keep_idx = next(
            (i for i, m in enumerate(messages) if m["id"] == keep_until_message_id),
            None,
        )
        if keep_idx is None:
            raise ValueError(
                f"Message {keep_until_message_id} not found in "
                f"conversation {conversation_id}"
            )

        # Nothing to truncate if this is the last message
        if keep_idx >= len(messages) - 1:
            return {"truncated": True, "kept_messages": len(messages)}

        # Remove from in-memory cache
        del messages[keep_idx + 1 :]
        conv["updated_at"] = _now()

        # Remove from SQLite
        conn = _get_conn()
        keep_msg_id_int = keep_idx + 1  # msg-N where N is 1-indexed
        conn.execute(
            "DELETE FROM messages WHERE conversation_id = ? "
            "AND CAST(REPLACE(id, 'msg-', '') AS INTEGER) > ?",
            (conversation_id, keep_msg_id_int),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (conv["updated_at"], conversation_id),
        )

        return {"truncated": True, "kept_messages": len(messages)}
