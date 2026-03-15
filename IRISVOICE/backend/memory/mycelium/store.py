"""
CoordinateStore — all node, edge, and traversal persistence for the Mycelium layer.

Dataclasses for in-memory graph objects (CoordNode, CoordEdge, MemoryPath) and the
CoordinateStore class that handles every read and write to the mycelium_nodes,
mycelium_edges, and mycelium_traversals tables.

All float coordinate arrays are struct-packed (big-endian floats) on write and
unpacked on read — never stored as JSON.
"""

import json
import logging
import math
import struct
import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# Deduplication threshold: nodes within this Euclidean distance in the same
# space are treated as the same node (Req 3.1). Context space uses the stricter
# per-axis project_id guard from Req 4.25 in addition.
_NODE_DEDUP_DISTANCE: float = 0.05

# Context space project_id axis index and its stricter merge guard (Req 4.25)
_CONTEXT_SPACE_ID = "context"
_CONTEXT_PROJECT_ID_AXIS: int = 0          # project_id is axes[0] in context space
_CONTEXT_PROJECT_ID_MAX_DIFF: float = 0.10  # must be <= this to allow merge


# ---------------------------------------------------------------------------
# Helper: pack / unpack float arrays
# ---------------------------------------------------------------------------

def _pack_coords(coords: List[float]) -> bytes:
    """Pack a list of floats into a big-endian binary blob (Req 2.2)."""
    n = len(coords)
    return struct.pack(f">{n}f", *coords)


def _unpack_coords(blob: bytes) -> List[float]:
    """Unpack a big-endian binary blob back to a list of floats."""
    n = len(blob) // 4  # 4 bytes per float
    return list(struct.unpack(f">{n}f", blob))


def _euclidean(a: List[float], b: List[float]) -> float:
    """Euclidean distance between two float vectors. Returns inf on mismatch."""
    if len(a) != len(b):
        return float("inf")
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _short_uuid() -> str:
    """12-character UUID prefix used as node_id (Req 3.2)."""
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CoordNode:
    """In-memory representation of one mycelium_nodes row."""

    node_id: str
    space_id: str
    coordinates: List[float]
    label: Optional[str]
    confidence: float
    created_at: float
    updated_at: float
    access_count: int
    last_accessed: Optional[float]

    def distance_to(self, other_coords: List[float]) -> float:
        """
        Euclidean distance to another coordinate vector.

        Returns float('inf') if the dimension count differs.
        """
        return _euclidean(self.coordinates, other_coords)


@dataclass
class CoordEdge:
    """In-memory representation of one mycelium_edges row."""

    edge_id: str
    from_node_id: str
    to_node_id: str
    score: float
    edge_type: str
    traversal_count: int
    hit_count: int
    miss_count: int
    decay_rate: float
    created_at: float
    last_traversed: Optional[float]


@dataclass
class MemoryPath:
    """A resolved coordinate path returned from graph traversal."""

    nodes: List[CoordNode]
    cumulative_score: float
    token_encoding: str
    spaces_covered: List[str]
    traversal_id: str


# ---------------------------------------------------------------------------
# CoordinateStore
# ---------------------------------------------------------------------------

class CoordinateStore:
    """
    All read/write access to the mycelium node, edge, and traversal tables.

    Takes the open, shared SQLCipher connection — never opens its own.
    One instance is created by MyceliumInterface and shared internally.
    """

    def __init__(self, conn: "sqlcipher3.Connection") -> None:
        """
        Initialise the store with the shared database connection.

        Args:
            conn: Open SQLCipher connection to data/memory.db.
                  MUST be the shared connection — never pass a db_path here.
        """
        self._conn = conn

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    def upsert_node(
        self,
        space_id: str,
        coordinates: List[float],
        label: Optional[str],
        confidence: float,
    ) -> CoordNode:
        """
        Insert or update a coordinate node.

        For all spaces: if an existing node in the same space is within
        Euclidean distance 0.05, update its coordinates, label, and confidence
        rather than inserting a duplicate (Req 3.1).

        For the context space only: two nodes MUST NOT be merged when
        |project_id_a - project_id_b| > 0.10, regardless of their full
        Euclidean distance (Req 4.25). Only when the project_id axes are
        within 0.10 does the standard distance check apply.

        Coordinates are stored as a struct-packed float BLOB (Req 2.2).

        Returns:
            The upserted CoordNode (either updated existing or newly created).
        """
        now = time.time()
        existing = self._find_dedup_candidate(space_id, coordinates)

        if existing is not None:
            # Update in-place: weighted-average coordinates, max confidence
            new_coords = [
                (a + b) / 2.0 for a, b in zip(existing.coordinates, coordinates)
            ]
            new_confidence = max(existing.confidence, confidence)
            new_label = label if label is not None else existing.label

            self._conn.execute(
                """
                UPDATE mycelium_nodes
                SET coordinates = ?, label = ?, confidence = ?, updated_at = ?
                WHERE node_id = ?
                """,
                (_pack_coords(new_coords), new_label, new_confidence, now, existing.node_id),
            )
            self._conn.commit()

            return CoordNode(
                node_id=existing.node_id,
                space_id=space_id,
                coordinates=new_coords,
                label=new_label,
                confidence=new_confidence,
                created_at=existing.created_at,
                updated_at=now,
                access_count=existing.access_count,
                last_accessed=existing.last_accessed,
            )

        # No nearby node — insert new (Req 3.2: 12-char UUID prefix)
        node_id = _short_uuid()
        self._conn.execute(
            """
            INSERT INTO mycelium_nodes
                (node_id, space_id, coordinates, label, confidence,
                 created_at, updated_at, access_count, last_accessed)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL)
            """,
            (node_id, space_id, _pack_coords(coordinates), label, confidence, now, now),
        )
        self._conn.commit()

        return CoordNode(
            node_id=node_id,
            space_id=space_id,
            coordinates=coordinates,
            label=label,
            confidence=confidence,
            created_at=now,
            updated_at=now,
            access_count=0,
            last_accessed=None,
        )

    def _find_dedup_candidate(
        self, space_id: str, coordinates: List[float]
    ) -> Optional[CoordNode]:
        """
        Find the nearest existing node in the same space within the dedup threshold.

        Returns None if no node is close enough, or if context space project_id
        guard blocks the merge.
        """
        nodes = self.get_nodes_by_space(space_id)
        best: Optional[CoordNode] = None
        best_dist = float("inf")

        for node in nodes:
            dist = node.distance_to(coordinates)
            if dist < best_dist:
                best_dist = dist
                best = node

        if best is None or best_dist > _NODE_DEDUP_DISTANCE:
            return None

        # Context space: additional project_id axis guard (Req 4.25)
        if space_id == _CONTEXT_SPACE_ID:
            if len(best.coordinates) > _CONTEXT_PROJECT_ID_AXIS and len(coordinates) > _CONTEXT_PROJECT_ID_AXIS:
                pid_diff = abs(
                    best.coordinates[_CONTEXT_PROJECT_ID_AXIS]
                    - coordinates[_CONTEXT_PROJECT_ID_AXIS]
                )
                if pid_diff > _CONTEXT_PROJECT_ID_MAX_DIFF:
                    return None  # Different projects — do not merge

        return best

    def nearest_node(
        self, space_id: str, coordinates: List[float]
    ) -> Optional[CoordNode]:
        """
        Return the closest node in the given space, or None if the space is empty.

        Scans all nodes in the space and returns the one with minimum Euclidean
        distance to the given coordinates (Req 3.3).
        """
        nodes = self.get_nodes_by_space(space_id)
        if not nodes:
            return None

        return min(nodes, key=lambda n: n.distance_to(coordinates))

    def get_nodes_by_space(self, space_id: str) -> List[CoordNode]:
        """
        Return all nodes in the given space, ordered by access_count DESC (Req 3.4).
        """
        cursor = self._conn.execute(
            """
            SELECT node_id, space_id, coordinates, label, confidence,
                   created_at, updated_at, access_count, last_accessed
            FROM mycelium_nodes
            WHERE space_id = ?
            ORDER BY access_count DESC
            """,
            (space_id,),
        )
        return [self._row_to_node(row) for row in cursor.fetchall()]

    def get_node_by_id(self, node_id: str) -> Optional[CoordNode]:
        """Return a single node by its node_id, or None if not found."""
        cursor = self._conn.execute(
            """
            SELECT node_id, space_id, coordinates, label, confidence,
                   created_at, updated_at, access_count, last_accessed
            FROM mycelium_nodes
            WHERE node_id = ?
            """,
            (node_id,),
        )
        row = cursor.fetchone()
        return self._row_to_node(row) if row else None

    def record_access(self, node_id: str) -> None:
        """
        Increment access_count and set last_accessed to now (Req 3.5).
        """
        self._conn.execute(
            """
            UPDATE mycelium_nodes
            SET access_count = access_count + 1, last_accessed = ?
            WHERE node_id = ?
            """,
            (time.time(), node_id),
        )
        self._conn.commit()

    def delete_node(self, node_id: str) -> None:
        """Delete a node by ID. Caller must handle orphaned edges first."""
        self._conn.execute(
            "DELETE FROM mycelium_nodes WHERE node_id = ?", (node_id,)
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    def get_outbound_edges(
        self, node_id: str, min_score: float = 0.0
    ) -> List[CoordEdge]:
        """
        Return all outbound edges from node_id with score >= min_score,
        ordered by score DESC (Req 3.6).
        """
        cursor = self._conn.execute(
            """
            SELECT edge_id, from_node_id, to_node_id, score, edge_type,
                   traversal_count, hit_count, miss_count, decay_rate,
                   created_at, last_traversed
            FROM mycelium_edges
            WHERE from_node_id = ? AND score >= ?
            ORDER BY score DESC
            """,
            (node_id, min_score),
        )
        return [self._row_to_edge(row) for row in cursor.fetchall()]

    def get_edge_by_id(self, edge_id: str) -> Optional[CoordEdge]:
        """Return a single edge by its edge_id, or None if not found."""
        cursor = self._conn.execute(
            """
            SELECT edge_id, from_node_id, to_node_id, score, edge_type,
                   traversal_count, hit_count, miss_count, decay_rate,
                   created_at, last_traversed
            FROM mycelium_edges
            WHERE edge_id = ?
            """,
            (edge_id,),
        )
        row = cursor.fetchone()
        return self._row_to_edge(row) if row else None

    def update_edge_score(self, edge_id: str, delta: float) -> None:
        """
        Apply a score delta to the given edge, clamping the result to [0.0, 1.0].

        Also updates traversal_count and last_traversed (Req 3.7).
        """
        cursor = self._conn.execute(
            "SELECT score FROM mycelium_edges WHERE edge_id = ?", (edge_id,)
        )
        row = cursor.fetchone()
        if row is None:
            logger.warning("[store] update_edge_score: edge not found: %s", edge_id)
            return

        new_score = max(0.0, min(1.0, row[0] + delta))
        self._conn.execute(
            """
            UPDATE mycelium_edges
            SET score = ?, traversal_count = traversal_count + 1, last_traversed = ?
            WHERE edge_id = ?
            """,
            (new_score, time.time(), edge_id),
        )
        self._conn.commit()

    def upsert_edge(
        self,
        from_node_id: str,
        to_node_id: str,
        edge_type: str,
        initial_score: float,
    ) -> str:
        """
        Insert a new edge between two nodes, or silently ignore if it already
        exists (INSERT OR IGNORE — Req 3.8).

        Returns the edge_id (existing or newly created).
        """
        # Check if edge already exists
        cursor = self._conn.execute(
            """
            SELECT edge_id FROM mycelium_edges
            WHERE from_node_id = ? AND to_node_id = ?
            """,
            (from_node_id, to_node_id),
        )
        row = cursor.fetchone()
        if row:
            return row[0]

        edge_id = _short_uuid()
        now = time.time()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO mycelium_edges
                (edge_id, from_node_id, to_node_id, score, edge_type,
                 traversal_count, hit_count, miss_count, decay_rate,
                 created_at, last_traversed)
            VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0.005, ?, NULL)
            """,
            (edge_id, from_node_id, to_node_id, initial_score, edge_type, now),
        )
        self._conn.commit()
        return edge_id

    def delete_edge(self, edge_id: str) -> None:
        """Delete an edge by ID (used by EdgeScorer prune and MapManager)."""
        self._conn.execute(
            "DELETE FROM mycelium_edges WHERE edge_id = ?", (edge_id,)
        )
        self._conn.commit()

    def get_all_edges(self) -> List[CoordEdge]:
        """Return all edges — used by EdgeScorer.apply_decay()."""
        cursor = self._conn.execute(
            """
            SELECT edge_id, from_node_id, to_node_id, score, edge_type,
                   traversal_count, hit_count, miss_count, decay_rate,
                   created_at, last_traversed
            FROM mycelium_edges
            """
        )
        return [self._row_to_edge(row) for row in cursor.fetchall()]

    def repoint_edges(self, old_node_id: str, new_node_id: str) -> None:
        """
        Re-point all edges that reference old_node_id to new_node_id.

        Used by MapManager.condense() after merging a node into its survivor.
        Skips self-loops that would be created by the re-point.
        """
        # Re-point outbound edges (from_node_id)
        self._conn.execute(
            """
            UPDATE mycelium_edges
            SET from_node_id = ?
            WHERE from_node_id = ? AND to_node_id != ?
            """,
            (new_node_id, old_node_id, new_node_id),
        )
        # Re-point inbound edges (to_node_id)
        self._conn.execute(
            """
            UPDATE mycelium_edges
            SET to_node_id = ?
            WHERE to_node_id = ? AND from_node_id != ?
            """,
            (new_node_id, old_node_id, new_node_id),
        )
        # Remove self-loops and duplicate edges that the re-point created
        self._conn.execute(
            "DELETE FROM mycelium_edges WHERE from_node_id = to_node_id"
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Traversal logging
    # ------------------------------------------------------------------

    def log_traversal(
        self,
        session_id: str,
        task_summary: Optional[str],
        path_node_ids: List[str],
        path_score: Optional[float],
        outcome: Optional[str],
        tokens_saved: Optional[int],
        delta_compressed: int = 0,
    ) -> str:
        """
        Write a traversal record to mycelium_traversals (Req 3.9).

        Args:
            session_id:       Session that generated this traversal.
            task_summary:     Short text description of the task (may be None).
            path_node_ids:    Ordered list of node IDs in the traversal path.
            path_score:       Cumulative score of the path (may be None).
            outcome:          One of "hit", "partial", "miss" (may be None).
            tokens_saved:     Estimated tokens saved vs. full prose header.
            delta_compressed: 0 = full baseline path; 1 = delta-only entry.

        Returns:
            traversal_id of the written record.
        """
        traversal_id = _short_uuid()
        self._conn.execute(
            """
            INSERT INTO mycelium_traversals
                (traversal_id, session_id, task_summary, path_node_ids,
                 path_score, outcome, tokens_saved, delta_compressed, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                traversal_id,
                session_id,
                task_summary,
                json.dumps(path_node_ids),
                path_score,
                outcome,
                tokens_saved,
                delta_compressed,
                time.time(),
            ),
        )
        self._conn.commit()
        return traversal_id

    def get_traversals_for_session(self, session_id: str) -> List[dict]:
        """Return all traversal records for a session, ordered by created_at."""
        cursor = self._conn.execute(
            """
            SELECT traversal_id, session_id, task_summary, path_node_ids,
                   path_score, outcome, tokens_saved, delta_compressed, created_at
            FROM mycelium_traversals
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        )
        rows = cursor.fetchall()
        return [
            {
                "traversal_id": r[0],
                "session_id": r[1],
                "task_summary": r[2],
                "path_node_ids": json.loads(r[3]),
                "path_score": r[4],
                "outcome": r[5],
                "tokens_saved": r[6],
                "delta_compressed": r[7],
                "created_at": r[8],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Row deserialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_node(row: tuple) -> CoordNode:
        """Convert a mycelium_nodes DB row to a CoordNode dataclass."""
        node_id, space_id, coordinates_blob, label, confidence, \
            created_at, updated_at, access_count, last_accessed = row
        return CoordNode(
            node_id=node_id,
            space_id=space_id,
            coordinates=_unpack_coords(coordinates_blob),
            label=label,
            confidence=confidence,
            created_at=created_at,
            updated_at=updated_at,
            access_count=access_count,
            last_accessed=last_accessed,
        )

    @staticmethod
    def _row_to_edge(row: tuple) -> CoordEdge:
        """Convert a mycelium_edges DB row to a CoordEdge dataclass."""
        (edge_id, from_node_id, to_node_id, score, edge_type,
         traversal_count, hit_count, miss_count, decay_rate,
         created_at, last_traversed) = row
        return CoordEdge(
            edge_id=edge_id,
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            score=score,
            edge_type=edge_type,
            traversal_count=traversal_count,
            hit_count=hit_count,
            miss_count=miss_count,
            decay_rate=decay_rate,
            created_at=created_at,
            last_traversed=last_traversed,
        )
