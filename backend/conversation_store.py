"""Persistent conversation store for IRIS backend.

v2 (post-Domain 6.4): SQLite-backed persistence with in-memory hot cache.
Schema:
  conversations (id PK, title, created_at, updated_at, pinned,
                 parent_id, tags, reports_to, project_id)
  messages (id PK, conversation_id FK, role, text, turn_id, thinking, timestamp,
            sources, source)

Public API is unchanged from the previous in-memory version, but now
every mutation also writes to SQLite. On startup, load_from_db() populates
the in-memory cache from disk so conversations survive restarts.

DB location: _DB_PATH (defaults to data/conversations.db in the project root)
WAL mode: enabled for concurrent read/write safety.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
import uuid
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
            sources         TEXT,
            source          TEXT,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
    """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, timestamp)"
    )
    # Strands (owner decision 2026-10-06): a THREAD is the whole, each chat under
    # it is a STRAND, and a strand IS a conversation row - messages stay keyed by
    # conversation id. parent_id NULL = this row is a thread root (and its own
    # first strand); otherwise it holds the root's id. Added as nullable columns
    # so an existing store opens unchanged; each ALTER is guarded, so it is
    # idempotent.
    have = {r[1] for r in conn.execute("PRAGMA table_info(conversations)")}
    for col in ("parent_id", "tags", "reports_to", "project_id"):
        if col not in have:
            conn.execute(f"ALTER TABLE conversations ADD COLUMN {col} TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_parent ON conversations(parent_id)"
    )
    # Provenance (2026-10-08): the URLs a turn's references came from, persisted
    # so a LATER turn - and the planner - can see WHERE a reference lives. The
    # alternative was a bare `owner/name` token in the model's prose summary,
    # which reads like a local path: measured live, a GitHub repo was searched
    # for inside the project root for ~6 minutes. Guarded like the columns
    # above, so an existing store opens unchanged.
    _msg_cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
    # `sources` = the URLs a turn's references came from (provenance).
    # `source`  = which path persisted the turn (ws_text_message /
    #             ws_voice_transcription). BOTH were passed as kwargs and
    #             silently dropped by the six-column INSERT until 2026-10-08.
    for _col in ("sources", "source"):
        if _col not in _msg_cols:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {_col} TEXT")
    # Tool results (CLM Wave 2, owner decision 2026-11-12): the EXACT text of a node tool result
    # too long to stay in the model's window, so a placeholder can be expanded to the real bytes.
    # Deliberately NO foreign key to conversations: a dev_cli / eval turn can run in a conversation
    # id that has no row here (add_message returns None for such an id), and its results must still
    # be recorded. delete_conversation / truncate_conversation delete the rows explicitly instead.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tool_results (
            id              TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            turn_id         TEXT,
            step_id         TEXT,
            call_ord        INTEGER,
            tool            TEXT,
            target          TEXT,
            chars           INTEGER NOT NULL,
            cut             INTEGER NOT NULL DEFAULT 0,
            content         TEXT NOT NULL,
            created_at      TEXT NOT NULL
        )
    """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_results_conv ON tool_results(conversation_id, turn_id)"
    )


def _parse_sources(raw: Any) -> list[str]:
    """Decode a persisted ``sources`` column into a list of URLs.

    Never raises: an absent, malformed or non-list value is an empty list, so one
    bad row cannot stop a store load. A row written before this column existed
    simply has None.
    """
    if not raw:
        return []
    try:
        val = json.loads(raw)
    except Exception:  # noqa: BLE001 — a bad row must not break the load
        return []
    if isinstance(val, list):
        return [str(u) for u in val if u]
    return []


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
            "SELECT id, conversation_id, role, text, turn_id, thinking, timestamp, "
            "sources, source FROM messages ORDER BY id"
        ).fetchall():
            mid, cid, role, text, turn_id, thinking, timestamp, sources, source = row
            if cid in _conversations:
                _conversations[cid]["messages"].append(
                    {
                        "id": f"msg-{mid}",
                        "role": role,
                        "text": text,
                        "turn_id": turn_id,
                        "thinking": thinking,
                        "timestamp": timestamp,
                        "sources": _parse_sources(sources),
                        "source": source,
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
    sources: list[str] | None = None,
    **kwargs,
) -> dict[str, Any] | None:
    """Add a message to a conversation.

    ``sources`` - the URLs this turn's references came from - is persisted as a
    JSON array so a later turn can see WHERE a reference lives instead of
    re-deriving it from a summary. Structure carries what prose loses.

    Extra kwargs (turn_id, thinking, source, ...) are stored in the message
    dict. NOTE: only the columns listed in the INSERT below reach SQLite. This
    docstring used to claim every kwarg was persisted; the six-column INSERT
    silently dropped them all.
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
            "sources": list(sources) if sources else [],
            **kwargs,
        }
        conv["messages"].append(msg)
        conv["updated_at"] = timestamp
        # Persist to SQLite
        conn = _get_conn()
        conn.execute(
            "INSERT INTO messages (conversation_id, role, text, turn_id, thinking, "
            "timestamp, sources, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                role,
                text,
                kwargs.get("turn_id"),
                kwargs.get("thinking"),
                timestamp,
                json.dumps(sources) if sources else None,
                kwargs.get("source"),
            ),
        )
        # Update conversation's updated_at
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (timestamp, conversation_id),
        )
        return msg


# Tombstones (MEMORY-SURFACE-BUILD section 4 cases 1/2/8): titles live ONLY in this store, so
# when a conversation is deleted or renamed the memory is told, once per conversation, and
# keeps the title (STRAND_DELETED / STRAND_RENAMED in memory.db, on the memory_events lane).
_TOMBSTONE_TITLE_MAX = 300   # a payload is a bounded reference (memory_events._PAYLOAD_MAX)
_tombstones_lost = 0         # tombstones that could not be queued (read by tests and the health view)


def tombstones_lost() -> int:
    return _tombstones_lost


def _type_tombstone(label: str, conversation_id: str, payload: dict) -> bool:
    """Queue ONE tombstone on lane("memory_events"). Off the request path, bounded (the
    lane drops past its depth), never raises; a tombstone that is not queued is counted and
    logged. Only the memory interface the running app already holds is used - no memory
    store open means no memory to tell (counted all the same)."""
    global _tombstones_lost
    ok = False
    try:
        mem = sys.modules.get("backend.memory")
        mi = mem.get_memory_interface() if mem is not None else None
        if mi is not None:
            from backend.memory import memory_events

            ok = bool(memory_events.submit(
                mi, "record_strand_tombstone", label=label, thread_id=conversation_id, payload=payload,
            ))
    except Exception as exc:  # noqa: BLE001 - chat delete/rename never fails on the memory
        logger.warning("[conversation_store] tombstone failed label=%s conv=%s: %s",
                       label, conversation_id, exc)
    if not ok:
        _tombstones_lost += 1
        logger.warning("[conversation_store] tombstone not queued label=%s conv=%s (lost so far: %d)",
                       label, conversation_id, _tombstones_lost)
    return ok


_TOMBSTONE_SQL = """
SELECT c.id, c.title, c.parent_id, c.tags, c.reports_to,
       (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id)
FROM conversations c WHERE c.id = ? OR c.parent_id = ?
"""


def delete_conversation(conversation_id: str) -> bool:
    """Delete a conversation by ID (from both dict and SQLite). One STRAND_DELETED
    tombstone per deleted conversation (a root's strands included) keeps the titles."""
    global _tombstones_lost
    with _lock:
        if conversation_id not in _conversations:
            return False
        del _conversations[conversation_id]
        conn = _get_conn()
        gone = []
        try:
            gone = conn.execute(_TOMBSTONE_SQL, (conversation_id, conversation_id)).fetchall()
        except Exception as exc:  # noqa: BLE001 - the delete goes on; the loss is counted
            _tombstones_lost += 1
            logger.warning("[conversation_store] tombstone read failed conv=%s (lost so far: %d): %s",
                           conversation_id, _tombstones_lost, exc)
        # Deleting a thread root deletes its strands too (no orphan strands that
        # /api/threads can no longer reach).
        children = [r[0] for r in conn.execute(
            "SELECT id FROM conversations WHERE parent_id = ?", (conversation_id,)
        )]
        for cid in children:
            _conversations.pop(cid, None)
        # The tool results of the conversation (and of its strands) go in the SAME transaction as
        # the conversation row: tool_results has no foreign key (see _create_tables), so nothing
        # else would ever remove them.
        conn.execute("BEGIN")
        try:
            marks = ",".join("?" * (1 + len(children)))
            conn.execute(
                f"DELETE FROM tool_results WHERE conversation_id IN ({marks})",
                (conversation_id, *children),
            )
            conn.execute(
                "DELETE FROM conversations WHERE id = ? OR parent_id = ?",
                (conversation_id, conversation_id),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        # CASCADE in the schema deletes messages too
    at = time.time()
    for cid, title, parent_id, tags, reports_to, message_count in gone:
        _type_tombstone("STRAND_DELETED", cid, {
            "title": (title or "")[:_TOMBSTONE_TITLE_MAX], "parent_id": parent_id,
            "tags": _load_tags(tags), "reports_to": reports_to,
            "message_count": message_count, "at": at,
        })
    return True


def update_conversation_title(conversation_id: str, title: str) -> bool:
    """Update the title of a conversation. A changed title leaves one STRAND_RENAMED
    tombstone (the old title stays searchable in the memory)."""
    with _lock:
        conv = _conversations.get(conversation_id)
        if not conv:
            return False
        old_title = conv["title"]
        conv["title"] = title
        conv["updated_at"] = _now()
        conn = _get_conn()
        conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, conv["updated_at"], conversation_id),
        )
    if title != old_title:
        _type_tombstone("STRAND_RENAMED", conversation_id, {
            "old_title": (old_title or "")[:_TOMBSTONE_TITLE_MAX],
            "new_title": (title or "")[:_TOMBSTONE_TITLE_MAX], "at": time.time(),
        })
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

        # A turn is removed only when NONE of its messages is kept: a turn cut in the middle keeps
        # its tool results. Messages without a turn_id match nothing.
        _kept_turns = {m.get("turn_id") for m in messages[: keep_idx + 1] if m.get("turn_id")}
        _gone_turns = sorted(
            {m.get("turn_id") for m in messages[keep_idx + 1 :] if m.get("turn_id")} - _kept_turns
        )

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
        if _gone_turns:
            conn.execute(
                "DELETE FROM tool_results WHERE conversation_id = ? AND turn_id IN (%s)"
                % ",".join("?" * len(_gone_turns)),
                (conversation_id, *_gone_turns),
            )

        return {"truncated": True, "kept_messages": len(messages)}



# ── Tool results: the exact text behind a placeholder (CLM Wave 2) ───────────────────────────────
# A node tool result longer than what later steps keep (NODE_BLOCK_HEAD = 2,500 chars) is recorded
# here in full, so a "set aside" placeholder can carry this id and the real bytes come back by id.
#
# The write is QUEUED on the ordered lane "tool_results" (utils/durability_queue.lane): the node loop
# never waits on SQLite. The caller mints the id first (new_tool_result_id) so the placeholder can
# carry it before the row exists; get_tool_result waits for THAT id's write, bounded.
#
# Growth budget (measured 2026-11-15; arithmetic in the report that introduced this block):
#   * Row size. logs/clm_dumps_before holds 157 distinct node tool messages from 8 conversations -
#     already clipped to the model's 8,000 chars (p50 1,805, p90 7,108, p99 8,026, max 8,027; 2.5%
#     hit the clip). The record keeps the text BEFORE that clip, so the real tail is longer: the
#     nearest measurable proxy for a read_file in developer mode is the size of the backend's own
#     source files (447 files: p50 9.6k, p90 45k, 93.1% <= 64k, 96.4% <= 100k, 97.8% <= 128k,
#     99.3% <= 200k, max 607k). 128,000 keeps every measured model-visible result and 97.8% of
#     source files whole; a longer text is stored cut (cut=1, chars = the original length).
TOOL_RESULT_MAX_CHARS = 128_000
#   * Rows per conversation. A whole DER run is one turn; the cohort makes a median 18.5 and a
#     maximum 38 node tool calls per run (8 conversations), and 28.7% of results exceed 2,500 chars,
#     i.e. about 11 stored rows in the largest run. 200 rows = 18 such maximum runs; past it the
#     OLDEST rows go in the same write job (counted as `evicted`).
TOOL_RESULTS_PER_CONVERSATION = 200
#   * Worst case per conversation: 200 x 128,000 = 25.6 M chars (about 25.6 MB of ASCII text; up
#     to 3x for non-ASCII). Typical: 200 x ~7k = 1.4 MB. The whole store is bounded by the number
#     of conversations x that, and rows leave with their conversation, so no store-wide budget.
#   * Only a result longer than this is recorded (shorter ones stay whole in the step result).
TOOL_RESULT_MIN_CHARS = 2_500

_TR_LANE = "tool_results"
_tr_lock = threading.Lock()
_tr_pending: dict[str, threading.Event] = {}   # id -> set when its write job ends (written or not)
_tr_stats = {
    "queued": 0, "written": 0, "refused": 0, "write_failed": 0,
    "cut": 0, "evicted": 0, "skipped_small": 0,
}


def _tr_lane():
    from backend.utils import durability_queue

    return durability_queue.lane(_TR_LANE)


def _tr_count(key: str, n: int = 1) -> None:
    with _tr_lock:
        _tr_stats[key] += n


def new_tool_result_id() -> str:
    """A fresh tool-result id (uuid4 hex). No I/O."""
    return uuid.uuid4().hex


def tool_result_stats() -> dict[str, int]:
    """Counters since import (reload resets them) plus the jobs still queued."""
    with _tr_lock:
        out = dict(_tr_stats)
        out["pending"] = len(_tr_pending)
    return out


def _write_tool_result(
    done: threading.Event, row: tuple, conversation_id: str, was_cut: bool
) -> None:
    """The lane job: insert one row, then trim the conversation to its row cap. Runs on the lane
    thread under the module's connection lock; every failure is logged with the conversation id
    and counted, and the waiter is always released."""
    try:
        with _lock:
            conn = _get_conn()
            conn.execute("BEGIN")
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO tool_results (id, conversation_id, turn_id, step_id, "
                    "call_ord, tool, target, chars, cut, content, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    row,
                )
                over = conn.execute(
                    "SELECT COUNT(*) FROM tool_results WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()[0] - TOOL_RESULTS_PER_CONVERSATION
                evicted = 0
                if over > 0:
                    evicted = conn.execute(
                        "DELETE FROM tool_results WHERE rowid IN (SELECT rowid FROM tool_results "
                        "WHERE conversation_id = ? ORDER BY rowid ASC LIMIT ?)",
                        (conversation_id, over),
                    ).rowcount
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        _tr_count("written")
        if was_cut:
            _tr_count("cut")
        if evicted:
            _tr_count("evicted", evicted)
    except Exception as exc:  # noqa: BLE001 - a record write never fails the task that made it
        _tr_count("write_failed")
        logger.warning("[conversation_store] tool result write failed conv=%s id=%s: %s",
                       conversation_id, row[0], exc)
    finally:
        with _tr_lock:
            _tr_pending.pop(row[0], None)
        done.set()


def add_tool_result(
    result_id: str,
    conversation_id: str,
    turn_id: str | None,
    step_id: str | None,
    call_ord: int | None,
    tool: str | None,
    target: str | None,
    content: str,
) -> bool:
    """QUEUE the write of one tool result and return at once.

    True = queued (it will be readable by get_tool_result shortly). False = not recorded: the text
    is not longer than TOOL_RESULT_MIN_CHARS (counted `skipped_small`), the ids are missing, or the
    lane refused it because its queue is full (counted `refused`, logged). Never raises, never
    blocks, never touches SQLite on the calling thread."""
    try:
        text = content if isinstance(content, str) else ("" if content is None else str(content))
        if not result_id or not conversation_id:
            _tr_count("refused")
            logger.warning("[conversation_store] tool result refused: missing id conv=%s id=%s",
                           conversation_id, result_id)
            return False
        if len(text) <= TOOL_RESULT_MIN_CHARS:
            _tr_count("skipped_small")
            return False
        was_cut = len(text) > TOOL_RESULT_MAX_CHARS
        row = (
            result_id, conversation_id, turn_id, step_id,
            None if call_ord is None else int(call_ord), tool, target,
            len(text), 1 if was_cut else 0, text[:TOOL_RESULT_MAX_CHARS], _now(),
        )
        done = threading.Event()
        with _tr_lock:
            _tr_pending[result_id] = done
        if not _tr_lane().submit("tool_result", _write_tool_result, done, row, conversation_id, was_cut):
            with _tr_lock:
                _tr_pending.pop(result_id, None)
                _tr_stats["refused"] += 1
            logger.warning("[conversation_store] tool result refused (lane queue full) conv=%s id=%s",
                           conversation_id, result_id)
            return False
        _tr_count("queued")
        return True
    except Exception as exc:  # noqa: BLE001
        with _tr_lock:
            _tr_pending.pop(result_id, None)
        _tr_count("refused")
        logger.warning("[conversation_store] add_tool_result failed conv=%s id=%s: %s",
                       conversation_id, result_id, exc)
        return False


_TR_COLS = ("id", "conversation_id", "turn_id", "step_id", "call_ord", "tool", "target",
            "chars", "cut", "content", "created_at")


def _read_tool_result(result_id: str) -> dict[str, Any] | None:
    with _lock:
        row = _get_conn().execute(
            "SELECT " + ", ".join(_TR_COLS) + " FROM tool_results WHERE id = ?", (result_id,)
        ).fetchone()
    if row is None:
        return None
    out = dict(zip(_TR_COLS, row))
    out["cut"] = int(out["cut"])
    return out


def get_tool_result(result_id: str, wait_s: float = 2.0) -> dict[str, Any] | None:
    """One recorded tool result (all columns, content included), or None.

    If the row is not there yet and ITS write is still queued, wait for that write - at most
    wait_s - and read again. The wait is on the id's own completion event, not on lane.flush()
    (flush waits for the whole queue and takes a queue slot, and is documented for tests and
    shutdown only). The connection lock is never held while waiting: the write job needs it.
    Never raises; None when absent, or when the bound ran out."""
    try:
        with _tr_lock:
            done = _tr_pending.get(result_id)
        row = _read_tool_result(result_id)
        if row is not None:
            return row
        if done is not None and not _tr_lane().in_worker():
            done.wait(max(0.0, wait_s))
            return _read_tool_result(result_id)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[conversation_store] get_tool_result failed id=%s: %s", result_id, exc)
        return None


def tool_results_for_turn(conversation_id: str, turn_id: str | None) -> list[dict[str, Any]]:
    """The recorded results of one turn, WITHOUT their content, ordered by step_id then call_ord.
    Only rows already committed are listed. Never raises."""
    cols = [c for c in _TR_COLS if c != "content"]
    try:
        with _lock:
            rows = _get_conn().execute(
                "SELECT " + ", ".join(cols) + " FROM tool_results "
                "WHERE conversation_id = ? AND turn_id IS ? ORDER BY step_id, call_ord, rowid",
                (conversation_id, turn_id),
            ).fetchall()
        return [dict(zip(cols, r)) for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[conversation_store] tool_results_for_turn failed conv=%s turn=%s: %s",
                       conversation_id, turn_id, exc)
        return []

# ── Threads and strands ────────────────────────────────────────────────────
# A thread = a root conversation (parent_id NULL) + the rows whose parent_id is
# the root. These functions read SQLite directly and never return message bodies
# (the thread list must not download every message - measured lag, 2026-10-06).

MAX_TAGS = 8
MAX_TAG_LEN = 24
PREVIEW_LEN = 80


def normalize_tags(tags: list[str] | None) -> list[str]:
    """Trim, lowercase, drop blanks and duplicates. Raises ValueError when the
    result is over the bound (<= MAX_TAGS tags, <= MAX_TAG_LEN chars each) - an
    over-long tag is refused, never silently cut."""
    out: list[str] = []
    for t in tags or []:
        t = str(t).strip().lower()
        if not t or t in out:
            continue
        if len(t) > MAX_TAG_LEN:
            raise ValueError(f"tag longer than {MAX_TAG_LEN} characters: {t[:MAX_TAG_LEN]}...")
        out.append(t)
    if len(out) > MAX_TAGS:
        raise ValueError(f"more than {MAX_TAGS} tags")
    return out


def _load_tags(raw: str | None) -> list[str]:
    try:
        v = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [t for t in v if isinstance(t, str)] if isinstance(v, list) else []


def thread_root_of(conversation_id: str) -> str:
    """Return the id of the thread root that owns ``conversation_id``.

    A root (parent_id NULL), an unknown id, or an orphan whose root is gone all
    resolve to the id itself. This is the ONE resolver for "which memory does
    this strand share" - every strand of a thread resolves to the same value.
    """
    with _lock:
        row = _get_conn().execute(
            "SELECT parent_id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
    return row[0] if row and row[0] else conversation_id


def is_thread_root(conversation_id: str) -> bool:
    with _lock:
        row = _get_conn().execute(
            "SELECT parent_id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
    return row is not None and row[0] is None


# One query, indexed: idx_conversations_parent finds each root's children,
# idx_messages_conv counts/reads messages without touching a message body except
# the single newest one per thread (for the preview).
_THREAD_LIST_SQL = """
SELECT c.id, c.title, c.pinned,
       MAX(c.updated_at, COALESCE(
           (SELECT MAX(s.updated_at) FROM conversations s WHERE s.parent_id = c.id), '')),
       1 + (SELECT COUNT(*) FROM conversations s WHERE s.parent_id = c.id),
       (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id)
         + (SELECT COUNT(*) FROM messages m WHERE m.conversation_id IN
              (SELECT s.id FROM conversations s WHERE s.parent_id = c.id)),
       (SELECT substr(m2.text, 1, 400) FROM messages m2
         WHERE m2.conversation_id IN
               (SELECT c.id UNION ALL SELECT s.id FROM conversations s WHERE s.parent_id = c.id)
         ORDER BY m2.timestamp DESC LIMIT 1)
FROM conversations c
WHERE c.parent_id IS NULL
ORDER BY c.pinned DESC, 4 DESC
"""


def list_threads() -> list[dict[str, Any]]:
    """Thread summaries, pinned first then newest. No message bodies."""
    with _lock:
        rows = _get_conn().execute(_THREAD_LIST_SQL).fetchall()
    return [
        {
            "id": cid,
            "title": title,
            "pinned": bool(pinned),
            "updated_at": updated_at,
            "strand_count": strand_count,
            "message_count": message_count,
            "last_preview": " ".join((last_text or "").split())[:PREVIEW_LEN],
        }
        for cid, title, pinned, updated_at, strand_count, message_count, last_text in rows
    ]


_STRAND_SQL = """
SELECT c.id, c.title, c.tags, c.reports_to, c.updated_at,
       (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id)
FROM conversations c
WHERE {where}
ORDER BY c.created_at, c.id
"""


def _strand_dict(row: tuple) -> dict[str, Any]:
    sid, title, tags, reports_to, updated_at, message_count = row
    return {
        "id": sid,
        "title": title,
        "tags": _load_tags(tags),
        "reports_to": reports_to,
        "updated_at": updated_at,
        "message_count": message_count,
    }


def list_strands(thread_id: str) -> list[dict[str, Any]] | None:
    """The root and its children, oldest first. None when ``thread_id`` is not a
    thread root."""
    with _lock:
        if not is_thread_root(thread_id):
            return None
        rows = _get_conn().execute(
            _STRAND_SQL.format(where="c.id = ? OR c.parent_id = ?"), (thread_id, thread_id)
        ).fetchall()
    return [_strand_dict(r) for r in rows]


def get_strand(strand_id: str) -> dict[str, Any] | None:
    with _lock:
        row = _get_conn().execute(
            _STRAND_SQL.format(where="c.id = ?"), (strand_id,)
        ).fetchone()
    return _strand_dict(row) if row else None


def create_strand(
    thread_id: str,
    name: str,
    tags: list[str] | None = None,
    reports_to: str | None = None,
) -> dict[str, Any]:
    """Create a strand (a conversation with parent_id = the thread root).

    The id is ``strand-<12 hex>`` (48 random bits - no collision loop, and no
    import of the agent package just to name a row). Raises ValueError for an
    unknown thread, bad tags, or a ``reports_to`` that is not a strand of the same
    thread.
    """
    clean = normalize_tags(tags)
    with _lock:
        if not is_thread_root(thread_id):
            raise ValueError(f"thread {thread_id} not found")
        if reports_to is not None and thread_root_of(reports_to) != thread_id:
            raise ValueError(f"reports_to {reports_to} is not a strand of thread {thread_id}")
        strand_id = f"strand-{uuid.uuid4().hex[:12]}"
        create_conversation(title=name, conv_id=strand_id)
        _get_conn().execute(
            "UPDATE conversations SET parent_id = ?, tags = ?, reports_to = ? WHERE id = ?",
            (thread_id, json.dumps(clean), reports_to, strand_id),
        )
    return get_strand(strand_id)  # type: ignore[return-value]


REPORT_SOURCE = "strand_report:"   # messages.source of a helper's report in its parent strand (+ the helper's id)


def report_back(strand_id: str, text: str | None = None) -> dict[str, Any] | None:
    """A helper strand reports back: its result becomes a message in the strand it reports to.

    ``text`` defaults to the helper's newest IRIS answer. The message's ``source`` is
    ``REPORT_SOURCE + strand_id``, so its timestamp IS the moment the helper reported
    (the memory surface reads it). None when the strand does not exist; ValueError when
    it is not a helper (no ``reports_to``) or there is nothing to report.
    """
    strand = get_strand(strand_id)
    if strand is None:
        return None
    parent = strand.get("reports_to")
    if not parent:
        raise ValueError(f"strand {strand_id} is not a helper (it reports to no strand)")
    if text is None or not text.strip():
        conv = get_conversation(strand_id) or {}
        answers = [m.get("text") or "" for m in conv.get("messages", []) if m.get("role") != "user"]
        text = next((t for t in reversed(answers) if t.strip()), "")
    if not text.strip():
        raise ValueError(f"strand {strand_id} has nothing to report yet")
    body = f"Report from the helper strand \u201c{strand.get('title') or strand_id}\u201d:\n\n{text.strip()}"
    msg = add_message(parent, "assistant", body, source=REPORT_SOURCE + strand_id)
    if msg is None:
        raise ValueError(f"the strand {parent} that {strand_id} reports to no longer exists")
    return {"parent": parent, "message": msg}


def update_strand(
    strand_id: str, name: str | None = None, tags: list[str] | None = None
) -> dict[str, Any] | None:
    """Rename and/or retag a strand. None when it does not exist."""
    clean = normalize_tags(tags) if tags is not None else None
    with _lock:
        if strand_id not in _conversations:
            return None
        if name is not None:
            update_conversation_title(strand_id, name)
        if clean is not None:
            _get_conn().execute(
                "UPDATE conversations SET tags = ? WHERE id = ?",
                (json.dumps(clean), strand_id),
            )
    return get_strand(strand_id)


def update_thread(
    thread_id: str, title: str | None = None, pinned: bool | None = None
) -> bool:
    """Rename and/or (un)pin a thread root. False when it is not a thread root."""
    with _lock:
        if not is_thread_root(thread_id):
            return False
        if title is not None:
            update_conversation_title(thread_id, title)
        if pinned is not None:
            conv = _conversations[thread_id]
            conv["pinned"] = bool(pinned)
            conv["updated_at"] = _now()
            _get_conn().execute(
                "UPDATE conversations SET pinned = ?, updated_at = ? WHERE id = ?",
                (1 if pinned else 0, conv["updated_at"], thread_id),
            )
    return True
