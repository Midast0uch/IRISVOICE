#!/usr/bin/env python3
"""DocumentDataStore — persistent canonical document data keyed by document_id.

Source-of-truth (plan G4) for a document's canonical data + rendered *variants*,
so ``reformat_document`` can retrieve by id and return a stored variant with
zero LLM calls (plan G1: "deterministic selection from stored variants").

Storage: SQLite in the same WAL-mode DB as the episodic store (reuses the
proven ``conversation_context_store`` pattern — thread-safe, bounded, never
blocks on read/write failure).  Each row holds the canonical ``content`` plus a
``variants`` JSON map of ``{format: content}`` (the LLM emits these in one
response; see agent_kernel prompt).  Retrieval is exact-by-id (T6/T13) and the
store is the reconciliation point for Immortus/Mycelium copies (G4).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Global bound on stored documents; oldest by created_at are evicted.
_MAX_DOCUMENTS = 500

_SQL_CREATE = """
CREATE TABLE IF NOT EXISTS document_data (
    document_id   TEXT PRIMARY KEY,
    conversation_id TEXT,
    fmt           TEXT,
    content       TEXT,
    variants      TEXT,
    alternatives  TEXT,
    trust         TEXT,
    created_at    REAL
)
"""


class DocumentDataStore:
    """Per-connection store of canonical document data, keyed by document_id."""

    _stores: Dict[int, "DocumentDataStore"] = {}

    def __init__(self, db_conn: sqlite3.Connection) -> None:
        self._conn = db_conn
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            self._conn.execute(_SQL_CREATE)
            self._conn.commit()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[DocumentDataStore] ensure_table failed: %s", exc)

    def store(
        self,
        document_id: str,
        conversation_id: str,
        fmt: str,
        content: str,
        variants: Dict[str, str],
        alternatives: list,
        trust: str,
    ) -> None:
        """Upsert a document's canonical data + variants (idempotent by id)."""
        try:
            self._conn.execute(
                "INSERT INTO document_data "
                "(document_id, conversation_id, fmt, content, variants, alternatives, trust, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(document_id) DO UPDATE SET "
                "conversation_id=excluded.conversation_id, fmt=excluded.fmt, "
                "content=excluded.content, variants=excluded.variants, "
                "alternatives=excluded.alternatives, trust=excluded.trust, "
                "created_at=excluded.created_at",
                (
                    document_id,
                    conversation_id,
                    fmt,
                    content,
                    json.dumps(variants or {}, ensure_ascii=False),
                    json.dumps(alternatives or [], ensure_ascii=False),
                    trust,
                    time.time(),
                ),
            )
            self._conn.commit()
            self._evict_if_needed()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[DocumentDataStore] store failed: %s", exc)

    def get(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Return the full document record, or None if not found."""
        try:
            row = self._conn.execute(
                "SELECT document_id, conversation_id, fmt, content, variants, "
                "alternatives, trust, created_at "
                "FROM document_data WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "document_id": row[0],
                "conversation_id": row[1],
                "format": row[2],
                "content": row[3],
                "variants": json.loads(row[4] or "{}"),
                "alternatives": json.loads(row[5] or "[]"),
                "trust": row[6],
                "created_at": row[7],
            }
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[DocumentDataStore] get failed: %s", exc)
            return None

    def get_variant(self, document_id: str, target_format: str) -> Optional[str]:
        """Return the stored content for ``target_format`` if present (G1 path)."""
        doc = self.get(document_id)
        if doc is None:
            return None
        return (doc.get("variants") or {}).get(target_format)

    def add_variant(self, document_id: str, target_format: str, content: str) -> None:
        """Cache a newly generated variant so future reformats are deterministic."""
        doc = self.get(document_id)
        if doc is None:
            return
        variants = dict(doc.get("variants") or {})
        variants[target_format] = content
        try:
            self._conn.execute(
                "UPDATE document_data SET variants = ? WHERE document_id = ?",
                (json.dumps(variants, ensure_ascii=False), document_id),
            )
            self._conn.commit()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[DocumentDataStore] add_variant failed: %s", exc)

    def _evict_if_needed(self) -> None:
        try:
            cur = self._conn.execute("SELECT COUNT(*) FROM document_data")
            count = cur.fetchone()[0]
            if count > _MAX_DOCUMENTS:
                excess = count - _MAX_DOCUMENTS
                self._conn.execute(
                    "DELETE FROM document_data WHERE document_id IN ("
                    "SELECT document_id FROM document_data ORDER BY created_at ASC LIMIT ?)",
                    (excess,),
                )
                self._conn.commit()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[DocumentDataStore] evict failed: %s", exc)

    @classmethod
    def get_for(cls, memory_interface: Any) -> Optional["DocumentDataStore"]:
        """Return (or create) the store for a MemoryInterface's DB connection.

        Returns None when no SQLite connection is available (e.g. tests with a
        fake memory interface) so callers can gracefully skip persistence.
        """
        if memory_interface is None:
            return None
        episodic = getattr(memory_interface, "episodic", None)
        conn = getattr(episodic, "db", None) if episodic is not None else None
        if conn is None:
            return None
        key = id(memory_interface)
        if key not in cls._stores:
            cls._stores[key] = cls(conn)
        return cls._stores[key]
