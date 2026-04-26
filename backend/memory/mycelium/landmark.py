"""
Landmark system — crystallization, activation, conflict resolution, and lifecycle management.

A Landmark is a crystallized memory of a task pattern: a cluster of coordinate nodes + the
traversal sequence that produced a good outcome. Landmarks reduce context retrieval to a
single high-signal reference once a pattern recurs enough times.

Classes:
  Landmark             — dataclass: the in-memory representation of one landmark.
  LandmarkCondenser    — derives a Landmark from a completed session's node set.
  LandmarkIndex        — persistence, activation, nullification, conflict resolution,
                         and edge decay for the landmark graph.
"""

import hashlib
import json
import logging
import struct
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .store import CoordinateStore
from .spaces import (
    LANDMARK_MIN_SCORE,
    LANDMARK_PRUNE_THRESHOLD,
    PERMANENCE_THRESHOLD,
    CLUSTER_MAX_NODES,
)

logger = logging.getLogger(__name__)

# Landmark edge decay rates (Req 8.10)
_DECAY_PERMANENT: float = 0.002     # per day — very stable
_DECAY_NON_PERMANENT: float = 0.005  # per day — still consolidating

# Trust-cap: fraction of cluster nodes from external/untrusted channels that
# blocks crystallisation (Req 15.12)
_TRUST_CAP_FRACTION: float = 0.30

# Source priority for conflict resolution: higher index = higher authority
_SOURCE_PRIORITY: Dict[str, int] = {
    "statement": 0,
    "hardware": 1,
    "behavioral": 2,
}


def _short_uuid() -> str:
    """12-character UUID prefix for landmark IDs."""
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Landmark dataclass
# ---------------------------------------------------------------------------

@dataclass
class Landmark:
    """
    In-memory representation of a crystallized task pattern (Req 8.1).

    `coordinate_cluster` is a list of dicts, each with keys:
        node_id, space_id, coordinates (List[float]), confidence, access_count.
    """

    landmark_id: str
    label: Optional[str]
    task_class: str
    coordinate_cluster: List[Dict[str, Any]]
    traversal_sequence: List[str]   # ordered list of node_ids from the traversal
    cumulative_score: float
    micro_abstract: Optional[bytes]
    micro_abstract_text: Optional[str]
    activation_count: int
    is_permanent: bool
    conversation_ref: Optional[str]
    created_at: float
    last_activated: Optional[float]

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def to_context_string(self) -> str:
        """
        Compact single-line summary for context injection (≤ 50 tokens) (Req 8.2).

        Format:  LANDMARK: class:{task_class} score:{score:.2f} nodes:{n} act:{activation_count}
        """
        n = len(self.coordinate_cluster)
        return (
            f"LANDMARK: class:{self.task_class} "
            f"score:{self.cumulative_score:.2f} "
            f"nodes:{n} "
            f"act:{self.activation_count}"
        )

    def to_remote(self) -> dict:
        """
        Serialise the landmark for transmission to a remote/sub-agent worker (Req 8.3).

        # Privacy contract: remote workers get coordinate structure only,
        # never labels, micro_abstract_text, or conversation_ref.
        """
        return {
            "landmark_id": self.landmark_id,
            "task_class": self.task_class,
            "coordinate_cluster": [
                {k: v for k, v in node.items() if k not in ("label",)}
                for node in self.coordinate_cluster
            ],
            "traversal_sequence": self.traversal_sequence,
            "cumulative_score": self.cumulative_score,
            "activation_count": self.activation_count,
            "is_permanent": self.is_permanent,
        }


# ---------------------------------------------------------------------------
# LandmarkCondenser
# ---------------------------------------------------------------------------

class LandmarkCondenser:
    """
    Derives a Landmark from the current session's traversed node set (Req 8.4–8.7).

    Called at the end of a session once a path outcome has been recorded.
    Returns None when the outcome or score does not meet the threshold.
    """

    def __init__(
        self,
        store: CoordinateStore,
        tokenizer: Any = None,
    ) -> None:
        """
        Args:
            store:     CoordinateStore for reading nodes.
            tokenizer: Optional tokenizer for micro_abstract encoding.
                       Must expose `tokenizer.encode(text) -> List[int]`.
        """
        self._store = store
        self._tokenizer = tokenizer

    def condense(
        self,
        session_id: str,
        cumulative_score: float,
        outcome: str,
        task_entry_label: Optional[str],
        source_channel: Optional[str] = None,
    ) -> Optional["Landmark"]:
        """
        Attempt to crystallise a Landmark from the current session (Req 8.4–8.7).

        Returns None when:
          - cumulative_score < LANDMARK_MIN_SCORE (0.45) (Req 8.5)
          - outcome == "miss" (Req 8.5)
          - > 30% of cluster nodes are EXTERNAL/UNTRUSTED (Req 15.12)

        Args:
            session_id:       Current session ID.
            cumulative_score: Cumulative path score from the traversal.
            outcome:          "hit", "partial", or "miss".
            task_entry_label: Short task description (used for task_class and label).
            source_channel:   Optional source channel level for trust cap check.

        Returns:
            A new Landmark, or None if threshold/trust checks fail.
        """
        if cumulative_score < LANDMARK_MIN_SCORE or outcome == "miss":
            return None

        # Collect all traversed nodes for this session from every space
        candidate_nodes = []
        from .spaces import SPACES
        for space_id in SPACES:
            candidate_nodes.extend(self._store.get_nodes_by_space(space_id))

        if not candidate_nodes:
            return None

        # Sort by access_count DESC and take top CLUSTER_MAX_NODES (6)
        cluster_nodes = sorted(
            candidate_nodes, key=lambda n: n.access_count, reverse=True
        )[:CLUSTER_MAX_NODES]

        # Trust cap: Req 15.12 — if > 30% of cluster nodes are from EXTERNAL/UNTRUSTED channels
        if source_channel is not None:
            untrusted_fraction = self._compute_untrusted_fraction(
                cluster_nodes, source_channel
            )
            if untrusted_fraction > _TRUST_CAP_FRACTION:
                logger.debug(
                    "[landmark] condense: rejected (%.1f%% untrusted > %.0f%% cap)",
                    untrusted_fraction * 100,
                    _TRUST_CAP_FRACTION * 100,
                )
                return None

        # Build coordinate_cluster dicts
        coordinate_cluster = [
            {
                "node_id": n.node_id,
                "space_id": n.space_id,
                "coordinates": n.coordinates,
                "confidence": n.confidence,
                "access_count": n.access_count,
            }
            for n in cluster_nodes
        ]

        # Derive task_class fingerprint from entry label and cluster
        task_class = self._make_task_class(task_entry_label, coordinate_cluster)

        # Encode micro_abstract if tokenizer available
        micro_abstract: Optional[bytes] = None
        micro_abstract_text: Optional[str] = None

        if self._tokenizer is not None and task_entry_label:
            abstract_text = task_entry_label[:200]  # safety cap on input
            micro_abstract_text = abstract_text
            try:
                token_ids = self._tokenizer.encode(abstract_text)[:30]  # cap 30 tokens
                micro_abstract = struct.pack(f">{len(token_ids)}i", *token_ids)
            except Exception as exc:  # noqa: BLE001
                logger.debug("[landmark] micro_abstract encoding failed: %s", exc)

        traversal_sequence = [n.node_id for n in cluster_nodes]

        return Landmark(
            landmark_id=_short_uuid(),
            label=task_entry_label,
            task_class=task_class,
            coordinate_cluster=coordinate_cluster,
            traversal_sequence=traversal_sequence,
            cumulative_score=cumulative_score,
            micro_abstract=micro_abstract,
            micro_abstract_text=micro_abstract_text,
            activation_count=0,
            is_permanent=False,
            conversation_ref=session_id,
            created_at=time.time(),
            last_activated=None,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_task_class(
        task_entry_label: Optional[str],
        cluster: List[Dict],
    ) -> str:
        """
        Derive a short, stable task_class string from the label and cluster shape.

        Uses the label directly when short; falls back to the dominant space name.
        """
        if task_entry_label and len(task_entry_label) <= 32:
            return task_entry_label.lower().replace(" ", "_")[:32]

        # Fallback: dominant space in the cluster
        if cluster:
            spaces = [d.get("space_id", "") for d in cluster]
            dominant = max(set(spaces), key=spaces.count)
            label_slug = ""
            if task_entry_label:
                # Use MD5 prefix as a short disambiguator
                digest = hashlib.md5(task_entry_label.encode("utf-8")).hexdigest()[:6]
                label_slug = f"_{digest}"
            return f"{dominant}_task{label_slug}"

        return "unknown_task"

    @staticmethod
    def _compute_untrusted_fraction(cluster_nodes: list, source_channel: str) -> float:
        """
        Estimate the fraction of cluster nodes that are EXTERNAL/UNTRUSTED.

        Lazy-imports HyphaChannel from kyudo.py to avoid circular imports.
        Returns 0.0 (safe) if kyudo is not available yet.
        """
        try:
            from .kyudo import HyphaChannel  # noqa: PLC0415
            untrusted_levels = {
                HyphaChannel.EXTERNAL,
                HyphaChannel.UNTRUSTED,
            }
            # source_channel is a single string — check if it maps to an untrusted level
            try:
                channel_level = HyphaChannel(source_channel)
                if channel_level in untrusted_levels:
                    # If the whole session is from an untrusted channel, all nodes count
                    return 1.0
            except (ValueError, KeyError):
                pass
            return 0.0
        except ImportError:
            return 0.0


# ---------------------------------------------------------------------------
# LandmarkIndex
# ---------------------------------------------------------------------------

class LandmarkIndex:
    """
    Persistence, activation, conflict resolution, and edge decay for the landmark graph (Req 9.1–9.10).
    """

    def __init__(self, conn: "sqlcipher3.Connection") -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, landmark: Landmark) -> None:
        """
        Persist a Landmark to `mycelium_landmarks` (Req 9.1).

        After writing, auto-connect to existing non-absorbed landmarks whose
        coordinate cluster overlaps ≥ 30% with this one (Req 9.2).
        Landmark edges are written at initial score 0.4.
        """
        self._conn.execute(
            """
            INSERT OR IGNORE INTO mycelium_landmarks
                (landmark_id, label, task_class, coordinate_cluster, traversal_sequence,
                 cumulative_score, micro_abstract, micro_abstract_text, activation_count,
                 is_permanent, conversation_ref, absorbed, created_at, last_activated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL)
            """,
            (
                landmark.landmark_id,
                landmark.label,
                landmark.task_class,
                json.dumps(landmark.coordinate_cluster),
                json.dumps(landmark.traversal_sequence),
                landmark.cumulative_score,
                landmark.micro_abstract,
                landmark.micro_abstract_text,
                landmark.activation_count,
                1 if landmark.is_permanent else 0,
                landmark.conversation_ref,
                landmark.created_at,
            ),
        )
        self._conn.commit()

        # Auto-connect to similar existing landmarks
        self._auto_connect(landmark)

    def _auto_connect(self, landmark: Landmark) -> None:
        """Write landmark edges to all existing non-absorbed landmarks with overlap ≥ 0.30."""
        cursor = self._conn.execute(
            """
            SELECT landmark_id, coordinate_cluster
            FROM mycelium_landmarks
            WHERE absorbed IS NULL AND landmark_id != ?
            """,
            (landmark.landmark_id,),
        )
        rows = cursor.fetchall()

        ids_new = {d["node_id"] for d in landmark.coordinate_cluster if "node_id" in d}

        for other_id, other_cluster_json in rows:
            try:
                other_cluster = json.loads(other_cluster_json)
            except (json.JSONDecodeError, TypeError):
                continue

            ids_other = {d.get("node_id") for d in other_cluster if "node_id" in d}
            overlap = _jaccard(ids_new, ids_other)
            if overlap >= 0.30:
                self._upsert_landmark_edge(
                    landmark.landmark_id, other_id, "similarity", 0.4
                )

    def _upsert_landmark_edge(
        self,
        from_id: str,
        to_id: str,
        edge_type: str,
        initial_score: float,
    ) -> None:
        """Insert a landmark edge, ignoring duplicate pairs."""
        edge_id = _short_uuid()
        now = time.time()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO mycelium_landmark_edges
                (edge_id, from_landmark_id, to_landmark_id, score, edge_type,
                 traversal_count, hit_count, miss_count, created_at, last_traversed)
            VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?, NULL)
            """,
            (edge_id, from_id, to_id, initial_score, edge_type, now),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------

    def activate(self, landmark_id: str) -> None:
        """
        Increment activation_count, update last_activated (Req 9.3).

        When activation_count reaches PERMANENCE_THRESHOLD (8), promote the landmark
        to is_permanent=1 and set confidence=1.0 on all constituent nodes.
        """
        now = time.time()

        # Fetch current state
        cursor = self._conn.execute(
            "SELECT activation_count, coordinate_cluster FROM mycelium_landmarks WHERE landmark_id = ?",
            (landmark_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return

        new_count = row[0] + 1
        coordinate_cluster = row[1]

        is_permanent = 1 if new_count >= PERMANENCE_THRESHOLD else 0

        self._conn.execute(
            """
            UPDATE mycelium_landmarks
            SET activation_count = ?, last_activated = ?, is_permanent = ?
            WHERE landmark_id = ?
            """,
            (new_count, now, is_permanent, landmark_id),
        )

        # Promote constituent nodes to confidence=1.0 on permanence
        if is_permanent and new_count == PERMANENCE_THRESHOLD:
            try:
                cluster = json.loads(coordinate_cluster)
                for node_entry in cluster:
                    node_id = node_entry.get("node_id")
                    if node_id:
                        self._conn.execute(
                            "UPDATE mycelium_nodes SET confidence = 1.0 WHERE node_id = ?",
                            (node_id,),
                        )
            except (json.JSONDecodeError, TypeError):
                pass

        self._conn.commit()

    # ------------------------------------------------------------------
    # Nullification
    # ------------------------------------------------------------------

    def nullify_conversation(self, session_id: str) -> None:
        """
        Clear conversation_ref for all landmarks referencing session_id (Req 9.4).

        Does NOT delete landmarks — the coordinate structure is retained for future
        navigation even after the conversation context has expired.
        """
        self._conn.execute(
            "UPDATE mycelium_landmarks SET conversation_ref = NULL WHERE conversation_ref = ?",
            (session_id,),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Conflict resolution
    # ------------------------------------------------------------------

    def resolve_conflict(
        self,
        space_id: str,
        axis: str,
        value_a: float,
        source_a: str,
        value_b: float,
        source_b: str,
    ) -> float:
        """
        Resolve a conflicting coordinate value from two sources (Req 9.5–9.7).

        Decision order:
          1. Source with higher cumulative landmark evidence wins.
          2. Tie-break: behavioural > hardware > statement (priority order).
          3. Fallback: average of both values.

        The conflict and its resolution are logged to `mycelium_conflicts`.

        Args:
            space_id:  The coordinate space where the conflict was detected.
            axis:      The axis name within that space.
            value_a:   Value from source_a.
            source_a:  Source identifier (e.g. "behavioral", "hardware", "statement").
            value_b:   Value from source_b.
            source_b:  Source identifier for value_b.

        Returns:
            The resolved float value.
        """
        score_a = self._landmark_evidence_score(source_a)
        score_b = self._landmark_evidence_score(source_b)

        if score_a > score_b:
            resolved = value_a
            basis = f"evidence:{source_a}>{source_b}"
        elif score_b > score_a:
            resolved = value_b
            basis = f"evidence:{source_b}>{source_a}"
        else:
            # Evidence tie: apply source priority
            prio_a = _SOURCE_PRIORITY.get(source_a, -1)
            prio_b = _SOURCE_PRIORITY.get(source_b, -1)
            if prio_a >= prio_b:
                resolved = value_a
                basis = f"priority:{source_a}"
            else:
                resolved = value_b
                basis = f"priority:{source_b}"

        # Log to mycelium_conflicts
        conflict_id = _short_uuid()
        self._conn.execute(
            """
            INSERT INTO mycelium_conflicts
                (conflict_id, space_id, axis, value_a, source_a, value_b, source_b,
                 resolved_value, resolution_basis, landmark_ref, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (conflict_id, space_id, axis, value_a, source_a, value_b, source_b,
             resolved, basis, time.time()),
        )
        self._conn.commit()

        return resolved

    def _landmark_evidence_score(self, source: str) -> float:
        """
        Return the total cumulative_score for all non-absorbed landmarks whose
        task_class matches the source label.  Returns 0.0 if none found.
        """
        cursor = self._conn.execute(
            """
            SELECT SUM(cumulative_score) FROM mycelium_landmarks
            WHERE task_class = ? AND absorbed IS NULL
            """,
            (source,),
        )
        row = cursor.fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0

    # ------------------------------------------------------------------
    # Landmark edge decay
    # ------------------------------------------------------------------

    def apply_landmark_decay(self) -> int:
        """
        Apply time-based decay to landmark edges and prune those below
        LANDMARK_PRUNE_THRESHOLD (0.08) (Req 9.8–9.10).

        Decay rates: 0.002/day for permanent landmark edges,
                     0.005/day for non-permanent.

        Returns:
            Number of landmark edges pruned.
        """
        now = time.time()
        pruned = 0

        # Fetch all landmark edges with their from_landmark is_permanent flag
        cursor = self._conn.execute(
            """
            SELECT le.edge_id, le.score, le.last_traversed, lm.is_permanent
            FROM mycelium_landmark_edges le
            JOIN mycelium_landmarks lm ON le.from_landmark_id = lm.landmark_id
            """
        )
        rows = cursor.fetchall()

        for edge_id, score, last_traversed, is_permanent in rows:
            if last_traversed is None:
                continue

            days_idle = (now - last_traversed) / 86400.0
            if days_idle <= 0.0:
                continue

            rate = _DECAY_PERMANENT if is_permanent else _DECAY_NON_PERMANENT
            new_score = score - rate * days_idle

            if new_score < LANDMARK_PRUNE_THRESHOLD:
                self._conn.execute(
                    "DELETE FROM mycelium_landmark_edges WHERE edge_id = ?", (edge_id,)
                )
                pruned += 1
            else:
                self._conn.execute(
                    "UPDATE mycelium_landmark_edges SET score = ? WHERE edge_id = ?",
                    (max(0.0, new_score), edge_id),
                )

        self._conn.commit()
        logger.debug("[landmark] apply_landmark_decay: pruned %d edges", pruned)
        return pruned

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_by_id(self, landmark_id: str) -> Optional[Landmark]:
        """Return a single Landmark by ID, or None if not found."""
        cursor = self._conn.execute(
            """
            SELECT landmark_id, label, task_class, coordinate_cluster,
                   traversal_sequence, cumulative_score, micro_abstract,
                   micro_abstract_text, activation_count, is_permanent,
                   conversation_ref, created_at, last_activated
            FROM mycelium_landmarks WHERE landmark_id = ?
            """,
            (landmark_id,),
        )
        row = cursor.fetchone()
        return self._row_to_landmark(row) if row else None

    def get_all_active(self) -> List[Landmark]:
        """Return all non-absorbed landmarks."""
        cursor = self._conn.execute(
            """
            SELECT landmark_id, label, task_class, coordinate_cluster,
                   traversal_sequence, cumulative_score, micro_abstract,
                   micro_abstract_text, activation_count, is_permanent,
                   conversation_ref, created_at, last_activated
            FROM mycelium_landmarks WHERE absorbed IS NULL
            ORDER BY cumulative_score DESC
            """
        )
        return [self._row_to_landmark(row) for row in cursor.fetchall()]

    @staticmethod
    def _row_to_landmark(row) -> "Landmark":
        (
            landmark_id, label, task_class, coordinate_cluster_json,
            traversal_sequence_json, cumulative_score, micro_abstract,
            micro_abstract_text, activation_count, is_permanent,
            conversation_ref, created_at, last_activated
        ) = row

        try:
            coordinate_cluster = json.loads(coordinate_cluster_json or "[]")
        except (json.JSONDecodeError, TypeError):
            coordinate_cluster = []

        try:
            traversal_sequence = json.loads(traversal_sequence_json or "[]")
        except (json.JSONDecodeError, TypeError):
            traversal_sequence = []

        return Landmark(
            landmark_id=landmark_id,
            label=label,
            task_class=task_class,
            coordinate_cluster=coordinate_cluster,
            traversal_sequence=traversal_sequence,
            cumulative_score=cumulative_score,
            micro_abstract=micro_abstract,
            micro_abstract_text=micro_abstract_text,
            activation_count=activation_count,
            is_permanent=bool(is_permanent),
            conversation_ref=conversation_ref,
            created_at=created_at,
            last_activated=last_activated,
        )


    # ------------------------------------------------------------------
    # Cross-project landmark bridges (Req future — PiN layer)
    # ------------------------------------------------------------------

    def add_bridge(
        self,
        local_landmark_id: str,
        remote_landmark_name: str,
        remote_project_id: Optional[str] = None,
        remote_instance_id: Optional[str] = None,
        remote_landmark_id: Optional[str] = None,
        confidence: float = 1.0,
        bridge_type: str = "equivalent",
        notes: Optional[str] = None,
    ) -> str:
        """
        Register a cross-project landmark bridge.

        A bridge maps a local landmark to an equivalent (or similar) landmark
        in another project or IRIS instance. IRIS uses bridges to bootstrap
        faster when entering a new project — familiar patterns activate
        immediately rather than re-crystallising from scratch.

        bridge_type: 'equivalent' | 'similar' | 'inverse'
        """
        bridge_id = _short_uuid()
        now = time.time()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO mycelium_landmark_bridges
                (bridge_id, local_landmark_id, remote_project_id, remote_instance_id,
                 remote_landmark_name, remote_landmark_id, confidence, bridge_type,
                 notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (bridge_id, local_landmark_id, remote_project_id, remote_instance_id,
             remote_landmark_name, remote_landmark_id, confidence, bridge_type,
             notes, now),
        )
        self._conn.commit()
        logger.debug(
            "[landmark] bridge registered: %s → %s (%s, conf=%.2f)",
            local_landmark_id, remote_landmark_name, bridge_type, confidence,
        )
        return bridge_id

    def get_bridges(self, local_landmark_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Return all landmark bridges, optionally filtered to a single local landmark.
        Results ordered by confidence DESC.
        """
        if local_landmark_id:
            cursor = self._conn.execute(
                "SELECT * FROM mycelium_landmark_bridges "
                "WHERE local_landmark_id = ? ORDER BY confidence DESC",
                (local_landmark_id,),
            )
        else:
            cursor = self._conn.execute(
                "SELECT * FROM mycelium_landmark_bridges ORDER BY confidence DESC"
            )
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def find_bridge(
        self,
        remote_landmark_name: str,
        remote_instance_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Look up the highest-confidence bridge for a remote landmark name.
        Returns the bridge dict, or None if no match.
        """
        if remote_instance_id:
            cursor = self._conn.execute(
                "SELECT * FROM mycelium_landmark_bridges "
                "WHERE remote_landmark_name = ? AND remote_instance_id = ? "
                "ORDER BY confidence DESC LIMIT 1",
                (remote_landmark_name, remote_instance_id),
            )
        else:
            cursor = self._conn.execute(
                "SELECT * FROM mycelium_landmark_bridges "
                "WHERE remote_landmark_name = ? "
                "ORDER BY confidence DESC LIMIT 1",
                (remote_landmark_name,),
            )
        row = cursor.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _jaccard(set_a: set, set_b: set) -> float:
    """Jaccard similarity: |A ∩ B| / |A ∪ B|. Returns 0.0 for empty inputs."""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0
