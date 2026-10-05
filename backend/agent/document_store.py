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
import threading
import time
from typing import Any, Dict, Optional

from backend.memory.db import app_flush, app_write, owns_store

from backend.agent.artifact_policy import (
    card_title_from_content,
    is_tool_result_envelope,
)

logger = logging.getLogger(__name__)

# Global bound on stored documents; oldest by created_at are evicted.
_MAX_DOCUMENTS = 500

# How much of a body is read to derive a card title. The hydration payload is
# metadata-only BY DESIGN (CT-DOC-1 pins "no content"), but the title label has
# to come from somewhere — so the store reads a bounded preview and derives it.
_TITLE_PREVIEW_CHARS = 400

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


# Binary bodies (screenshots) live in their OWN table rather than as a column on
# document_data, for two reasons that both bite in practice:
#   * `list_for_conversation(metadata_only=False)` selects content/variants for a
#     whole conversation. A blob column would be dragged into every one of those
#     reads — megabytes to answer a question about text.
#   * document_data's TEXT `content` is truncated on the render path
#     (agent_kernel `response[:12000]`) and again in the card at 50k. A base64
#     image in that column would be silently CUT, producing a broken image with
#     no error anywhere — the exact class of failure this file keeps hosting.
# Keyed by document_id so the image is addressed by an opaque id, never by a
# filename: there is no path to traverse. Lifetime follows the document row
# (see _evict), so an image cannot outlive the card that shows it.
_SQL_CREATE_BLOBS = """
CREATE TABLE IF NOT EXISTS document_blobs (
    document_id TEXT PRIMARY KEY,
    mime TEXT NOT NULL,
    data BLOB NOT NULL,
    byte_len INTEGER NOT NULL,
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
        # Read-your-writes, TARGETED: what this store queued on the one writer
        # and a read may need (doc id / "conv:<id>" / "edges" -> queued at).
        # A blanket flush on every read waited for the WHOLE queue - 34 reads,
        # 149 s, up to 14.4 s each on the answer path (live A/B 2026-10-04).
        self._pending: Dict[str, float] = {}
        self._pending_lock = threading.Lock()
        self._ensure_table()

    def _note_pending(self, *keys: Optional[str]) -> None:
        if not owns_store(self._conn):
            return
        now = time.monotonic()
        with self._pending_lock:
            for k in keys:
                if k:
                    self._pending[k] = now

    def _settle(self, *keys: Optional[str], any_doc: bool = False) -> None:
        """Wait for the writer queue ONLY when this store queued a write the
        read needs (a key below, or any write for an all-documents read)."""
        with self._pending_lock:
            if not self._pending:
                return
            now = time.monotonic()
            for k, t in list(self._pending.items()):
                if now - t > 30.0:  # long landed
                    del self._pending[k]
            hit = bool(self._pending) if any_doc else any(k in self._pending for k in keys if k)
        if not hit:
            return
        started = time.monotonic()
        if app_flush(5.0):
            with self._pending_lock:
                for k, t in list(self._pending.items()):
                    if t <= started:
                        del self._pending[k]

    def _ensure_table(self) -> None:
        try:
            self._conn.execute(_SQL_CREATE)
            self._conn.execute(_SQL_CREATE_BLOBS)
            self._conn.execute(_SQL_CREATE_EDGES)
            # The evict picks the oldest rows; without this index it scanned
            # and sorted the table on every store past the cap (2.6 s on the
            # writer thread, live 2026-10-04).
            # Through the one writer: a direct CREATE INDEX needs the write
            # lock, and the slow evict it exists to fix held that lock past the
            # 5 s busy timeout ("ensure_table failed: database is locked").
            app_write(
                self._conn,
                "CREATE INDEX IF NOT EXISTS idx_document_data_created "
                "ON document_data(created_at)",
            )
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
            for col in (
                "source_document_id",
                "sources",
                "har_path",
                "turn_id",
                # 2026-09-22 (reply-surface-contract audit, REQ-10): persist the
                # prism card lifecycle id so it survives a reload instead of a
                # fresh in-memory mint replacing it while the document survives.
                "card_id",
            ):
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
        card_id: Optional[str] = None,
    ) -> None:
        """Upsert a document's canonical data + variants (idempotent by id)."""
        try:
            from backend.memory.db import locked_retry as _locked_retry326

            def _write326() -> None:
                app_write(
                    self._conn,
                    "INSERT INTO document_data "
                "(document_id, conversation_id, fmt, content, variants, alternatives, trust, revision, "
                " source_document_id, sources, har_path, turn_id, card_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
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
                "turn_id=COALESCE(excluded.turn_id, document_data.turn_id), "
                # Same rule for the lifecycle id: an existing card_id is a
                # contract with any client that already saw it (REQ-10 AC1/AC4).
                "card_id=COALESCE(excluded.card_id, document_data.card_id)",
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
                    card_id,
                ),
            )

            _locked_retry326(_write326, label="document_data.store")
            self._note_pending(document_id, f"conv:{conversation_id}")
            self._evict_if_needed()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[DocumentDataStore] store failed: %s", exc)

    def update(self, document_id: str, content: str, fmt: str, variants: Dict[str, str], trust: str) -> bool:
        """Phase 4 (chat-card-redesign): revise an existing document's content.

        Bumps ``revision`` so the frontend can show an 'Updated' indicator and
        later recall sees the latest version.  Returns False if the id is unknown.
        """
        try:
            from backend.memory.db import locked_retry as _locked_retry326

            # One writer: rowcount is only truthiness here, so count the row
            # first (flush: a store() queued just before must be visible).
            self._settle(document_id)
            exists = self._conn.execute(
                "SELECT 1 FROM document_data WHERE document_id=?", (document_id,)
            ).fetchone() is not None

            def _write326() -> None:
                app_write(
                    self._conn,
                    "UPDATE document_data SET content=?, fmt=?, variants=?, trust=?, revision=revision+1 "
                    "WHERE document_id=?",
                    (content, fmt, json.dumps(variants or {}, ensure_ascii=False), trust, document_id),
                )

            _locked_retry326(_write326, label="document_data.update")
            self._note_pending(document_id)
            return exists
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[DocumentDataStore] update failed: %s", exc)
            return False

    # ── Binary bodies (screenshots) ────────────────────────────────────────
    # Deliberately NOT folded into store()/get(): a caller asking for a text
    # document must never pay for an image, and a blob must never reach a code
    # path that treats `content` as text (it would be truncated, see the
    # _SQL_CREATE_BLOBS note).

    def store_blob(
        self, document_id: str, data: bytes, mime: str = "image/png"
    ) -> bool:
        """Persist a binary body for ``document_id``. Returns success.

        Never raises: an image that fails to store must cost the card its
        picture, never the turn.
        """
        if not document_id or not data:
            return False
        try:
            app_write(
                self._conn,
                "INSERT OR REPLACE INTO document_blobs "
                "(document_id, mime, data, byte_len) VALUES (?, ?, ?, ?)",
                (document_id, mime, bytes(data), len(data)),
            )
            self._note_pending(document_id)
            return True
        except Exception as exc:  # noqa: BLE001 — storage never breaks a turn
            logger.warning(
                "[DocumentDataStore] store_blob failed id=%s bytes=%d: %s",
                document_id, len(data), exc,
            )
            return False

    def get_blob(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Return ``{"mime", "data", "byte_len"}`` for a stored binary body.

        None when absent — the caller serves a 404 rather than a placeholder, so
        a missing image is visible as missing instead of silently blank.
        """
        if not document_id:
            return None
        try:
            self._settle(document_id)  # a store_blob this store queued
            row = self._conn.execute(
                "SELECT mime, data, byte_len FROM document_blobs WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            if row is None:
                return None
            return {"mime": row[0], "data": bytes(row[1]), "byte_len": row[2]}
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[DocumentDataStore] get_blob failed id=%s: %s", document_id, exc
            )
            return None

    def store_json_atomic(
        self,
        document_id: str,
        fmt: str,
        content: str,
        conversation_id: Optional[str] = None,
        variants: Optional[dict] = None,
        alternatives: Optional[list] = None,
        trust: Optional[str] = None,
        turn_id: Optional[str] = None,
        source_document_id: Optional[str] = None,
        sources: Optional[list] = None,
        har_path: Optional[str] = None,
    ) -> None:
        """REQ-14 AC4: bump revision by +1 when the SAME document_id gets a
        new payload, and record the revision transition. Never silently fail —
        a failed upsert here is a contract break.
        """
        # get() flushes the writer, so a prior queued write is read here.
        existing = self.get(document_id)
        next_revision = (existing["revision"] + 1) if existing else 1
        # AC14.2 boundary: a delta only exists against a REAL prior snapshot.
        # On a first-ever write there is nothing to compare — computing the
        # diff against {} would fabricate "changed from —" statements for
        # every field. (Found by BT-7 test_first_snapshot_creates_revision_1.)
        if existing is not None:
            try:
                from backend.crawler.temporal_diff import compute_temporal_delta

                prior_content = existing.get("content") or "{}"
                prior_dict = json.loads(prior_content) if prior_content else {}
                current_dict = json.loads(content) if content else {}
                delta = compute_temporal_delta(prior_dict, current_dict)
                _v = dict(variants or {})
                _v["_temporal_delta"] = {
                    "changed_fields": delta.changed_fields,
                    "delta_statements": delta.delta_statements,
                    "prior_revision": existing["revision"],
                    "current_revision": next_revision,
                }
            except Exception:
                _v = dict(variants or {})
        else:
            _v = dict(variants or {})
        try:
            app_write(
                self._conn,
                "INSERT INTO document_data "
                "(document_id, conversation_id, fmt, content, variants, alternatives, trust, revision, "
                " source_document_id, sources, har_path, turn_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(document_id) DO UPDATE SET "
                "conversation_id=excluded.conversation_id, fmt=excluded.fmt, "
                "content=excluded.content, variants=excluded.variants, "
                "alternatives=excluded.alternatives, trust=excluded.trust, "
                # atomic path writes revision explicitly — the plain store()
                # unexpectedly keeps the original so this path is the only
                # reentrant way a re-crawl can show "Updated". One writer: the
                # bump is computed on the writer thread, not from the read above
                # (two queued writes would both carry the same stale number).
                "revision=document_data.revision + 1, "
                "source_document_id=excluded.source_document_id, "
                "sources=excluded.sources, har_path=excluded.har_path, "
                "turn_id=COALESCE(excluded.turn_id, document_data.turn_id)",
                (
                    document_id,
                    conversation_id or (existing["conversation_id"] if existing else ""),
                    fmt,
                    content,
                    json.dumps(_v, ensure_ascii=False),
                    json.dumps(alternatives or [], ensure_ascii=False),
                    trust or "",
                    next_revision,
                    source_document_id,
                    json.dumps(sources or [], ensure_ascii=False) if sources is not None else None,
                    har_path,
                    turn_id,
                ),
            )
            self._note_pending(document_id, f"conv:{conversation_id}" if conversation_id else None)
        except Exception as exc:
            logger.warning(
                "[DocumentDataStore] store_json_atomic failed id=%s: %s",
                document_id, exc,
            )

    def get_with_delta(self, document_id: str) -> Optional[tuple]:
        """Return (dict, revision, delta) — the full record + revision +
        the TemporalDelta the store captured on the last write, or None if
        not found.

        Shape mirrors the frontend's card rehydration: `sources` from JSON,
        `temporal_delta` variants-computed, `content` canonical.
        """
        row = self.get(document_id)
        if row is None:
            return None
        content = row.get("content") or ""
        try:
            current_dict = json.loads(content) if content else {}
        except Exception:
            current_dict = {}
        v = row.get("variants") or {}
        delta_payload = v.get("_temporal_delta") or {}
        return (
            {
                "sources": row.get("sources") or [],
                "json": current_dict,
                "fmt": row.get("fmt"),
            },
            row.get("revision") or 0,
            delta_payload if delta_payload else None,
        )

    def get(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Return the full document record, or None if not found."""
        try:
            self._settle(document_id)  # a store() this store queued
            row = self._conn.execute(
                "SELECT document_id, conversation_id, fmt, content, variants, "
                "alternatives, trust, revision, source_document_id, sources, har_path, "
                "turn_id, card_id "
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
                "card_id": row[12],
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
            self._settle(f"conv:{conversation_id}")  # a store() for this conversation
            if metadata_only:
                rows = self._conn.execute(
                    "SELECT document_id, fmt, conversation_id, sources, har_path, created_at, "
                    "turn_id, card_id, substr(content, 1, ?) "
                    # A research record (fmt 'research') is memory, not a card:
                    # it is never offered for rehydration.
                    "FROM document_data WHERE conversation_id = ? AND fmt IS NOT 'research' "
                    "ORDER BY created_at ASC",
                    (_TITLE_PREVIEW_CHARS, conversation_id),
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
                        # REQ-10 (audit 2026-09-22): the lifecycle id rides
                        # metadata so a rehydrated card keeps its identity.
                        "card_id": r[7],
                        # REQ-22 (owner report 2026-09-25): the title label rides
                        # metadata too — derived from a bounded preview, never
                        # the body itself.
                        "title": card_title_from_content(r[8]),
                    }
                    for r in rows
                    # Owner bound 2026-09-25: a tool RESULT is not an artifact,
                    # so a stored receipt ({'success': true, ...}) is not offered
                    # for rehydration at all. Rows written before that bound
                    # (conv-151 held four) rendered as prism cards whose body was
                    # raw JSON and whose title was the "Document" fallback — the
                    # "prism cards are rendering with just json output" report.
                    # Not offered = not rendered, and nothing is deleted.
                    if not is_tool_result_envelope(r[8])
                ]
            # Pre-existing bug fixed 2026-09-25: this branch assigned `row`
            # (singular) and then iterated `rows`, so the agent-side full-data
            # read raised UnboundLocalError, was swallowed by the except below,
            # and returned []. The agent could never retrieve its OWN rendered
            # documents by conversation — CT-DOC-3 (REQ-7/T5) was red because of
            # it, and a model that cannot see its earlier cards mints new ones
            # instead (the "prism cards render as raw JSON" shape).
            rows = self._conn.execute(
                "SELECT document_id, conversation_id, fmt, content, variants, "
                "alternatives, trust, revision, source_document_id, sources, har_path, "
                "turn_id, card_id "
                "FROM document_data WHERE conversation_id = ? AND fmt IS NOT 'research' "
                "ORDER BY created_at ASC",
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
                    "card_id": r[12],
                }
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[DocumentDataStore] list_for_conversation failed: %s", exc)
            return []

    def list_by_format(
        self, fmt: str, limit: int = 50, conversation_id: Optional[str] = None
    ) -> list:
        """Metadata-only rows of one ``fmt``, newest first (no content blob).

        The research history reads this: ``variants`` carries a small ``meta``
        dict, so a listing never pays for the record bodies. Never raises.
        """
        try:
            self._settle(any_doc=True)  # any store() this store queued
            sql = (
                "SELECT document_id, conversation_id, variants, created_at "
                "FROM document_data WHERE fmt = ?"
            )
            args: list = [fmt]
            if conversation_id:
                sql += " AND conversation_id = ?"
                args.append(conversation_id)
            sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
            args.append(max(1, min(int(limit), 500)))
            return [
                {
                    "document_id": r[0],
                    "conversation_id": r[1],
                    "variants": json.loads(r[2] or "{}"),
                    "created_at": r[3],
                }
                for r in self._conn.execute(sql, args).fetchall()
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[DocumentDataStore] list_by_format failed: %s", exc)
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
            self._settle(any_doc=True)  # any store() this store queued
            rows = self._conn.execute(
                "SELECT conversation_id, COUNT(*) AS doc_count, MAX(created_at) AS latest "
                "FROM document_data WHERE fmt IS NOT 'research' "
                "GROUP BY conversation_id ORDER BY latest DESC"
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
            app_write(
                self._conn,
                "UPDATE document_data SET variants = ? WHERE document_id = ?",
                (json.dumps(variants, ensure_ascii=False), document_id),
            )
            self._note_pending(document_id)
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
            app_write(
                self._conn,
                "INSERT INTO reformat_edges (from_format, to_format, weight, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(from_format, to_format) DO UPDATE SET "
                "weight = MIN(weight + excluded.weight, 100.0), "
                "updated_at = excluded.updated_at",
                (from_format, to_format, float(amount), time.time()),
            )
            self._note_pending("edges")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[DocumentDataStore] record_reformat failed: %s", exc)

    def get_reformat_edges(self, from_format: Optional[str] = None) -> list:
        """Return reformat edges (from_format, to_format, weight), highest weight first."""
        try:
            self._settle("edges")  # a record_reformat this store queued
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
                # One writer: the excess is computed INSIDE the delete, on the
                # writer thread - a second queued evict then deletes nothing
                # extra (a count read here would be stale once queued). Trim
                # to 90% of the cap: at the cap every store evicted again, a
                # multi-second delete each time on this disk (live 2026-10-04).
                app_write(
                    self._conn,
                    "DELETE FROM document_data WHERE document_id IN ("
                    "SELECT document_id FROM document_data ORDER BY created_at ASC "
                    "LIMIT max(0, (SELECT COUNT(*) FROM document_data) - ?))",
                    (_MAX_DOCUMENTS * 9 // 10,),
                )
                # Cascade to binary bodies. SQLite does not enforce foreign keys
                # unless PRAGMA foreign_keys is on (it is not, per-connection),
                # so the cascade is explicit. Without it the blobs would be the
                # ONLY thing in this store that grows without bound — and being
                # images, they are the rows where that actually costs something.
                app_write(
                    self._conn,
                    "DELETE FROM document_blobs WHERE document_id NOT IN ("
                    "SELECT document_id FROM document_data)",
                )
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
