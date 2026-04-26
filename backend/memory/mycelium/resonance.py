"""
Resonance layer — episode coordinate indexing and resonance-augmented retrieval re-ranking.

EpisodeIndexer: writes a mycelium_episode_index row when an episodic memory is stored,
linking the episode to the session's active coordinate state.

ResonanceScorer: re-ranks cosine-sorted retrieval candidates using coordinate overlap
between the current session and each candidate episode's stored coordinate state.
The 6 non-toolpath RESONANCE_SPACES are used for overlap calculation.
"""

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from .store import CoordinateStore
from .spaces import (
    LANDMARK_MATCH_BONUS,
    RESONANCE_OVERLAP_THRESHOLD,
    RESONANCE_SPACES,
    RESONANCE_WEIGHT_PER_SPACE,
    SUPPRESSION_COVERAGE_THRESHOLD,
)

logger = logging.getLogger(__name__)


def _short_uuid() -> str:
    """12-character UUID prefix."""
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# EpisodeIndexer
# ---------------------------------------------------------------------------

class EpisodeIndexer:
    """
    Links episodic memories to the coordinate state active at storage time (Req 11.1–11.4).

    Writes a `mycelium_episode_index` row for every new episode.
    Failures are silently swallowed — episode storage MUST NOT be blocked.
    """

    def __init__(self, conn: "sqlcipher3.Connection") -> None:
        self._conn = conn

    def index_episode(
        self,
        episode_id: str,
        session_id: str,
        node_ids: Optional[List[str]] = None,
        space_ids: Optional[List[str]] = None,
        landmark_id: Optional[str] = None,
        source_channel: Optional[int] = None,
        coordinate_hash: Optional[str] = None,
    ) -> None:
        """
        Write a mycelium_episode_index row linking an episode to the session's
        current coordinate state (Req 11.1–11.3).

        MUST NOT raise exceptions — all errors are silently logged so that
        episode storage is never blocked by indexing failures.

        Args:
            episode_id:       ID of the newly stored episode.
            session_id:       Current session identifier.
            node_ids:         List of active node_ids for the session. If None,
                              writes an empty list (episode has no Mycelium state).
            space_ids:        List of space_ids covered by the active nodes.
            landmark_id:      Optional landmark active at storage time.
            source_channel:   Optional integer channel level from episode metadata.
            coordinate_hash:  Optional content hash for dedup (computed if not provided).
        """
        try:
            idx_id = _short_uuid()
            nodes_json = json.dumps(node_ids or [])
            spaces_json = json.dumps(space_ids or [])

            if coordinate_hash is None:
                # Simple hash of node_ids for index lookups
                import hashlib
                raw = ",".join(sorted(node_ids or []))
                coordinate_hash = hashlib.md5(raw.encode()).hexdigest()[:24]

            self._conn.execute(
                """
                INSERT OR IGNORE INTO mycelium_episode_index
                    (idx_id, episode_id, session_id, node_ids, space_ids,
                     landmark_id, coordinate_hash, source_channel, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    idx_id,
                    episode_id,
                    session_id,
                    nodes_json,
                    spaces_json,
                    landmark_id,
                    coordinate_hash,
                    source_channel,
                    time.time(),
                ),
            )
            self._conn.commit()

        except Exception as exc:  # noqa: BLE001
            logger.debug("[resonance] index_episode failed (non-fatal): %s", exc)

    def backfill_landmark(self, session_id: str, landmark_id: str) -> None:
        """
        Update all episode_index rows for a session to point to the new landmark (Req 11.4).

        Called after LandmarkIndex.save() so that existing session episodes gain
        a landmark reference retroactively.
        """
        try:
            self._conn.execute(
                """
                UPDATE mycelium_episode_index
                SET landmark_id = ?
                WHERE session_id = ? AND landmark_id IS NULL
                """,
                (landmark_id, session_id),
            )
            self._conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[resonance] backfill_landmark failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# ResonanceScorer
# ---------------------------------------------------------------------------

class ResonanceScorer:
    """
    Re-ranks cosine-sorted retrieval candidates using coordinate overlap (Req 11.5–11.12).

    Uses the 6 RESONANCE_SPACES (all except toolpath) for per-space overlap calculation.
    Failures fall back to cosine-only ranking — resilience is paramount.
    """

    # Expose as class constant so callers can reference it
    RESONANCE_SPACES = RESONANCE_SPACES

    def __init__(
        self,
        conn: "sqlcipher3.Connection",
        store: CoordinateStore,
    ) -> None:
        self._conn = conn
        self._store = store

    def augment_retrieval(
        self,
        session_id: str,
        candidates: List[Dict[str, Any]],
        current_landmark_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Re-rank retrieval candidates using coordinate resonance (Req 11.5–11.10).

        For each candidate:
          1. Look up its mycelium_episode_index record.
          2. Compute resonance_multiplier:
               - For each of the 6 RESONANCE_SPACES:
                   if cosine overlap between the episode's nodes and the current
                   session's nodes in that space > RESONANCE_OVERLAP_THRESHOLD (0.60):
                   add RESONANCE_WEIGHT_PER_SPACE (0.15)
               - If candidate's landmark_id matches current_landmark_id:
                   add LANDMARK_MATCH_BONUS (0.40)
          3. channel_weight from kyudo.CHANNEL_WEIGHTS (lazy import; default 1.0)
          4. final_score = cosine × (1 + resonance_multiplier) × channel_weight
          5. Suppression: success episodes where coverage ratio ≥
             SUPPRESSION_COVERAGE_THRESHOLD (0.70) are marked suppressed=True.
             Failure episodes are NEVER suppressed.

        Falls back to cosine-only ranking if any error occurs.

        Args:
            session_id:           Current session identifier.
            candidates:           List of episode dicts with at minimum keys:
                                    "episode_id": str
                                    "cosine_score": float
                                    "outcome": str ("success", "failure", or other)
                                  Returns the list unchanged if < 1 candidates.
            current_landmark_id:  The landmark currently active for this session.

        Returns:
            The candidates list, each annotated with:
                "resonance_score":     float
                "resonance_multiplier": float
                "suppressed":          bool
                "final_score":         float
            Sorted by final_score DESC (suppressed items ranked last).
        """
        if not candidates:
            return candidates

        try:
            # Load current session's active nodes per space
            session_nodes_by_space = self._load_session_nodes_by_space(session_id)

            for candidate in candidates:
                self._score_candidate(
                    candidate,
                    session_nodes_by_space,
                    current_landmark_id,
                )

            # Sort by final_score DESC, suppressed items last
            candidates.sort(
                key=lambda c: (
                    0 if c.get("suppressed") else 1,
                    c.get("final_score", 0.0),
                ),
                reverse=True,
            )
            return candidates

        except Exception as exc:  # noqa: BLE001
            logger.debug("[resonance] augment_retrieval failed, using cosine fallback: %s", exc)
            # Fallback: annotate with defaults and return cosine-sorted order
            for candidate in candidates:
                candidate.setdefault("resonance_score", 0.0)
                candidate.setdefault("resonance_multiplier", 0.0)
                candidate.setdefault("suppressed", False)
                candidate.setdefault("final_score", candidate.get("cosine_score", 0.0))
            return candidates

    def format_context(
        self,
        successes: List[Dict[str, Any]],
        failures: List[Dict[str, Any]],
    ) -> str:
        """
        Format retrieved episodes into a context string (Req 11.11).

        Suppressed success episodes are omitted.
        Failure episodes are NEVER suppressed (included regardless of suppressed flag).

        Args:
            successes: List of success episode dicts from augment_retrieval.
            failures:  List of failure episode dicts from augment_retrieval.

        Returns:
            Formatted string with success and failure episode summaries.
        """
        lines: List[str] = []

        visible_successes = [
            c for c in successes if not c.get("suppressed", False)
        ]
        if visible_successes:
            lines.append("Past successes:")
            for ep in visible_successes:
                summary = ep.get("summary") or ep.get("episode_id", "unknown")
                score = ep.get("final_score", 0.0)
                lines.append(f"  [{score:.2f}] {summary}")

        if failures:
            lines.append("Past failures (avoid repeating):")
            for ep in failures:  # failures never suppressed
                summary = ep.get("summary") or ep.get("episode_id", "unknown")
                score = ep.get("final_score", 0.0)
                lines.append(f"  [{score:.2f}] {summary}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_session_nodes_by_space(
        self, session_id: str
    ) -> Dict[str, List[List[float]]]:
        """
        Return the current session's active node coordinate vectors, grouped by space_id.

        Uses the session's most-recent episode_index entries to determine active node IDs,
        then fetches their coordinates from mycelium_nodes.
        """
        # Get node_ids from the latest episode_index entry for this session
        cursor = self._conn.execute(
            """
            SELECT node_ids FROM mycelium_episode_index
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (session_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return {}

        try:
            node_ids = json.loads(row[0] or "[]")
        except (json.JSONDecodeError, TypeError):
            return {}

        result: Dict[str, List[List[float]]] = {}
        for node_id in node_ids:
            node = self._store.get_node_by_id(node_id)
            if node and node.space_id in RESONANCE_SPACES:
                result.setdefault(node.space_id, []).append(node.coordinates)

        return result

    def _score_candidate(
        self,
        candidate: Dict[str, Any],
        session_nodes_by_space: Dict[str, List[List[float]]],
        current_landmark_id: Optional[str],
    ) -> None:
        """Annotate a single candidate with resonance scores in-place."""
        cosine = candidate.get("cosine_score", 0.0)

        # Retrieve episode index record
        episode_id = candidate.get("episode_id", "")
        idx_record = self._get_index_record(episode_id)

        resonance_multiplier = 0.0
        channel_weight = 1.0
        suppressed = False

        if idx_record:
            # Per-space coordinate overlap
            try:
                ep_node_ids = json.loads(idx_record.get("node_ids", "[]"))
            except (json.JSONDecodeError, TypeError):
                ep_node_ids = []

            ep_nodes_by_space: Dict[str, List[List[float]]] = {}
            for nid in ep_node_ids:
                node = self._store.get_node_by_id(nid)
                if node and node.space_id in RESONANCE_SPACES:
                    ep_nodes_by_space.setdefault(node.space_id, []).append(node.coordinates)

            for space_id in RESONANCE_SPACES:
                ep_coords = ep_nodes_by_space.get(space_id, [])
                sess_coords = session_nodes_by_space.get(space_id, [])
                if ep_coords and sess_coords:
                    overlap = _space_overlap(ep_coords, sess_coords)
                    if overlap > RESONANCE_OVERLAP_THRESHOLD:
                        resonance_multiplier += RESONANCE_WEIGHT_PER_SPACE

            # Landmark match bonus
            ep_landmark = idx_record.get("landmark_id")
            if (
                ep_landmark
                and current_landmark_id
                and ep_landmark == current_landmark_id
            ):
                resonance_multiplier += LANDMARK_MATCH_BONUS

            # Channel weight (lazy import)
            source_channel = idx_record.get("source_channel")
            if source_channel is not None:
                channel_weight = self._get_channel_weight(source_channel)

            # Suppression: success episodes with high coordinate coverage
            outcome = candidate.get("outcome", "")
            if outcome == "success" and ep_nodes_by_space and session_nodes_by_space:
                coverage = _coverage_ratio(ep_nodes_by_space, session_nodes_by_space)
                if coverage >= SUPPRESSION_COVERAGE_THRESHOLD:
                    suppressed = True
            # Failure episodes are NEVER suppressed (Req 11.9)

        final_score = cosine * (1.0 + resonance_multiplier) * channel_weight

        candidate["resonance_score"] = resonance_multiplier
        candidate["resonance_multiplier"] = resonance_multiplier
        candidate["suppressed"] = suppressed
        candidate["final_score"] = final_score

    def _get_index_record(self, episode_id: str) -> Optional[Dict[str, Any]]:
        """Fetch the most recent episode_index record for an episode_id."""
        cursor = self._conn.execute(
            """
            SELECT idx_id, episode_id, session_id, node_ids, space_ids,
                   landmark_id, coordinate_hash, source_channel
            FROM mycelium_episode_index
            WHERE episode_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (episode_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        keys = ["idx_id", "episode_id", "session_id", "node_ids", "space_ids",
                "landmark_id", "coordinate_hash", "source_channel"]
        return dict(zip(keys, row))

    @staticmethod
    def _get_channel_weight(source_channel: int) -> float:
        """
        Get channel weight for a source_channel integer.

        Lazy-imports kyudo.CHANNEL_WEIGHTS to avoid circular imports.
        Falls back to 1.0 if kyudo is not available.
        """
        try:
            from .kyudo import CHANNEL_WEIGHTS  # noqa: PLC0415
            return CHANNEL_WEIGHTS.get(source_channel, 1.0)
        except ImportError:
            return 1.0


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Compute cosine similarity between two float vectors of equal length."""
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = sum(x * x for x in vec_a) ** 0.5
    mag_b = sum(x * x for x in vec_b) ** 0.5
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


def _space_overlap(
    ep_coords: List[List[float]],
    sess_coords: List[List[float]],
) -> float:
    """
    Compute the maximum cosine similarity between any episode node and any
    session node in a given space.  Returns 0.0 if either list is empty.
    """
    best = 0.0
    for ep_vec in ep_coords:
        for sess_vec in sess_coords:
            sim = _cosine_similarity(ep_vec, sess_vec)
            if sim > best:
                best = sim
    return best


def _coverage_ratio(
    ep_nodes_by_space: Dict[str, List],
    sess_nodes_by_space: Dict[str, List],
) -> float:
    """
    Compute what fraction of the current session's spaces are covered by the
    episode's coordinate state with overlap > RESONANCE_OVERLAP_THRESHOLD.
    """
    session_spaces = [s for s in sess_nodes_by_space if sess_nodes_by_space[s]]
    if not session_spaces:
        return 0.0

    covered = 0
    for space_id in session_spaces:
        ep_coords = ep_nodes_by_space.get(space_id, [])
        sess_coords = sess_nodes_by_space[space_id]
        if ep_coords and _space_overlap(ep_coords, sess_coords) > RESONANCE_OVERLAP_THRESHOLD:
            covered += 1

    return covered / len(session_spaces)
