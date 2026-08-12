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
    document_id TEXT PRIMARY KEY,
    conversation_id TEXT,
    fmt TEXT,
    content TEXT,
    variants TEXT,
    alternatives TEXT,
    trust TEXT,
    revision INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
)
"""


_SQL_CREATE_EDGES = """
CREATE TABLE IF NOT EXISTS reformat_edges (
    from_format TEXT NOT NULL,
    to_format   TEXT NOT NULL,
    weight      REAL DEFAULT 0.0,
    updated_at  REAL,
    PRIMARY KEY (from_format, to_format)
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
            self._conn.execute(_SQL_CREATE_EDGES)
            self._conn.commit()
            # Phase 4 (chat-card-redesign): revision column added after launch.
            try:
                self._conn.execute(
                    "ALTER TABLE document_data ADD COLUMN revision INTEGER DEFAULT 0"
                )
                self._conn.commit()
            except Exception:
                # Column already exists on a fresh DB — safe to ignore.
                pass
            # Wave 0/1 (document-rehydration, REQ-5/REQ-13): provenance linkage.
            # `turn_id` was passed to every writer and stored by NONE of them, so
            # a rehydrated document came back unattributable: the frontend pairs
            # a card to its turn by turn_id, and without it the answer text and
            # its card both render (neither knowing about the other) and the
            # agent cannot tell which exchange a previous render belongs to.
            # Idempotent — each ADD COLUMN is a no-op once the column exists.
            for col in ("source_document_id", "sources", "har_path", "turn_id"):
                try:
                    self._conn.execute(
                        f"ALTER TABLE document_data ADD COLUMN {col} TEXT"
                    )
                    self._conn.commit()
                except Exception:
                    # Column already exists — safe to ignore.
                    pass
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
        revision: int = 0,
        source_document_id: Optional[str] = None,
        sources: Optional[list] = None,
        har_path: Optional[str] = None,
        turn_id: Optional[str] = None,
    ) -> None:
        """Upsert a document's canonical data + variants (idempotent by id)."""
        try:
            self._conn.execute(
                "INSERT INTO document_data "
                "(document_id, conversation_id, fmt, content, variants, alternatives, trust, revision, "
                " source_document_id, sources, har_path, turn_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(document_id) DO UPDATE SET "
                "conversation_id=excluded.conversation_id, fmt=excluded.fmt, "
                "content=excluded.content, variants=excluded.variants, "
                "alternatives=excluded.alternatives, trust=excluded.trust, "
                "revision=document_data.revision, "
                "source_document_id=excluded.source_document_id, "
                "sources=excluded.sources, har_path=excluded.har_path, "
                # COALESCE, not excluded: a later write that does not know the
                # turn (a reformat, a variant refresh) must not erase the
                # attribution the original render established.
                "turn_id=COALESCE(excluded.turn_id, document_data.turn_id)",
                (
                    document_id,
                    conversation_id,
                    fmt,
                    content,
                    json.dumps(variants or {}, ensure_ascii=False),
                    json.dumps(alternatives or [], ensure_ascii=False),
                    trust,
                    revision,
                    source_document_id,
                    json.dumps(sources or [], ensure_ascii=False) if sources is not None else None,
                    har_path,
                    turn_id,
                ),
            )
            self._conn.commit()
            self._evict_if_needed()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[DocumentDataStore] store failed: %s", exc)

    def update(self, document_id: str, content: str, fmt: str, variants: Dict[str, str], trust: str) -> bool:
        """Phase 4 (chat-card-redesign): revise an existing document's content.

        Bumps ``revision`` so the frontend can show an 'Updated' indicator and
        later recall sees the latest version.  Returns False if the id is unknown.
        """
        try:
            cur = self._conn.execute(
                "UPDATE document_data SET content=?, fmt=?, variants=?, trust=?, revision=revision+1 "
                "WHERE document_id=?",
                (content, fmt, json.dumps(variants or {}, ensure_ascii=False), trust, document_id),
            )
            self._conn.commit()
            return cur.rowcount > 0
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[DocumentDataStore] update failed: %s", exc)
            return False

    def get(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Return the full document record, or None if not found."""
        try:
            row = self._conn.execute(
                "SELECT document_id, conversation_id, fmt, content, variants, "
                "alternatives, trust, revision, source_document_id, sources, har_path, "
                "turn_id "
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
                "revision": row[7] or 0,
                "source_document_id": row[8],
                "sources": json.loads(row[9] or "[]"),
                "har_path": row[10],
                "turn_id": row[11],
            }
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[DocumentDataStore] get failed: %s", exc)
            return None

    def list_for_conversation(self, conversation_id: str, metadata_only: bool = False) -> list:
        """Return all document rows for a conversation (REQ-4/REQ-7).

        ``metadata_only=True`` (UI path, REQ-4/T3) returns light columns only
        (document_id, fmt, conversation_id, sources, har_path, created_at) —
        NOT the large content/variants blobs. Full data only when
        ``metadata_only=False`` (agent tool path, REQ-7/T5). Always scoped by
        ``conversation_id`` (REQ-12). Never raises.
        """
        try:
            if metadata_only:
                rows = self._conn.execute(
                    "SELECT document_id, fmt, conversation_id, sources, har_path, created_at, "
                    "turn_id "
                    "FROM document_data WHERE conversation_id = ? ORDER BY created_at ASC",
                    (conversation_id,),
                ).fetchall()
                return [
                    {
                        "document_id": r[0],
                        "format": r[1],
                        "conversation_id": r[2],
                        "sources": json.loads(r[3] or "[]"),
                        "har_path": r[4],
                        "created_at": r[5],
                        "turn_id": r[6],
                    }
                    for r in rows
                ]
            rows = self._conn.execute(
                "SELECT document_id, conversation_id, fmt, content, variants, "
                "alternatives, trust, revision, source_document_id, sources, har_path, "
                "turn_id "
                "FROM document_data WHERE conversation_id = ? ORDER BY created_at ASC",
                (conversation_id,),
            ).fetchall()
            return [
                {
                    "document_id": r[0],
                    "conversation_id": r[1],
                    "format": r[2],
                    "content": r[3],
                    "variants": json.loads(r[4] or "{}"),
                    "alternatives": json.loads(r[5] or "[]"),
                    "trust": r[6],
                    "revision": r[7] or 0,
                    "source_document_id": r[8],
                    "sources": json.loads(r[9] or "[]"),
                    "har_path": r[10],
                    "turn_id": r[11],
                }
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[DocumentDataStore] list_for_conversation failed: %s", exc)
            return []

    def list_conversations(self) -> list:
        """Return every conversation that has at least one rendered document.

        Discovery primitive for cross-thread reuse: the agent calls this to find
        prior threads (e.g. one that previously rendered a document) and then
        pulls their data via ``get_rendered_documents(conversation_id=...)``
        instead of re-searching the web. Newest-first:
        ``[{conversation_id, doc_count, latest_created_at}]``. Never raises.
        """
        try:
            rows = self._conn.execute(
                "SELECT conversation_id, COUNT(*) AS doc_count, MAX(created_at) AS latest "
                "FROM document_data GROUP BY conversation_id ORDER BY latest DESC"
            ).fetchall()
            return [
                {
                    "conversation_id": r[0],
                    "doc_count": r[1],
                    "latest_created_at": r[2],
                }
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[DocumentDataStore] list_conversations failed: %s", exc)
            return []

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

    # ── W10 (O4): reformat pheromone edges ──────────────────────────────────
    def record_reformat(self, from_format: str, to_format: str, amount: float = 1.0) -> None:
        """Reinforce the pheromone edge from_format -> to_format (W10/O4).

        Weight compounds on repeated use (bounded at 100.0) so frequently
        reformatted doc types become "sticky" — the substrate for proactively
        offering reformats. Never raises.
        """
        try:
            self._conn.execute(
                "INSERT INTO reformat_edges (from_format, to_format, weight, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(from_format, to_format) DO UPDATE SET "
                "weight = MIN(weight + excluded.weight, 100.0), "
                "updated_at = excluded.updated_at",
                (from_format, to_format, float(amount), time.time()),
            )
            self._conn.commit()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[DocumentDataStore] record_reformat failed: %s", exc)

    def get_reformat_edges(self, from_format: Optional[str] = None) -> list:
        """Return reformat edges (from_format, to_format, weight), highest weight first."""
        try:
            if from_format is not None:
                rows = self._conn.execute(
                    "SELECT from_format, to_format, weight FROM reformat_edges "
                    "WHERE from_format = ? ORDER BY weight DESC",
                    (from_format,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT from_format, to_format, weight FROM reformat_edges "
                    "ORDER BY weight DESC"
                ).fetchall()
            return [
                {"from_format": r[0], "to_format": r[1], "weight": r[2]} for r in rows
            ]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[DocumentDataStore] get_reformat_edges failed: %s", exc)
            return []

    def predict_next_format(self, from_format: str) -> Optional[str]:
        """Return the most-reinforced target format for ``from_format``, or None."""
        edges = self.get_reformat_edges(from_format)
        if not edges:
            return None
        return edges[0]["to_format"]

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
