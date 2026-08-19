#!/usr/bin/env python3
"""
ConversationContextStore — Persistent per-thread agent context.

Keys agent context by conversation_id so switching threads or surviving a WS
disconnect preserves the agent's state.  Bounded (max 50 convs, 200 msgs each).

Also persists task CARD state (REQ-4 AC1), keyed by card_id and scoped to
its conversation — a separate table (conversation_cards) from the message
snapshot, upserted the same way document_store.py upserts document_data.
Cards follow the same bound as messages and evict with their conversation.

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
import threading
import time
import uuid
from collections import OrderedDict
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
class CardStepSnapshot:
    """One step's persisted state within a task card (REQ-4 AC1)."""

    id: str
    description: str
    status: str
    tool_name: Optional[str] = None


# Terminal states a persisted card can settle into. "running" is the only
# NON-terminal value; every card starts there and moves to one of these
# three when the process that owns it observes the card stop moving.
CARD_STATE_RUNNING = "running"
CARD_TERMINAL_STATES = {"done", "fail", "terminated_unknown"}


@dataclass
class CardState:
    """Persisted snapshot of a task card (REQ-4 AC1), scoped to its
    conversation (AC3: a card must never appear in a conversation it was
    not created in).

    Deliberately a SEPARATE record from ``ConversationMessage`` rather than
    a field bolted onto it — mirrors the shape ``document_store.py`` already
    uses for rich documents (a dedicated table keyed by the entity's own id,
    upserted idempotently), which is the working precedent for this kind of
    "renders independently of the message stream" state. ``ConversationMessage``
    stays exactly {role, content, timestamp, turn_id}.
    """

    card_id: str
    conversation_id: str
    card_relation: str = "new"  # "new" | "continues"
    plan_title: Optional[str] = None
    mode: Optional[str] = None
    steps: List[CardStepSnapshot] = field(default_factory=list)
    current_step: int = 0
    total_steps: int = 0
    # AC5: restored as "terminated_unknown" if still "running" on read —
    # see ConversationContextStore.get_cards_for_conversation().
    terminal_state: str = CARD_STATE_RUNNING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["steps"] = [asdict(s) for s in self.steps]
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CardState":
        steps = [CardStepSnapshot(**s) for s in data.get("steps", [])]
        data = {**data, "steps": steps}
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


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
            # Cards follow the conversation's own lifecycle — a cleared
            # conversation must not leave orphaned cards a later conversation
            # could never reach (AC3: cards are scoped to conversation_id).
            self._execute(
                "DELETE FROM conversation_cards WHERE conversation_id = ?",
                (conversation_id,),
            )
            return True
        except Exception as exc:
            logger.warning(
                f"[ConversationContextStore] clear({conversation_id}) failed: {exc}"
            )
            return False

    # ── Card state (REQ-4 AC1/AC3/AC5) ─────────────────────────────────

    def save_card(self, card: CardState) -> bool:
        """Upsert a card's persisted state, scoped to ``card.conversation_id``.

        Duplicate ``card_id`` updates the existing row rather than creating a
        second one (same upsert shape as ``document_store.store()``).
        ``created_at`` is preserved across updates — only set on first insert.

        Never raises: a failed card write must not block execution or a
        user response (T4/T5 shared rule) — logged and returns False.
        """
        try:
            data_json = json.dumps(card.to_dict())
            now = time.time()
            conn = self._get_connection()
            try:
                conn.execute(
                    """INSERT INTO conversation_cards
                       (card_id, conversation_id, data_json, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(card_id) DO UPDATE SET
                           conversation_id = excluded.conversation_id,
                           data_json = excluded.data_json,
                           updated_at = excluded.updated_at""",
                    (card.card_id, card.conversation_id, data_json, card.created_at, now),
                )
                conn.commit()
            finally:
                conn.close()
            self._enforce_card_bounds(card.conversation_id)
            return True
        except Exception as exc:
            logger.warning(
                f"[ConversationContextStore] save_card(card_id={card.card_id}, "
                f"conversation_id={card.conversation_id}) failed: {exc}"
            )
            return False

    def get_cards_for_conversation(self, conversation_id: str) -> List[CardState]:
        """Return every card for a conversation, oldest first (REQ-4 AC1/AC3).

        AC5: a card whose stored ``terminal_state`` is still "running" means
        the process that owned it never reached the write path that would
        have marked it done/fail — it was cut off mid-execution (crash,
        disconnect, navigate-away). Resolved to "terminated_unknown" HERE, on
        READ, rather than at write/shutdown time: a crash never gets a turn
        to run a shutdown-time write, so read-time is the only place this
        transform is guaranteed to run. The stored row itself is left
        untouched — only the returned snapshot is corrected — so a later,
        legitimate task:done for the same card_id can still land normally.

        Never raises: a broken store degrades to "no cards" (empty list)
        rather than blocking conversation load. A single corrupt row is
        skipped (never rendered as a partial card) without failing the rest.
        """
        try:
            rows = self._fetch_all(
                "SELECT data_json FROM conversation_cards WHERE conversation_id = ? "
                "ORDER BY created_at ASC",
                (conversation_id,),
            )
        except Exception as exc:
            logger.warning(
                f"[ConversationContextStore] get_cards_for_conversation("
                f"{conversation_id}) failed: {exc}"
            )
            return []

        cards: List[CardState] = []
        for row in rows:
            try:
                data = json.loads(row[0])
                card = CardState.from_dict(data)
            except Exception as exc:
                logger.warning(
                    f"[ConversationContextStore] skipping corrupt card row "
                    f"for conversation_id={conversation_id}: {exc}"
                )
                continue
            if card.conversation_id != conversation_id:
                # AC3: never let a scope mismatch (corrupt row, bad write)
                # leak a card into a conversation it wasn't created in.
                continue
            if card.terminal_state == CARD_STATE_RUNNING:
                card.terminal_state = "terminated_unknown"
            cards.append(card)
        return cards

    def _enforce_card_bounds(self, conversation_id: str) -> None:
        """Cards follow the conversation's EXISTING retention rule: the same
        per-conversation cap as ``MAX_MESSAGES_PER_CONV``, oldest evicted
        first. A card is dropped whole (DELETE), never truncated — the edge
        case explicitly forbids persisting or restoring a partial card.
        """
        try:
            conn = self._get_connection()
            try:
                conn.execute(
                    """DELETE FROM conversation_cards WHERE conversation_id = ? AND card_id IN (
                        SELECT card_id FROM conversation_cards WHERE conversation_id = ?
                        ORDER BY created_at ASC
                        LIMIT -1 OFFSET ?
                    )""",
                    (conversation_id, conversation_id, MAX_MESSAGES_PER_CONV),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(
                f"[ConversationContextStore] _enforce_card_bounds("
                f"{conversation_id}) failed: {exc}"
            )

    def close(self) -> None:
        """Close all connections and free resources. Called by fixtures on teardown.

        After calling close(), the store can still be used — it will open new
        connections as needed.  This is a hint for the SQLite engine to flush
        WAL and release file locks so tools like tempfile.cleanup() can delete
        the database file on Windows.
        """
        try:
            conn = self._get_connection()
            # Flush WAL to main database file
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            # Switch out of WAL mode so no WAL/-shm/-wal files remain
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning(f"[ConversationContextStore] close failed: {exc}")

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
            # REQ-4 AC1: card state, keyed by card_id and scoped to its
            # conversation. A dedicated table (mirrors document_data in
            # document_store.py) rather than a column on conversation_contexts
            # — cards render and evict independently of the message snapshot.
            conn.execute(
                """CREATE TABLE IF NOT EXISTS conversation_cards (
                    card_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cards_conversation "
                "ON conversation_cards(conversation_id)"
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
        """Keep the DB bounded at MAX_CONVERSATIONS.

        Cascades to conversation_cards: a conversation evicted by LRU must
        not leave its cards behind as orphans nothing will ever load again.
        """
        try:
            conn = self._get_connection()
            try:
                evicted = conn.execute(
                    """SELECT conversation_id FROM conversation_contexts
                       ORDER BY updated_at DESC
                       LIMIT -1 OFFSET ?""",
                    (MAX_CONVERSATIONS,),
                ).fetchall()
                evicted_ids = [r[0] for r in evicted]
                conn.execute(
                    """DELETE FROM conversation_contexts WHERE conversation_id IN (
                        SELECT conversation_id FROM conversation_contexts
                        ORDER BY updated_at DESC
                        LIMIT -1 OFFSET ?
                    )""",
                    (MAX_CONVERSATIONS,),
                )
                if evicted_ids:
                    placeholders = ",".join("?" * len(evicted_ids))
                    conn.execute(
                        f"DELETE FROM conversation_cards WHERE conversation_id IN ({placeholders})",
                        evicted_ids,
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(
                f"[ConversationContextStore] _enforce_bounds failed: {exc}"
            )


# ── Card write queue (T4a — REQ-4 AC1/AC5) ──────────────────────────────────
#
# ``save_card`` is synchronous SQLite. The kernel's emit sites (task:start,
# task:progress step transitions, task:done/fail) run on the DER worker
# thread — ``iris_gateway.py``'s ``loop.run_in_executor(None, _execute_agent)``
# pool, never inside a coroutine on the asyncio event loop, so there is no
# running loop to hand a blocking call to via ``asyncio.to_thread``. A single
# background daemon thread drains a coalescing queue instead: ``enqueue()``
# from the emit site is an O(1) dict write under a lock and returns
# immediately, never touching disk on the calling (DER) thread.


CARD_WRITE_QUEUE_MAX = 200  # mirrors AgentKernel._CARD_REGISTRY_CAP — a kernel
# process tracks at most that many live cards, so the write queue never needs
# to hold more distinct card_ids than the kernel itself would track.


class CardWriteQueue:
    """Bounded, coalescing, non-blocking writer for ``CardState`` snapshots.

    COALESCING: keyed by ``card_id``. A burst of step-transition snapshots
    for the same card overwrites the same pending entry, so the writer
    thread issues at most one ``save_card`` per card per drain cycle — not
    one per emit.

    BOUND: at most ``CARD_WRITE_QUEUE_MAX`` distinct card_ids waiting to be
    written at once. A NEW card_id that would exceed the bound evicts the
    OLDEST still-pending card_id (dropped, with a warning) — that card's
    last snapshot is lost and it falls back to whatever was last durably
    written (or nothing, if it never wrote). This bounds memory without
    blocking the caller; it never blocks admission of the newest write.

    FAILURE: a ``save_card`` failure is logged and dropped — it never
    raises back into the DER loop and never retries indefinitely (the next
    snapshot for that card_id, if any, supersedes it naturally).
    """

    def __init__(self, store_getter) -> None:
        self._store_getter = store_getter
        self._lock = threading.Lock()
        self._pending: "OrderedDict[str, Any]" = OrderedDict()
        self._wake = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._thread: Optional[threading.Thread] = None

    def enqueue(self, card: "CardState") -> None:
        """Admit a card snapshot for eventual persistence. Never blocks on
        disk I/O and never raises — a queue-admission failure is logged and
        the write is simply dropped, matching the T4/T5 "never block a user
        response" rule."""
        try:
            with self._lock:
                if card.card_id not in self._pending and (
                    len(self._pending) >= CARD_WRITE_QUEUE_MAX
                ):
                    _oldest_id, _ = self._pending.popitem(last=False)
                    logger.warning(
                        "[CardWriteQueue] pending bound (%d) hit — dropping "
                        "unwritten snapshot for card_id=%s to admit card_id=%s",
                        CARD_WRITE_QUEUE_MAX, _oldest_id, card.card_id,
                    )
                self._pending[card.card_id] = card
                self._idle.clear()
                self._ensure_thread_started_locked()
            self._wake.set()
        except Exception as exc:  # noqa: BLE001 — admission must never raise
            logger.warning("[CardWriteQueue] enqueue failed: %s", exc)

    def _ensure_thread_started_locked(self) -> None:
        """Must be called with self._lock held."""
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._run, name="card-write-queue", daemon=True
            )
            self._thread.start()

    def _run(self) -> None:
        while True:
            self._wake.wait(timeout=5.0)
            self._wake.clear()
            with self._lock:
                batch = list(self._pending.values())
                self._pending.clear()
            if not batch:
                self._idle.set()
                continue
            store = self._store_getter()
            for card in batch:
                try:
                    store.save_card(card)
                except Exception as exc:  # noqa: BLE001 — never crash the writer thread
                    logger.warning(
                        "[CardWriteQueue] save_card failed for card_id=%s: %s",
                        card.card_id, exc,
                    )
            with self._lock:
                if not self._pending:
                    self._idle.set()

    def wait_idle(self, timeout: float = 2.0) -> bool:
        """TEST-ONLY: block until the queue has drained and no write is in
        flight. The real emit path never calls this — it exists so contract
        tests can assert a write landed without sleeping arbitrarily.
        Returns False on timeout."""
        return self._idle.wait(timeout=timeout)


_card_write_queue: Optional[CardWriteQueue] = None


def get_card_write_queue() -> CardWriteQueue:
    """Get or create the singleton CardWriteQueue, wired to the singleton
    ConversationContextStore (get_context_store) — resolved lazily on each
    drain so tests that swap the store via reset_context_store_for_testing()
    are still picked up."""
    global _card_write_queue
    if _card_write_queue is None:
        _card_write_queue = CardWriteQueue(get_context_store)
    return _card_write_queue


def enqueue_card_write(card: "CardState") -> None:
    """Non-blocking entry point for emit sites: hand a card snapshot to the
    background writer. Never raises, never touches disk on this thread."""
    try:
        get_card_write_queue().enqueue(card)
    except Exception as exc:  # noqa: BLE001 — never block the emit site
        logger.warning("[CardWriteQueue] enqueue_card_write failed: %s", exc)


def reset_card_write_queue_for_testing() -> None:
    """Reset the singleton — for test isolation only."""
    global _card_write_queue
    _card_write_queue = None


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
