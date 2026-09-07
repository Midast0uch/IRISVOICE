"""
Card footprints — REQ-11: persist a per-card execution record, retrievable
by card_id alone, without loading the whole conversation.

Foundation only (Decisions Locked 6): this module writes and reads the
record. `@card:` addressing UX is explicitly deferred to a later spec — do
not build it here.

Storage: writes through backend/memory/semantic.py's EXISTING key-value
interface (SemanticStore.update / SemanticStore.get) — the SAME interface
backend/memory/skills.py already uses to key crystallised skills by
skill_key. No new store, no interface change (design.md records
`backend/memory/` stores as NO-CHANGE-verified for REQ-11).

  category="card_footprints", key=card_id
    -> AC2: keyed by the REQ-3 card_id.
    -> AC4: SemanticStore.get(category, key) is a direct primary-key
       lookup — no conversation-wide scan required.
    -> Duplicate card_id: SemanticStore.update()'s ON CONFLICT upserts the
       existing row rather than creating a second (edge case satisfied for
       free by the interface we're reusing).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from backend.memory.interface import MemoryInterface

logger = logging.getLogger(__name__)

CARD_FOOTPRINT_CATEGORY = "card_footprints"


def save_card_footprint(
    memory: MemoryInterface,
    card_id: str,
    conversation_id: str,
    objective: str,
    steps: List[Dict[str, Any]],
    tools_used: List[str],
    files_touched: List[str],
    outcome: str,
) -> bool:
    """Persist a card's footprint (REQ-11 AC1/AC2/AC3/AC5).

    ``outcome`` is the TERMINAL state actually reached —
    "converged" | "failed" | "abandoned" | "unknown". A card that never
    completes still records that reached state (edge case: never a
    fabricated success).

    ``created_at`` is preserved across repeated writes for the same
    card_id (best-effort read-before-write); a fresh write when no prior
    entry exists sets both timestamps to now.

    Never raises: a failed footprint write must not block execution or a
    user response (REQ-11 edge case / T5 rule) — logged and returns False.
    """
    if not card_id:
        logger.warning("[card_footprint] save skipped: missing card_id")
        return False
    try:
        now = time.time()
        created_at = now
        try:
            existing = memory.semantic.get(CARD_FOOTPRINT_CATEGORY, card_id)
            if existing is not None:
                existing_data = json.loads(existing.value)
                created_at = existing_data.get("created_at", now)
        except Exception as exc:  # noqa: BLE001 — best-effort; still write fresh
            logger.debug(
                "[card_footprint] could not read prior created_at for "
                "card_id=%s: %s", card_id, exc,
            )

        footprint = {
            "card_id": card_id,
            "conversation_id": conversation_id,
            "objective": objective,
            "steps": steps or [],
            "tools_used": tools_used or [],
            "files_touched": files_touched or [],
            "outcome": outcome,
            "created_at": created_at,
            "updated_at": now,
        }
        memory.semantic.update(
            category=CARD_FOOTPRINT_CATEGORY,
            key=card_id,
            value=json.dumps(footprint, ensure_ascii=False),
            confidence=1.0,
            source="card_lifecycle",
        )
        return True
    except Exception as exc:  # noqa: BLE001 — a footprint write must never break a turn
        logger.warning(
            "[card_footprint] save_card_footprint failed card_id=%s "
            "conversation_id=%s: %s", card_id, conversation_id, exc,
        )
        return False


def get_card_footprint(memory: MemoryInterface, card_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a card's footprint by card_id alone (REQ-11 AC4).

    None if absent, on a malformed stored value, or on any read failure —
    never raises.
    """
    if not card_id:
        return None
    try:
        entry = memory.semantic.get(CARD_FOOTPRINT_CATEGORY, card_id)
        if entry is None:
            return None
        return json.loads(entry.value)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[card_footprint] get_card_footprint failed card_id=%s: %s", card_id, exc
        )
        return None


def save_batch_footprint(
    db,
    batch_id: str,
    tool: str,
    session_id: str,
    items: list,
    fail_on_child: bool = False,
) -> bool:
    """T16 (REQ-19): atomic batch persistence — one transaction, never
    half-committed.

    Idempotent on ``batch_id``: a re-save is a no-op (returns True), so a
    circuit-retry or replay can never duplicate the footprint. Never raises —
    a failed write must never break the turn.
    """
    if not batch_id:
        return False
    now = time.time()
    # Accepts either a Database/Manager object (.conn) or a raw
    # sqlite3.Connection — they share the execute/with driver shape.
    conn = getattr(db, "conn", db)
    if not hasattr(conn, "execute"):
        logger.warning("[card_footprint] no usable db handle; skipping")
        return False
    try:
        cur = conn.execute(
            "SELECT 1 FROM batch_records WHERE batch_id = ?", (batch_id,)
        )
        if cur.fetchone() is not None:
            return True  # idempotent — already written
    except Exception as exc:  # noqa: BLE001
        logger.warning("[card_footprint] idempotence check failed: %s", exc)
        return False

    children = [item for item in (items or []) if isinstance(item, dict)]
    ok_count = sum(1 for c in children if c.get("ok"))

    # One transaction — all children land or none do. `with conn:` commits
    # on success, ROLLBACKS on any exception (the atomicity guarantee T16
    # needs: partial batches never leave an orphan behind).
    with conn:
        conn.execute(
            "INSERT INTO batch_records (batch_id, tool, session_id, item_count, "
            "ok_count, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                batch_id, str(tool), str(session_id), len(children),
                ok_count, now,
            ),
        )
        for i, child in enumerate(children):
            if fail_on_child and i == 0:
                # Test seam: forces a mid-transaction failure to prove the
                # whole batch rolls back atomically.
                raise RuntimeError("simulated child persistence failure")
            conn.execute(
                "INSERT INTO batch_node_records (node_id, batch_id, item_key, "
                "ok, result_json, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{batch_id}::{i}",
                    batch_id,
                    str(child.get("item_key") or "") or f"item-{i}",
                    1 if child.get("ok") else 0,
                    json.dumps(child.get("result"), ensure_ascii=False),
                    str(child.get("error") or "")[:256],
                    now,
                ),
            )
    return True
