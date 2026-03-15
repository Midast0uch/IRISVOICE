"""
Episodic Memory Store for IRIS.

Stores task episodes with vector embeddings for similarity search.
Uses SQLCipher for encryption and numpy for vector similarity calculation.
"""

import json
import logging
import uuid
import math
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from backend.memory.db import open_encrypted_memory, Connection
from backend.memory.embedding import EmbeddingService

logger = logging.getLogger(__name__)


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
    """
    
    # Threshold for considering episodes as duplicates (cosine similarity)
    DEDUP_THRESHOLD = 0.95
    
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
                    stored_embedding = json.loads(row[1])
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
        """Initialize database schema for episodes."""
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
            
            CREATE INDEX IF NOT EXISTS idx_ep_session ON episodes(session_id);
            CREATE INDEX IF NOT EXISTS idx_ep_type ON episodes(outcome_type);
            CREATE INDEX IF NOT EXISTS idx_ep_score ON episodes(outcome_score);
            CREATE INDEX IF NOT EXISTS idx_ep_node ON episodes(node_id);
            CREATE INDEX IF NOT EXISTS idx_ep_origin ON episodes(origin);
            CREATE INDEX IF NOT EXISTS idx_ep_timestamp ON episodes(timestamp);
        """)
        self.db.commit()
        logger.debug("[EpisodicStore] Schema initialized")
    
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
        embedding_blob = json.dumps(embedding).encode()
        
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
                stored_embedding = json.loads(row[4])
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
                stored_embedding = json.loads(row[3])
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
