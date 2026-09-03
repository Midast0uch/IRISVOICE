"""
Reindex Manager for IRIS Memory — resumable background re-embedding (Wave 3).

Transitions persisted embeddings from one backend to another (e.g. bge-m3 → lfm)
without taking the memory offline. During a migration, retrieval methods perform
dual-read: the query is embedded with BOTH backends, each space is queried only
against rows with a matching ``embedding_backend``, and results are merged.

Crash safety:
  - Write the new vector FIRST, update ``embedding_backend`` SECOND.
    If a crash occurs between the two writes the row still has the OLD backend
    and will be retried on resume.  No row is ever "migrated without a vector."
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

from backend.memory.db import open_encrypted_memory, Connection
from backend.memory.embedding import (
    EmbeddingService,
    compare_embeddings,
    CrossSpaceComparisonError,
    BACKEND_BGE,
)

logger = logging.getLogger(__name__)

STATE_FILE = None  # set by init_manager so tests can override

# ── Helpers ──────────────────────────────────────────────────────────────────

def _pack_embedding(vec: List[float]) -> bytes:
    import struct
    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack_embedding(blob: bytes) -> List[float]:
    if not blob:
        return []
    if blob[:1] in (b"[", b"{"):
        try:
            return json.loads(blob)
        except Exception:
            return []
    import struct
    try:
        return list(struct.unpack(f"<{len(blob)//4}f", blob))
    except Exception:
        return []


# ── Module-level singleton ───────────────────────────────────────────────────

_manager: Optional["ReindexManager"] = None


def get_reindex_manager() -> Optional["ReindexManager"]:
    """Return the global ReindexManager instance, if initialised."""
    return _manager


def init_reindex_manager(
    db_path: str,
    biometric_key: bytes,
    state_file: Optional[str] = None,
) -> "ReindexManager":
    """Initialise (or return existing) global ReindexManager singleton."""
    global _manager
    if _manager is None:
        _manager = ReindexManager(db_path, biometric_key, state_file=state_file)
    return _manager


def reset_reindex_manager() -> None:
    """Clear the global singleton (for testing)."""
    global _manager
    mgr = _manager
    if mgr is not None:
        mgr.stop()
    _manager = None


# ── ReindexManager ───────────────────────────────────────────────────────────

class ReindexManager:
    """
    Resumable background re-embedding worker with dual-read search.

    State machine: idle → running → interrupted|complete → idle (on reset).
    The worker is a daemon thread; it stops when the process exits.
    """

    def __init__(
        self,
        db_path: str,
        biometric_key: bytes,
        state_file: Optional[str] = None,
    ) -> None:
        self._db_path = db_path
        self._biometric_key = biometric_key
        self._state_file = (
            state_file or os.path.join(os.path.dirname(db_path), ".reindex_state.json")
        )

        self._lock = threading.Lock()
        self._event = threading.Event()  # stop signal
        self._thread: Optional[threading.Thread] = None

        # Current migration parameters
        self._from_backend: str = ""
        self._to_backend: str = ""
        self._last_row_id: Optional[str] = None
        self._total_rows: int = 0
        self._migrated_rows: int = 0
        self._state: str = "idle"

        self._load_state()

    # ── Public API ───────────────────────────────────────────────────────────

    def start(self, from_backend: str, to_backend: str) -> None:
        """Launch a re-index migration. Idempotent if already running."""
        with self._lock:
            if self._state == "running":
                logger.info("[ReindexManager] start called while already running; no-op")
                return
            self._from_backend = from_backend
            self._to_backend = to_backend
            self._last_row_id = None
            self._migrated_rows = 0
            self._total_rows = 0
            self._state = "running"
            self._event.clear()
            self._save_state()

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(
            "[ReindexManager] started migration %r -> %r",
            from_backend, to_backend,
        )

    def stop(self) -> None:
        """Signal the worker to stop and wait briefly."""
        self._event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        with self._lock:
            if self._state == "running":
                self._state = "interrupted"
                self._save_state()

    def resume(self) -> None:
        """Resume an interrupted migration from last known position."""
        with self._lock:
            prev_state = self._state
            if prev_state == "running":
                logger.info("[ReindexManager] resume called while already running; no-op")
                return
            if prev_state not in ("interrupted",) and self._last_row_id is not None:
                # Also allow resume from a previously-started-but-not-finished state
                pass
            if not self._from_backend or not self._to_backend:
                logger.info("[ReindexManager] resume: no previous migration found")
                return
            self._state = "running"
            self._event.clear()
            self._save_state()

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(
            "[ReindexManager] resumed migration %r -> %r from row %s",
            self._from_backend, self._to_backend, self._last_row_id,
        )

    def progress(self) -> Dict[str, Any]:
        """Return migration progress snapshot."""
        with self._lock:
            return {
                "total_rows": self._total_rows,
                "migrated_rows": self._migrated_rows,
                "from_backend": self._from_backend,
                "to_backend": self._to_backend,
                "state": self._state,
                "last_row_id": self._last_row_id,
            }

    # ── Dual-read search (called from EpisodicStore during migration) ────────

    def search_episodes(
        self,
        query: str,
        limit: int = 3,
        min_score: float = 0.6,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Dual-read search over episodes across both vector spaces."""
        with self._lock:
            backends = [b for b in (self._from_backend, self._to_backend) if b]

        svc = EmbeddingService()
        db = open_encrypted_memory(self._db_path, self._biometric_key)
        try:
            results: List[Tuple[float, Dict[str, Any]]] = []
            for backend in backends:
                vec = svc.encode_with_backend(query, backend)
                if vec is None:
                    logger.debug("[ReindexManager] backend %r unavailable; skip space", backend)
                    continue

                sql = """SELECT id, task_summary, tool_sequence, outcome_score,
                                embedding, embedding_backend
                         FROM episodes
                         WHERE outcome_score >= ? AND outcome_type = 'success'
                           AND embedding_backend = ?"""
                params: List[Any] = [min_score, backend]
                if session_id:
                    sql += " AND session_id = ?"
                    params.append(session_id)

                for row in db.execute(sql, params).fetchall():
                    stored_vec = _unpack_embedding(row[4])
                    if not stored_vec:
                        continue
                    try:
                        sim = compare_embeddings(vec, backend, stored_vec, row[5] or BACKEND_BGE)
                    except CrossSpaceComparisonError:
                        continue
                    results.append((sim, {
                        "id": row[0],
                        "task_summary": row[1],
                        "tool_sequence": json.loads(row[2] or "[]"),
                        "outcome_score": row[3],
                        "similarity": round(sim, 3),
                    }))

            results.sort(key=lambda x: x[0], reverse=True)
            return [ep for _, ep in results[:limit]]
        finally:
            db.close()

    def search_failures(
        self,
        query: str,
        limit: int = 2,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Dual-read search over failure episodes across both vector spaces."""
        with self._lock:
            backends = [b for b in (self._from_backend, self._to_backend) if b]

        svc = EmbeddingService()
        db = open_encrypted_memory(self._db_path, self._biometric_key)
        try:
            results: List[Tuple[float, Dict[str, Any]]] = []
            for backend in backends:
                vec = svc.encode_with_backend(query, backend)
                if vec is None:
                    continue

                sql = """SELECT id, task_summary, failure_reason,
                                embedding, embedding_backend
                         FROM episodes
                         WHERE outcome_type = 'failure'
                           AND embedding_backend = ?"""
                params: List[Any] = [backend]
                if session_id:
                    sql += " AND session_id = ?"
                    params.append(session_id)

                for row in db.execute(sql, params).fetchall():
                    stored_vec = _unpack_embedding(row[3])
                    if not stored_vec:
                        continue
                    try:
                        sim = compare_embeddings(vec, backend, stored_vec, row[4] or BACKEND_BGE)
                    except CrossSpaceComparisonError:
                        continue
                    results.append((sim, {
                        "task_summary": row[1],
                        "failure_reason": row[2],
                        "similarity": round(sim, 3),
                    }))

            results.sort(key=lambda x: x[0], reverse=True)
            return [ep for _, ep in results[:limit]]
        finally:
            db.close()

    def search_chunks(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 6,
        min_similarity: float = 0.25,
        chunk_types: Optional[List[str]] = None,
        zones: Optional[List[str]] = None,
        max_context_tokens: Optional[int] = None,
    ) -> List[str]:
        """Dual-read search over context chunks across both vector spaces."""
        with self._lock:
            backends = [b for b in (self._from_backend, self._to_backend) if b]

        svc = EmbeddingService()
        db = open_encrypted_memory(self._db_path, self._biometric_key)
        try:
            results: List[Tuple[float, str, str]] = []

            for backend in backends:
                vec = svc.encode_with_backend(query, backend)
                if vec is None:
                    continue

                where = ["embedding_backend = ?"]
                params: List[Any] = [backend]
                if session_id:
                    where.append("session_id = ?")
                    params.append(session_id)
                if chunk_types:
                    placeholders = ",".join("?" * len(chunk_types))
                    where.append(f"chunk_type IN ({placeholders})")
                    params.extend(chunk_types)
                if zones:
                    placeholders = ",".join("?" * len(zones))
                    where.append(f"zone IN ({placeholders})")
                    params.extend(zones)

                sql = (
                    f"SELECT id, content, embedding, timestamp, embedding_backend "
                    f"FROM context_chunks WHERE {' AND '.join(where)} "
                    f"ORDER BY timestamp DESC LIMIT 200"
                )

                for row in db.execute(sql, params).fetchall():
                    stored_vec = _unpack_embedding(row[2])
                    if not stored_vec:
                        continue
                    try:
                        sim = compare_embeddings(vec, backend, stored_vec, row[4] or BACKEND_BGE)
                    except CrossSpaceComparisonError:
                        continue
                    if sim < min_similarity:
                        continue

                    import datetime as _dt
                    try:
                        ts = _dt.datetime.fromisoformat(
                            row[3].replace("Z", "+00:00").rstrip("+00:00").split("+")[0]
                        )
                        age_hours = max(0.0, (_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) - ts).total_seconds() / 3600.0)
                    except Exception:
                        age_hours = 0.0
                    recency = 1.0 / (1.0 + age_hours / 24.0)

                    combined = sim * 0.8 + recency * 0.2
                    results.append((combined, row[1], row[0]))

            results.sort(key=lambda x: x[0], reverse=True)
            top = results[:limit]

            if max_context_tokens is not None and max_context_tokens > 0:
                kept = []
                used = 0
                for score, content, cid in top:
                    tokens = max(1, len(content) // 4)
                    if used + tokens > max_context_tokens:
                        break
                    kept.append((score, content, cid))
                    used += tokens
                top = kept

            return [content for _, content, _ in top]
        finally:
            db.close()

    # ── Worker implementation ────────────────────────────────────────────────

    def _run(self) -> None:
        """Background worker: iterate rows, re-embed, migrate one by one."""
        svc = EmbeddingService()
        db = open_encrypted_memory(self._db_path, self._biometric_key)
        try:
            self._count_total(db)
            self._process_episodes(svc, db)
            if not self._event.is_set():
                self._process_chunks(svc, db)

            with self._lock:
                if not self._event.is_set():
                    self._state = "complete"
                else:
                    self._state = "interrupted"
                self._save_state()
            logger.info("[ReindexManager] migration finished, state=%s", self._state)
        except Exception as exc:
            logger.error("[ReindexManager] worker crashed: %s", exc)
            with self._lock:
                self._state = "interrupted"
                self._save_state()
        finally:
            db.close()

    def _count_total(self, db) -> None:
        """Count rows with embeddings that could be migrated."""
        with self._lock:
            be = self._to_backend
            ep = db.execute(
                "SELECT COUNT(*) FROM episodes WHERE embedding IS NOT NULL"
            ).fetchone()[0]
            cc = db.execute(
                "SELECT COUNT(*) FROM context_chunks WHERE embedding IS NOT NULL"
            ).fetchone()[0]
            self._total_rows = ep + cc

    def _process_episodes(self, svc: EmbeddingService, db) -> None:
        while not self._event.is_set():
            with self._lock:
                last_id = self._last_row_id
                to_backend = self._to_backend

            if last_id:
                rows = db.execute(
                    """SELECT id, task_summary, embedding, embedding_backend
                       FROM episodes
                       WHERE id > ? AND embedding IS NOT NULL
                       ORDER BY id LIMIT 10""",
                    (last_id,),
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT id, task_summary, embedding, embedding_backend
                       FROM episodes
                       WHERE embedding IS NOT NULL
                       ORDER BY id LIMIT 10"""
                ).fetchall()

            if not rows:
                break  # done with episodes

            for row in rows:
                if self._event.is_set():
                    return
                row_id, text, _, current_backend = row
                current_backend = current_backend or BACKEND_BGE

                if current_backend == to_backend:
                    with self._lock:
                        self._last_row_id = row_id
                        self._migrated_rows += 1
                        self._save_state()
                    continue

                # Re-embed with the target backend
                new_vec = svc.encode_with_backend(text, to_backend)
                if new_vec is None:
                    logger.warning(
                        "[ReindexManager] backend %r unavailable; skip episode %s",
                        to_backend, row_id,
                    )
                    with self._lock:
                        self._last_row_id = row_id
                        self._migrated_rows += 1
                        self._save_state()
                    continue

                # CRASH-SAFE: write vector first
                db.execute(
                    "UPDATE episodes SET embedding = ? WHERE id = ?",
                    (_pack_embedding(new_vec), row_id),
                )
                db.commit()

                # Then mark migrated
                db.execute(
                    "UPDATE episodes SET embedding_backend = ? WHERE id = ?",
                    (to_backend, row_id),
                )
                db.commit()

                with self._lock:
                    self._last_row_id = row_id
                    self._migrated_rows += 1
                    self._save_state()

    def _process_chunks(self, svc: EmbeddingService, db) -> None:
        """Migrate context_chunks using a separate row-id counter."""
        # The last_row_id is reused, with a prefix convention to separate
        # episodes from chunks. After episodes finish, we start a fresh sweep.
        with self._lock:
            self._last_row_id = None  # reset for chunk sweep

        while not self._event.is_set():
            with self._lock:
                last_id = self._last_row_id
                to_backend = self._to_backend

            if last_id:
                rows = db.execute(
                    """SELECT id, content, embedding, embedding_backend
                       FROM context_chunks
                       WHERE id > ? AND embedding IS NOT NULL
                       ORDER BY id LIMIT 10""",
                    (last_id,),
                ).fetchall()
            else:
                rows = db.execute(
                    """SELECT id, content, embedding, embedding_backend
                       FROM context_chunks
                       WHERE embedding IS NOT NULL
                       ORDER BY id LIMIT 10"""
                ).fetchall()

            if not rows:
                break  # done with chunks

            for row in rows:
                if self._event.is_set():
                    return
                row_id, text, _, current_backend = row
                current_backend = current_backend or BACKEND_BGE

                if current_backend == to_backend:
                    with self._lock:
                        self._last_row_id = row_id
                        self._migrated_rows += 1
                        self._save_state()
                    continue

                new_vec = svc.encode_with_backend(text, to_backend)
                if new_vec is None:
                    with self._lock:
                        self._last_row_id = row_id
                        self._migrated_rows += 1
                        self._save_state()
                    continue

                # CRASH-SAFE: write vector first
                db.execute(
                    "UPDATE context_chunks SET embedding = ? WHERE id = ?",
                    (_pack_embedding(new_vec), row_id),
                )
                db.commit()

                # Then mark migrated
                db.execute(
                    "UPDATE context_chunks SET embedding_backend = ? WHERE id = ?",
                    (to_backend, row_id),
                )
                db.commit()

                with self._lock:
                    self._last_row_id = row_id
                    self._migrated_rows += 1
                    self._save_state()

    # ── State persistence ───────────────────────────────────────────────────

    def _save_state(self) -> None:
        """Persist migration state to a JSON file for crash recovery."""
        try:
            d = os.path.dirname(self._state_file)
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            with open(self._state_file, "w") as f:
                json.dump({
                    "from_backend": self._from_backend,
                    "to_backend": self._to_backend,
                    "last_row_id": self._last_row_id,
                    "total_rows": self._total_rows,
                    "migrated_rows": self._migrated_rows,
                    "state": self._state,
                }, f)
        except Exception as exc:
            logger.warning("[ReindexManager] state save failed: %s", exc)

    def _load_state(self) -> None:
        """Restore migration state from JSON file (if any)."""
        if not os.path.isfile(self._state_file):
            return
        try:
            with open(self._state_file, "r") as f:
                data = json.load(f)
            self._from_backend = data.get("from_backend", "")
            self._to_backend = data.get("to_backend", "")
            self._last_row_id = data.get("last_row_id")
            self._total_rows = data.get("total_rows", 0)
            self._migrated_rows = data.get("migrated_rows", 0)
            s = data.get("state", "idle")
            # If state was running at crash time, mark as interrupted for resume
            self._state = "interrupted" if s == "running" else s
            logger.info(
                "[ReindexManager] loaded state: %r from %r -> %r (row=%s, %d/%d)",
                self._state, self._from_backend, self._to_backend,
                self._last_row_id, self._migrated_rows, self._total_rows,
            )
        except Exception as exc:
            logger.warning("[ReindexManager] state load failed: %s", exc)
