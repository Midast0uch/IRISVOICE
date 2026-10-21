"""The strand identity rule of the memory (MEMORY-SURFACE-BUILD section 4 case 5,
MEMORY-UX-PLAN section 4.2). ONE place, read-only.

  strand  = a conversation id (conversations.db). A memory row typed during a chat
            turn carries  thread_id = <conversation id>  and
            episode_id = "<conversation id>:<turn id>".
  Rows of older builds carry the WebSocket session id ("session_iris") as thread_id;
  ``caducean_session_exits.conversation_id`` still names the conversation a session
  ran. ``resolve_strand`` reads both; ``conversation_row_ids`` is the writer's half of
  the same rule (used by memory_events.emit_event, the one row writer).
"""
from __future__ import annotations

import logging
from typing import Any, FrozenSet, Optional, Tuple

logger = logging.getLogger(__name__)


def _is_conversation(conversation_id: str) -> bool:
    """A live conversation (chat knows it). One primary-key read."""
    try:
        from backend import conversation_store

        return conversation_store.get_strand(conversation_id) is not None
    except Exception as exc:  # noqa: BLE001 - no chat store: not a conversation
        logger.warning("[strand_ids] conversation lookup failed id=%s: %s", conversation_id, exc)
        return False


def _is_ghost(memory_conn: Any, conversation_id: str) -> bool:
    """A conversation chat deleted: its STRAND_DELETED tombstone is in the memory.
    The family+label index narrows the read to the tombstones (never a scan)."""
    try:
        row = memory_conn.execute(
            "SELECT 1 FROM memory_events WHERE family = 'memory' AND label = 'STRAND_DELETED' "
            "AND thread_id = ? LIMIT 1", (conversation_id,)
        ).fetchone()
        return row is not None
    except Exception as exc:  # noqa: BLE001 - an older store without the table: no ghosts
        logger.warning("[strand_ids] tombstone lookup failed id=%s: %s", conversation_id, exc)
        return False


def resolve_strand(thread_id: Optional[str], memory_conn: Any = None) -> Optional[str]:
    """The conversation id a memory thread id stands for, or None (outside chat).

    1. the id is a conversation (live, or a ghost with a tombstone) -> itself;
    2. else it is a session id: ``caducean_session_exits.conversation_id`` names the
       conversation when the session ran exactly ONE (a session shared by many
       conversations, e.g. "session_iris", is ambiguous -> None, never a guess);
    3. else None (``eval-*``, test ids, the system's own rows).
    Read-only. ``memory_conn`` is a connection to the app store (data/memory.db,
    opened only through resolve_memory_store_path); without it only step 1 runs.
    """
    if not thread_id:
        return None
    if _is_conversation(thread_id):
        return thread_id
    if memory_conn is None:
        return None
    if _is_ghost(memory_conn, thread_id):
        return thread_id
    try:
        found = [r[0] for r in memory_conn.execute(
            "SELECT DISTINCT conversation_id FROM caducean_session_exits "
            "WHERE session_id = ? AND conversation_id IS NOT NULL LIMIT 3", (thread_id,)
        )]
    except Exception as exc:  # noqa: BLE001 - an older store without the table
        logger.warning("[strand_ids] session exit lookup failed id=%s: %s", thread_id, exc)
        return None
    if len(found) != 1 or found[0] == thread_id:
        return None
    cand = found[0]
    return cand if (_is_conversation(cand) or _is_ghost(memory_conn, cand)) else None


def conversation_row_ids(
    conversation_id: Optional[str], sessions: FrozenSet[str],
    thread_id: Optional[str], episode_id: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    """The writer's half: the (thread_id, episode_id) a row must carry.

    ``sessions`` are the session ids the owning kernel runs under; a row typed with one
    of them (or none) is re-keyed to the conversation, and an episode "<session>:<turn>"
    becomes "<conversation>:<turn>". Without a conversation nothing changes."""
    if not conversation_id:
        return thread_id, episode_id
    if thread_id is not None and thread_id not in sessions and thread_id != conversation_id:
        return thread_id, episode_id   # another thread's row (e.g. "research"): not ours to re-key
    if episode_id:
        for s in sessions:
            if episode_id.startswith(s + ":"):
                episode_id = conversation_id + episode_id[len(s):]
                break
    return conversation_id, episode_id
