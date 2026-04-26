"""
Episodic Memory Store for IRIS.

Stores task episodes with vector embeddings for similarity search.
Uses SQLCipher for encryption and numpy for vector similarity calculation.
Embeddings are stored as binary (struct.pack format) with transparent JSON fallback.
"""

import json
import logging
import uuid
import math
import struct
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from backend.memory.db import open_encrypted_memory, Connection
from backend.memory.embedding import EmbeddingService

logger = logging.getLogger(__name__)


def _pack_embedding(vec: List[float]) -> bytes:
    """Pack embedding vector as binary (little-endian 32-bit floats)."""
    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack_embedding(blob: bytes) -> List[float]:
    """
    Unpack embedding from binary format.
    Falls back to JSON for legacy rows (backward compatible).
    Returns empty list on error.
    """
    if not blob:
        return []
    # JSON fallback for legacy rows
    if blob[:1] in (b"[", b"{"):
        try:
            return json.loads(blob)
        except Exception:
            return []
    # Binary format
    try:
        return list(struct.unpack(f"<{len(blob)//4}f", blob))
    except Exception:
        return []


@dataclass
class Episode:
    """A task episode to be stored in episodic memory."""
    session_id: str
    task_summary: str
    full_content: str
    tool_sequence: List[Dict[str, Any]]
    outcome_type: str  # success|failure|partial|abandoned|clarification
    failure_reason: Optional[str] = None
    user_corrected: bool = False
    user_confirmed: bool = False
    duration_ms: int = 0
    tokens_used: int = 0
    model_id: str = ""
    source_channel: str = "websocket"
    node_id: str = "local"  # TORUS: Dilithium3 pubkey at Phase 6
    origin: str = "local"   # TORUS: 'local' | 'torus_task'


class EpisodicStore:
    """
    Persistent vector-searchable store of every completed task.

    Uses numpy-based cosine similarity for vector search within SQLCipher encrypted database.
    Includes deduplication to prevent duplicate episode storage.

    Domain 1.6 Option B — Pacman context fragmentation:
      fragment_and_store()      — digest raw turns/DER outputs into vector chunks
      retrieve_context_chunks() — semantic retrieval replaces rolling window
    """

    # Threshold for considering episodes as duplicates (cosine similarity)
    DEDUP_THRESHOLD = 0.95

    # ── Pacman fragmentation constants (Option B / PACMAN.md) ────────────────
    # Max chars per chunk ≈ 512 tokens (4 chars/token). Overlap keeps sentences whole.
    _CHUNK_MAX_CHARS: int = 2048
    _CHUNK_OVERLAP:   int = 200   # trailing chars re-included in next chunk
    _CHUNK_MIN_CHARS: int = 50    # skip near-empty slivers

    # Lower than episode DEDUP so we deduplicate near-identical fragment repeats
    # but still allow similar-but-distinct chunks (e.g. same topic, different details).
    _FRAG_DEDUP_THRESHOLD: float = 0.92

    # Age-weighted scoring: recency weight decays over this many hours.
    # At 24h a chunk contributes 50% of its max recency bonus.
    _RECENCY_HALF_LIFE_HOURS: float = 24.0

    # Fraction of final score that comes from recency vs. cosine similarity.
    # 0.20 = 20% recency bonus, 80% semantic match.
    _RECENCY_WEIGHT: float = 0.20

    # Chunks retrieved this many times are promoted to crystallization candidates.
    _CRYSTALLIZE_THRESHOLD: int = 5

    # Zone vocabulary (PACMAN.md Dimension 1)
    _ZONE_TRUSTED:   str = "trusted"    # user's own conversation
    _ZONE_TOOL:      str = "tool"       # DER / tool execution outputs
    _ZONE_REFERENCE: str = "reference"  # external content (future)
    _ZONE_SYSTEM:    str = "system"     # IRIS internals (future)

    # Default zone per chunk_type
    _CHUNK_TYPE_ZONE: dict = {
        "context_fragment": "trusted",
        "der_output":       "tool",
    }
    
    def __init__(self, db_path: str, biometric_key: bytes):
        """
        Initialize EpisodicStore.
        
        Args:
            db_path: Path to the SQLite database file
            biometric_key: 32-byte encryption key
        """
        self.db_path = db_path
        self.biometric_key = biometric_key
        self._db: Optional[Connection] = None
        self._embed = EmbeddingService()

        # Optional Mycelium reference — injected by MemoryInterface after init (Req 13.6)
        self._mycelium: Any = None

        # Initialize schema on first access
        self._init_schema()
        logger.info("[EpisodicStore] Initialized")
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        Calculate cosine similarity between two vectors.
        
        Args:
            vec1: First vector
            vec2: Second vector
            
        Returns:
            Cosine similarity (-1 to 1, where 1 is identical)
        """
        if len(vec1) != len(vec2):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def _find_duplicate(self, embedding: List[float]) -> Optional[Tuple[str, float]]:
        """
        Find if a similar episode already exists.

        Args:
            embedding: The embedding to check

        Returns:
            Tuple of (episode_id, similarity) if duplicate found, None otherwise
        """
        try:
            # Get all episode embeddings (with limit for performance)
            rows = self.db.execute("""
                SELECT id, embedding, outcome_score
                FROM episodes
                ORDER BY timestamp DESC
                LIMIT 100
            """).fetchall()

            best_match = None
            best_similarity = 0.0

            for row in rows:
                try:
                    stored_embedding = _unpack_embedding(row[1])
                    if not stored_embedding:
                        continue
                    similarity = self._cosine_similarity(embedding, stored_embedding)

                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_match = (row[0], similarity)

                    if similarity >= self.DEDUP_THRESHOLD:
                        return (row[0], similarity)
                except (json.JSONDecodeError, TypeError):
                    continue

            return best_match if best_match and best_match[1] >= self.DEDUP_THRESHOLD else None

        except Exception as e:
            logger.warning(f"[EpisodicStore] Error finding duplicate: {e}")
            return None
    
    @property
    def db(self) -> Connection:
        """Get database connection (lazy initialization)."""
        if self._db is None:
            self._db = open_encrypted_memory(self.db_path, self.biometric_key)
        return self._db
    
    def _init_schema(self) -> None:
        """Initialize database schema for episodes and context chunks."""
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS episodes (
                id             TEXT PRIMARY KEY,
                session_id     TEXT NOT NULL,
                task_summary   TEXT NOT NULL,
                full_content   TEXT,
                tool_sequence  TEXT,
                outcome_score  REAL DEFAULT 0.0,
                outcome_type   TEXT NOT NULL,
                failure_reason TEXT,
                user_corrected INTEGER DEFAULT 0,
                user_confirmed INTEGER DEFAULT 0,
                duration_ms    INTEGER DEFAULT 0,
                tokens_used    INTEGER DEFAULT 0,
                model_id       TEXT DEFAULT '',
                source_channel TEXT DEFAULT 'websocket',
                node_id        TEXT DEFAULT 'local',
                origin         TEXT DEFAULT 'local',
                embedding      BLOB,
                timestamp      TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_ep_session   ON episodes(session_id);
            CREATE INDEX IF NOT EXISTS idx_ep_type      ON episodes(outcome_type);
            CREATE INDEX IF NOT EXISTS idx_ep_score     ON episodes(outcome_score);
            CREATE INDEX IF NOT EXISTS idx_ep_node      ON episodes(node_id);
            CREATE INDEX IF NOT EXISTS idx_ep_origin    ON episodes(origin);
            CREATE INDEX IF NOT EXISTS idx_ep_timestamp ON episodes(timestamp);

            -- Option B: Pacman context fragmentation store (PACMAN.md §Biological Fragmentation)
            -- Raw conversation turns and DER outputs are chunked + embedded here.
            -- retrieve_context_chunks() pulls semantically relevant fragments back
            -- into the context window instead of a blind rolling-window crop.
            --
            -- Zone taxonomy matches PACMAN.md §Dimension 1:
            --   trusted   — user's own conversation turns (default)
            --   tool      — verified DER/tool execution outputs
            --   reference — external content (future)
            --   system    — IRIS internals (future)
            --
            -- retrieval_count tracks usage frequency for the crystallization pathway:
            -- frequently-retrieved chunks contribute to landmark formation.
            CREATE TABLE IF NOT EXISTS context_chunks (
                id               TEXT PRIMARY KEY,
                session_id       TEXT NOT NULL,
                chunk_type       TEXT NOT NULL DEFAULT 'context_fragment',
                zone             TEXT NOT NULL DEFAULT 'trusted',
                content          TEXT NOT NULL,
                embedding        BLOB,
                retrieval_count  INTEGER NOT NULL DEFAULT 0,
                timestamp        TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_chunk_session  ON context_chunks(session_id);
            CREATE INDEX IF NOT EXISTS idx_chunk_type     ON context_chunks(chunk_type);
            CREATE INDEX IF NOT EXISTS idx_chunk_zone     ON context_chunks(zone);
            CREATE INDEX IF NOT EXISTS idx_chunk_ts       ON context_chunks(timestamp);
            CREATE INDEX IF NOT EXISTS idx_chunk_usage    ON context_chunks(retrieval_count);
        """)
        self.db.commit()
        self._migrate_chunk_schema()
        logger.debug("[EpisodicStore] Schema initialized")

    def _migrate_chunk_schema(self) -> None:
        """Add columns introduced in the Pacman lifecycle upgrade to existing DBs.

        SQLite does not support IF NOT EXISTS on ALTER TABLE, so we probe the
        column list and only issue ALTER TABLE when the column is absent.
        """
        existing = {
            row[1]
            for row in self.db.execute(
                "PRAGMA table_info(context_chunks)"
            ).fetchall()
        }
        migrations = [
            ("zone",            "TEXT NOT NULL DEFAULT 'trusted'"),
            ("retrieval_count", "INTEGER NOT NULL DEFAULT 0"),
        ]
        for col, col_def in migrations:
            if col not in existing:
                try:
                    self.db.execute(
                        f"ALTER TABLE context_chunks ADD COLUMN {col} {col_def}"
                    )
                    self.db.commit()
                    logger.info(f"[EpisodicStore] Migrated context_chunks: added {col}")
                except Exception as e:
                    logger.warning(f"[EpisodicStore] Migration warning ({col}): {e}")
    
    def store(self, episode: Episode, score: float) -> str:
        """
        Persist an episode with its embedding.

        Implements deduplication: if a similar episode already exists
        (cosine similarity >= DEDUP_THRESHOLD), it will be updated instead
        of creating a duplicate.

        Args:
            episode: The episode to store
            score: Outcome score (0.0-1.0)

        Returns:
            The ID of the stored episode (new or existing)
        """
        # Generate embedding for task summary
        embedding = self._embed.encode(episode.task_summary)
        embedding_blob = _pack_embedding(embedding)

        # Check for duplicates
        duplicate = self._find_duplicate(embedding)
        if duplicate:
            episode_id, similarity = duplicate
            # Update existing episode with new information
            self.db.execute("""
                UPDATE episodes SET
                    task_summary = ?,
                    full_content = full_content || ?,
                    outcome_score = MAX(outcome_score, ?),
                    user_corrected = MAX(user_corrected, ?),
                    user_confirmed = MAX(user_confirmed, ?),
                    timestamp = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                episode.task_summary,
                f"\n---\n{episode.full_content}",
                score,
                int(episode.user_corrected),
                int(episode.user_confirmed),
                episode_id
            ))
            self.db.commit()
            logger.debug(f"[EpisodicStore] Updated duplicate episode {episode_id[:8]}... (similarity: {similarity:.3f})")
            return episode_id

        # No duplicate found - insert new episode
        episode_id = str(uuid.uuid4())

        self.db.execute("""
            INSERT INTO episodes
            (id, session_id, task_summary, full_content, tool_sequence,
             outcome_score, outcome_type, failure_reason, user_corrected,
             user_confirmed, duration_ms, tokens_used, model_id,
             source_channel, node_id, origin, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            episode_id,
            episode.session_id,
            episode.task_summary,
            episode.full_content,
            json.dumps(episode.tool_sequence),
            score,
            episode.outcome_type,
            episode.failure_reason,
            int(episode.user_corrected),
            int(episode.user_confirmed),
            episode.duration_ms,
            episode.tokens_used,
            episode.model_id,
            episode.source_channel,
            episode.node_id,
            episode.origin,
            embedding_blob
        ))
        self.db.commit()

        # Mycelium: index this episode against the current coordinate state (Req 13.6)
        if self._mycelium is not None:
            try:
                self._mycelium.episode_indexer.index_episode(
                    episode_id=episode_id,
                    session_id=episode.session_id,
                    source_channel=None,  # HyphaChannel wired in Phase 9
                )
            except Exception:
                pass  # MUST NOT block episode storage

        logger.debug(f"[EpisodicStore] Stored new episode {episode_id[:8]}... (score: {score})")
        return episode_id
    
    def retrieve_similar(
        self,
        task: str,
        limit: int = 3,
        min_score: float = 0.6
    ) -> List[Dict[str, Any]]:
        """
        Find top-N semantically similar successful episodes.
        
        Uses cosine similarity on embeddings for semantic search.
        
        Args:
            task: The task query
            limit: Maximum number of results
            min_score: Minimum outcome score to include
        
        Returns:
            List of similar episode dictionaries, sorted by similarity
        """
        # Get embedding for query
        query_embedding = self._embed.encode(task)
        
        # Get all successful episodes with embeddings
        rows = self.db.execute("""
            SELECT id, task_summary, tool_sequence, outcome_score, embedding
            FROM episodes
            WHERE outcome_score >= ? AND outcome_type = 'success'
        """, (min_score,)).fetchall()
        
        # Calculate similarity for each episode
        scored_episodes = []
        for row in rows:
            try:
                stored_embedding = _unpack_embedding(row[4])
                if not stored_embedding:
                    continue
                similarity = self._cosine_similarity(query_embedding, stored_embedding)
                scored_episodes.append((similarity, {
                    "id": row[0],
                    "task_summary": row[1],
                    "tool_sequence": json.loads(row[2] or "[]"),
                    "outcome_score": row[3],
                    "similarity": round(similarity, 3)
                }))
            except (json.JSONDecodeError, TypeError):
                continue
        
        # Sort by similarity (highest first) and select top N
        scored_episodes.sort(key=lambda x: x[0], reverse=True)
        results = [ep for _, ep in scored_episodes[:limit]]

        # Mycelium: augment with coordinate resonance (Req 11.6–11.8)
        if self._mycelium is not None and results:
            try:
                # Annotate with cosine_score and outcome fields for resonance scoring
                for ep in results:
                    ep.setdefault("cosine_score", ep.get("similarity", 0.0))
                    ep.setdefault("outcome", "success")
                    ep.setdefault("episode_id", ep.get("id", ""))
                results = self._mycelium.resonance_scorer.augment_retrieval(
                    session_id="",   # No active session context here; best-effort
                    candidates=results,
                )
            except Exception:
                pass  # Fallback to cosine-only ranking on any error

        logger.debug(f"[EpisodicStore] Found {len(results)} similar episodes for task: {task[:50]}...")
        return results
    
    def retrieve_failures(
        self,
        task: str,
        limit: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Find top-N semantically similar failure episodes for warnings.
        
        Uses cosine similarity to find failures most relevant to current task.
        
        Args:
            task: The task query
            limit: Maximum number of results
        
        Returns:
            List of failure episode dictionaries, sorted by similarity
        """
        # Get embedding for query
        query_embedding = self._embed.encode(task)
        
        # Get all failures with embeddings
        rows = self.db.execute("""
            SELECT id, task_summary, failure_reason, embedding
            FROM episodes
            WHERE outcome_type = 'failure'
        """).fetchall()
        
        # Calculate similarity for each failure
        scored_failures = []
        for row in rows:
            try:
                stored_embedding = _unpack_embedding(row[3])
                if not stored_embedding:
                    continue
                similarity = self._cosine_similarity(query_embedding, stored_embedding)
                scored_failures.append((similarity, {
                    "task_summary": row[1],
                    "failure_reason": row[2],
                    "similarity": round(similarity, 3)
                }))
            except (json.JSONDecodeError, TypeError):
                continue
        
        # Sort by similarity (highest first) and return top N
        scored_failures.sort(key=lambda x: x[0], reverse=True)
        
        results = [ep for _, ep in scored_failures[:limit]]
        
        logger.debug(f"[EpisodicStore] Found {len(results)} similar failures for task: {task[:50]}...")
        return results
    
    def assemble_episodic_context(self, task: str) -> str:
        """
        Format episodic context for injection into prompts.
        
        Args:
            task: The current task
        
        Returns:
            Formatted episodic context string
        """
        successes = self.retrieve_similar(task, limit=3, min_score=0.6)
        failures = self.retrieve_failures(task, limit=2)

        # Mycelium: use resonance-aware format_context which omits suppressed successes
        # and always includes failure warnings (Req 11.11)
        if self._mycelium is not None:
            try:
                # Annotate failure candidates for resonance scorer
                for ep in failures:
                    ep.setdefault("cosine_score", ep.get("similarity", 0.0))
                    ep.setdefault("outcome", "failure")
                    ep.setdefault("episode_id", ep.get("id", ""))
                    ep.setdefault("summary", f"{ep.get('task_summary', '')} — {ep.get('failure_reason', '')}")
                for ep in successes:
                    ep.setdefault("summary", ep.get("task_summary", ""))
                return self._mycelium.resonance_scorer.format_context(successes, failures)
            except Exception:
                pass  # Fallback to plain format below

        # Plain format (used when Mycelium is not available)
        parts = []
        if successes:
            parts.append("RELEVANT PAST SUCCESSES:")
            for ep in successes:
                parts.append(f"  - {ep['task_summary']} (score: {ep['outcome_score']})")
        if failures:
            parts.append("WARNINGS FROM PAST FAILURES:")
            for ep in failures:
                parts.append(f"  - {ep['task_summary']}: {ep['failure_reason']}")
        return "\n".join(parts)
    
    # ── Option B: Pacman fragmentation ───────────────────────────────────────

    def fragment_and_store(
        self,
        content: str,
        session_id: str,
        chunk_type: str = "context_fragment",
        zone: Optional[str] = None,
    ) -> List[str]:
        """
        Digest raw text into overlapping vector chunks and store in context_chunks.

        This is the Pacman mechanism (PACMAN.md §Biological Fragmentation):
        content is split into fixed-size chunks with overlap, each embedded and
        stored with zone classification matching PACMAN.md Dimension 1.
        Duplicates at >= _FRAG_DEDUP_THRESHOLD are silently skipped.
        Uses batch insert (executemany) for efficiency.

        Args:
            content:    Raw text to fragment.
            session_id: Session that produced this content.
            chunk_type: 'context_fragment' (conversation) | 'der_output' (DER step).
            zone:       PACMAN zone override. Defaults: context_fragment → 'trusted',
                        der_output → 'tool'.  Pass explicitly to override.

        Returns:
            List of stored chunk IDs (empty on error or empty input).
        """
        _zone = zone or self._CHUNK_TYPE_ZONE.get(chunk_type, self._ZONE_TRUSTED)
        if not content or not content.strip():
            return []

        text = content.strip()
        # Split into overlapping windows
        chunks: List[str] = []
        step = self._CHUNK_MAX_CHARS - self._CHUNK_OVERLAP
        if len(text) <= self._CHUNK_MAX_CHARS:
            chunks = [text]
        else:
            pos = 0
            while pos < len(text):
                chunk = text[pos: pos + self._CHUNK_MAX_CHARS]
                if len(chunk) >= self._CHUNK_MIN_CHARS:
                    chunks.append(chunk)
                pos += step

        stored_ids: List[str] = []
        batch_rows: List[Tuple] = []

        for chunk in chunks:
            chunk = chunk.strip()
            if len(chunk) < self._CHUNK_MIN_CHARS:
                continue

            embedding = self._embed.encode(chunk)

            # Dedup: compare against recent chunks in this session
            try:
                rows = self.db.execute(
                    """SELECT id, embedding FROM context_chunks
                       WHERE session_id = ? AND chunk_type = ?
                       ORDER BY timestamp DESC LIMIT 50""",
                    (session_id, chunk_type),
                ).fetchall()
                is_dup = False
                for row in rows:
                    try:
                        stored_emb = _unpack_embedding(row[1])
                        if stored_emb and self._cosine_similarity(embedding, stored_emb) >= self._FRAG_DEDUP_THRESHOLD:
                            is_dup = True
                            stored_ids.append(row[0])
                            break
                    except Exception:
                        continue
                if is_dup:
                    continue
            except Exception:
                pass  # dedup failure is non-fatal; store anyway

            chunk_id = str(uuid.uuid4())
            embedding_blob = _pack_embedding(embedding)
            batch_rows.append((chunk_id, session_id, chunk_type, _zone, chunk, embedding_blob))
            stored_ids.append(chunk_id)

        # Batch insert all non-duplicate chunks
        if batch_rows:
            try:
                with self.db:
                    self.db.executemany(
                        """INSERT INTO context_chunks
                           (id, session_id, chunk_type, zone, content, embedding)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        batch_rows
                    )
            except Exception as e:
                logger.warning(f"[EpisodicStore] batch chunk store error: {e}")
                # Fallback: store individually
                for row in batch_rows:
                    try:
                        self.db.execute(
                            """INSERT INTO context_chunks
                               (id, session_id, chunk_type, zone, content, embedding)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            row
                        )
                        self.db.commit()
                    except Exception as e2:
                        logger.warning(f"[EpisodicStore] individual chunk store error: {e2}")

        logger.debug(
            f"[EpisodicStore] fragment_and_store: {len(stored_ids)} chunks "
            f"stored for session={session_id[:8]} type={chunk_type}"
        )
        return stored_ids

    def retrieve_context_chunks(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 6,
        min_similarity: float = 0.25,
        chunk_types: Optional[List[str]] = None,
        zones: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Retrieve the most semantically relevant context chunks for a query.

        Implements PACMAN.md metabolism:
          - Semantic match (cosine similarity) — 80% of final score
          - Recency bonus (age-weighted decay) — 20% of final score
            Chunks older than _RECENCY_HALF_LIFE_HOURS contribute half
            their maximum recency bonus.  Decay is continuous, not stepped.
          - retrieval_count incremented on every hit so high-frequency chunks
            can be promoted through the crystallization pathway.

        Args:
            query:          Current query to match against stored fragments.
            session_id:     Filter to a specific session (None = all sessions).
            limit:          Max number of chunks to return.
            min_similarity: Minimum *cosine* similarity threshold (applied before
                            recency weighting so low-similarity stale chunks are
                            filtered out regardless of how recent they are).
            chunk_types:    Filter by chunk_type; None = all types.
            zones:          Filter by zone (e.g. ['trusted','tool']); None = all.

        Returns:
            List of chunk content strings ranked by descending combined score.
        """
        if not query:
            return []

        query_embedding = self._embed.encode(query)

        where_clauses: List[str] = []
        params_list: List[Any] = []
        if session_id:
            where_clauses.append("session_id = ?")
            params_list.append(session_id)
        if chunk_types:
            placeholders = ",".join("?" * len(chunk_types))
            where_clauses.append(f"chunk_type IN ({placeholders})")
            params_list.extend(chunk_types)
        if zones:
            placeholders = ",".join("?" * len(zones))
            where_clauses.append(f"zone IN ({placeholders})")
            params_list.extend(zones)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        try:
            rows = self.db.execute(
                f"SELECT id, content, embedding, timestamp FROM context_chunks "
                f"{where_sql} ORDER BY timestamp DESC LIMIT 200",
                params_list,
            ).fetchall()
        except Exception as e:
            logger.warning(f"[EpisodicStore] chunk retrieve error: {e}")
            return []

        import datetime as _dt

        now_utc = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)

        scored: List[Tuple[float, str, str]] = []  # (combined_score, content, id)
        for row in rows:
            try:
                stored_emb = _unpack_embedding(row[2])
                if not stored_emb:
                    continue
                sim = self._cosine_similarity(query_embedding, stored_emb)
                if sim < min_similarity:
                    continue

                # Recency weight: exponential decay, half-life = _RECENCY_HALF_LIFE_HOURS
                try:
                    ts = _dt.datetime.fromisoformat(row[3].replace("Z", "+00:00").rstrip("+00:00").split("+")[0])
                    age_hours = max(0.0, (now_utc - ts).total_seconds() / 3600.0)
                except Exception:
                    age_hours = 0.0
                recency = 1.0 / (1.0 + age_hours / self._RECENCY_HALF_LIFE_HOURS)

                combined = (
                    sim     * (1.0 - self._RECENCY_WEIGHT)
                    + recency * self._RECENCY_WEIGHT
                )
                scored.append((combined, row[1], row[0]))
            except Exception:
                continue

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:limit]
        results = [content for _, content, _ in top]

        # Increment retrieval_count for returned chunks (usage tracking for decay/crystallization)
        retrieved_ids = [chunk_id for _, _, chunk_id in top]
        if retrieved_ids:
            try:
                placeholders = ",".join("?" * len(retrieved_ids))
                self.db.execute(
                    f"UPDATE context_chunks SET retrieval_count = retrieval_count + 1 "
                    f"WHERE id IN ({placeholders})",
                    retrieved_ids,
                )
                self.db.commit()

                # Crystallization pathway: log chunks that have hit the threshold
                # so Mycelium can promote them in the next distillation pass.
                # (Full Mycelium integration is Phase 2 — this provides the signal.)
                if self._mycelium is not None:
                    try:
                        for _, content, chunk_id in top:
                            row_count = self.db.execute(
                                "SELECT retrieval_count FROM context_chunks WHERE id = ?",
                                (chunk_id,),
                            ).fetchone()
                            if row_count and row_count[0] >= self._CRYSTALLIZE_THRESHOLD:
                                self._mycelium.episode_indexer.index_episode(
                                    episode_id=chunk_id,
                                    session_id=session_id or "",
                                    source_channel=None,
                                )
                    except Exception:
                        pass  # never block retrieval on crystallization signal failure
            except Exception as e:
                logger.warning(f"[EpisodicStore] retrieval_count update error: {e}")

        logger.debug(
            f"[EpisodicStore] retrieve_context_chunks: {len(results)}/{len(rows)} "
            f"chunks (sim>={min_similarity}) for query={query[:40]!r}"
        )
        return results

    def cleanup_stale_chunks(
        self,
        session_id: Optional[str] = None,
        max_age_hours: float = 72.0,
        min_retrievals: int = 0,
    ) -> int:
        """
        Pacman decay: remove chunks that are old AND have low usage.

        PACMAN.md says coordinates "decay when unused." This method
        prunes context_chunks that have not been retrieved (retrieval_count
        <= min_retrievals) and are older than max_age_hours.

        Chunks adjacent to crystallization candidates (retrieval_count >=
        _CRYSTALLIZE_THRESHOLD) are never pruned regardless of age.

        Returns:
            Number of rows deleted.
        """
        where_clauses = [
            "retrieval_count <= ?",
            "datetime(timestamp) < datetime('now', ? || ' hours')",
            "retrieval_count < ?",  # never prune crystallization candidates
        ]
        params: List[Any] = [
            min_retrievals,
            f"-{max_age_hours}",
            self._CRYSTALLIZE_THRESHOLD,
        ]
        if session_id:
            where_clauses.append("session_id = ?")
            params.append(session_id)

        try:
            cursor = self.db.execute(
                f"DELETE FROM context_chunks WHERE {' AND '.join(where_clauses)}",
                params,
            )
            self.db.commit()
            deleted = cursor.rowcount
            if deleted:
                logger.info(
                    f"[EpisodicStore] Pacman decay: pruned {deleted} stale chunks "
                    f"(age>{max_age_hours}h, retrievals<={min_retrievals})"
                )
            return deleted
        except Exception as e:
            logger.warning(f"[EpisodicStore] cleanup_stale_chunks error: {e}")
            return 0

    def get_stats(self) -> Dict[str, Any]:
        """
        Get memory health statistics.
        
        Returns:
            Dictionary with episode statistics
        """
        row = self.db.execute("""
            SELECT COUNT(*), AVG(outcome_score),
                   SUM(CASE WHEN outcome_type='success' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN outcome_type='failure' THEN 1 ELSE 0 END)
            FROM episodes
        """).fetchone()
        
        return {
            "total_episodes": row[0],
            "avg_score": round(row[1] or 0, 3),
            "successes": row[2],
            "failures": row[3]
        }
    
    def get_recent_for_distillation(
        self,
        hours: int = 8,
        min_episodes: int = 5
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get recent episodes for distillation process.
        
        Args:
            hours: How many hours back to look
            min_episodes: Minimum episodes required
        
        Returns:
            List of recent episodes or None if not enough
        """
        rows = self.db.execute("""
            SELECT task_summary, outcome_type, outcome_score, timestamp
            FROM episodes
            WHERE timestamp > datetime('now', '-' || ? || ' hours')
            ORDER BY timestamp DESC
        """, (hours,)).fetchall()
        
        if len(rows) < min_episodes:
            return None
        
        return [
            {
                "task_summary": row[0],
                "outcome_type": row[1],
                "outcome_score": row[2],
                "timestamp": row[3]
            }
            for row in rows
        ]
    
    def get_crystallisation_candidates(
        self,
        min_uses: int = 5,
        min_avg_score: float = 0.7
    ) -> List[Dict[str, Any]]:
        """
        Find tool sequences eligible for skill crystallisation.
        
        Args:
            min_uses: Minimum number of uses
            min_avg_score: Minimum average score
        
        Returns:
            List of candidate tool sequences
        """
        # Group by tool_sequence and find candidates
        rows = self.db.execute("""
            SELECT tool_sequence, COUNT(*) as uses, AVG(outcome_score) as avg_score
            FROM episodes
            WHERE tool_sequence IS NOT NULL AND tool_sequence != '[]'
            GROUP BY tool_sequence
            HAVING uses >= ? AND avg_score >= ?
        """, (min_uses, min_avg_score)).fetchall()
        
        return [
            {
                "tool_sequence": json.loads(row[0]),
                "uses": row[1],
                "avg_score": round(row[2], 3)
            }
            for row in rows
        ]
