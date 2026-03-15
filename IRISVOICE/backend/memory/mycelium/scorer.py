"""
EdgeScorer and MapManager — edge score maintenance, time decay, and graph topology management.

EdgeScorer: records traversal outcomes (hit/partial/miss), applies time-based score decay,
and prunes edges that fall below the minimum score threshold.

MapManager: condenses near-duplicate nodes by merging and re-pointing edges, and expands
high-variance nodes by splitting them into hit-cluster and miss-cluster children.
"""

import logging
import math
import struct
import time
from typing import List, Optional

from .store import CoordEdge, CoordNode, CoordinateStore
from .spaces import (
    CONDENSE_THRESHOLD,
    HIGHWAY_BONUS,
    HIGHWAY_THRESHOLD,
    PRUNE_THRESHOLD,
    SPLIT_THRESHOLD,
    TOOLPATH_DECAY_RATE,
)

logger = logging.getLogger(__name__)

# Fixed space order for condense and expand passes (Req 7.10)
_SPACE_ORDER: List[str] = [
    "domain", "style", "conduct", "chrono", "capability", "context", "toolpath",
]

# Outcome score deltas (Req 7.1)
_OUTCOME_DELTAS = {
    "hit":     0.05,
    "partial": 0.02,
    "miss":   -0.08,
}


def _pack_coords(coords: List[float]) -> bytes:
    """Pack float list to big-endian binary blob — mirrors store._pack_coords."""
    n = len(coords)
    return struct.pack(f">{n}f", *coords)


# ---------------------------------------------------------------------------
# EdgeScorer
# ---------------------------------------------------------------------------

class EdgeScorer:
    """
    Maintains edge scores based on traversal outcomes and time decay.

    All reads and writes go through CoordinateStore — never raw SQL outside
    the one decay UPDATE that bypasses traversal_count (intentional).
    """

    def __init__(self, store: CoordinateStore) -> None:
        self._store = store

    def record_outcome(self, edge_ids: List[str], outcome: str) -> None:
        """
        Apply an outcome delta to every edge in edge_ids (Req 7.1–7.2).

        Deltas: hit=+0.05, partial=+0.02, miss=-0.08.
        HIGHWAY_BONUS (+0.01) is applied in the same call when a hit pushes
        the score from below HIGHWAY_THRESHOLD (0.85) to at or above it —
        crossing counts as a single traversal (Req 7.2).

        Unknown outcome values are silently ignored.

        Args:
            edge_ids: Edge IDs to update.
            outcome:  One of "hit", "partial", "miss".
        """
        base_delta = _OUTCOME_DELTAS.get(outcome, 0.0)
        if base_delta == 0.0:
            return

        for edge_id in edge_ids:
            edge = self._store.get_edge_by_id(edge_id)
            if edge is None:
                continue

            delta = base_delta

            # Highway bonus: add when a hit crosses HIGHWAY_THRESHOLD
            if outcome == "hit":
                projected = min(1.0, edge.score + base_delta)
                if edge.score < HIGHWAY_THRESHOLD <= projected:
                    delta += HIGHWAY_BONUS

            self._store.update_edge_score(edge_id, delta)

    def apply_decay(self) -> int:
        """
        Apply time-based score decay to all edges and delete those below
        PRUNE_THRESHOLD (0.08) (Req 7.3–7.5).

        Decay formula:  score -= effective_decay_rate * days_idle
        where days_idle = (now - last_traversed) / 86400.

        Toolpath edges use TOOLPATH_DECAY_RATE (0.02); all others use their
        stored per-edge decay_rate.  Edges with last_traversed=None (never
        traversed) are skipped — no idle time can be computed.

        Decay writes use a direct UPDATE to avoid bumping traversal_count
        (decay is not a traversal).

        Returns:
            Number of edges deleted (pruned) during this pass.
        """
        now = time.time()
        pruned = 0

        # Fetch all edges joined to their from_node space_id in one round-trip
        cursor = self._store._conn.execute(
            """
            SELECT e.edge_id, e.score, e.decay_rate, e.last_traversed, n.space_id
            FROM mycelium_edges e
            JOIN mycelium_nodes n ON e.from_node_id = n.node_id
            """
        )
        rows = cursor.fetchall()

        for edge_id, score, decay_rate, last_traversed, space_id in rows:
            if last_traversed is None:
                continue  # Never traversed — skip

            days_idle = (now - last_traversed) / 86400.0
            if days_idle <= 0.0:
                continue

            effective_rate = (
                TOOLPATH_DECAY_RATE if space_id == "toolpath" else decay_rate
            )
            new_score = score - effective_rate * days_idle

            if new_score < PRUNE_THRESHOLD:
                self._store.delete_edge(edge_id)
                pruned += 1
            else:
                # Direct UPDATE: bypass traversal_count bump (Req 7.3)
                self._store._conn.execute(
                    "UPDATE mycelium_edges SET score = ? WHERE edge_id = ?",
                    (max(0.0, new_score), edge_id),
                )

        self._store._conn.commit()
        logger.debug("[scorer] apply_decay: pruned %d edges", pruned)
        return pruned


# ---------------------------------------------------------------------------
# MapManager
# ---------------------------------------------------------------------------

class MapManager:
    """
    Graph topology maintenance — condenses near-duplicate nodes and expands
    high-variance nodes so the coordinate graph stays lean and informative.
    """

    def __init__(self, store: CoordinateStore) -> None:
        self._store = store

    # ------------------------------------------------------------------
    # Public entry points (called by MyceliumInterface during maintenance)
    # ------------------------------------------------------------------

    def run_condense(self) -> int:
        """
        Run condense pass across all 7 spaces in fixed order (Req 7.10).

        Returns:
            Total nodes merged (removed) across all spaces.
        """
        total = 0
        for space_id in _SPACE_ORDER:
            total += self.condense(space_id)
        return total

    def run_expand(self) -> int:
        """
        Run expand pass across all 7 spaces in fixed order (Req 7.10).

        Returns:
            Total nodes split across all spaces.
        """
        total = 0
        for space_id in _SPACE_ORDER:
            total += self.expand(space_id)
        return total

    # ------------------------------------------------------------------
    # Condense
    # ------------------------------------------------------------------

    def condense(self, space_id: str) -> int:
        """
        Merge pairs of nodes in space_id within CONDENSE_THRESHOLD (0.04) (Req 7.6–7.7).

        For each qualifying pair:
          - Survivor = node with higher access_count (ties favour first-encountered).
          - New coordinates = access-count-weighted average of both nodes.
          - All edges from the victim are re-pointed to the survivor via
            CoordinateStore.repoint_edges() (handles self-loop removal internally).
          - Victim node is deleted.

        Each node participates in at most one merge per call (marked via
        a `merged` set so chained merges are deferred to the next pass).

        Returns:
            Number of nodes removed in this space.
        """
        nodes = self._store.get_nodes_by_space(space_id)
        merged: set = set()
        merge_count = 0

        for i, node_a in enumerate(nodes):
            if node_a.node_id in merged:
                continue

            for node_b in nodes[i + 1:]:
                if node_b.node_id in merged:
                    continue

                dist = node_a.distance_to(node_b.coordinates)
                if dist > CONDENSE_THRESHOLD:
                    continue

                # Survivor = higher access_count
                if node_b.access_count > node_a.access_count:
                    survivor, victim = node_b, node_a
                else:
                    survivor, victim = node_a, node_b

                # Weighted-average coordinates by access_count
                total_acc = survivor.access_count + victim.access_count
                if total_acc > 0:
                    w_s = survivor.access_count / total_acc
                    w_v = victim.access_count / total_acc
                else:
                    w_s, w_v = 0.5, 0.5

                new_coords = [
                    w_s * sc + w_v * vc
                    for sc, vc in zip(survivor.coordinates, victim.coordinates)
                ]

                # Update survivor coordinates directly (not via upsert — avoids
                # triggering another dedup check that could merge with a third node)
                self._store._conn.execute(
                    """
                    UPDATE mycelium_nodes
                    SET coordinates = ?, updated_at = ?
                    WHERE node_id = ?
                    """,
                    (_pack_coords(new_coords), time.time(), survivor.node_id),
                )

                # Re-point victim edges → survivor; delete victim
                self._store.repoint_edges(victim.node_id, survivor.node_id)
                self._store.delete_node(victim.node_id)

                merged.add(victim.node_id)
                merge_count += 1
                break  # node_a fully processed; advance outer loop

        if merge_count:
            self._store._conn.commit()

        logger.debug("[scorer] condense(%s): merged %d nodes", space_id, merge_count)
        return merge_count

    # ------------------------------------------------------------------
    # Expand
    # ------------------------------------------------------------------

    def expand(self, space_id: str) -> int:
        """
        Split nodes whose outbound edge hit/miss variance exceeds SPLIT_THRESHOLD (0.40)
        into two child nodes (Req 7.8–7.9).

        For each qualifying node:
          - Compute hit_rate per outbound edge: hit_count / (hit_count + miss_count).
          - Compute variance of these rates across all outbound edges.
          - If variance > SPLIT_THRESHOLD:
              hit_edges  = edges with hit_rate > 0.5
              miss_edges = edges with hit_rate ≤ 0.5
            (Skip if either group is empty — no meaningful split.)
          - hit_center  = mean coordinates of hit_edges' target nodes
          - miss_center = mean coordinates of miss_edges' target nodes
          - node_a coords = original + 0.20 * (hit_center  - original)
          - node_b coords = original + 0.20 * (miss_center - original)
          - hit_edges  are re-pointed from_node_id → node_a
          - miss_edges are re-pointed from_node_id → node_b
          - Inbound edges to original are re-pointed → node_a (arbitrary survivor)
          - Original node is deleted.

        Returns:
            Number of nodes split in this space.
        """
        nodes = self._store.get_nodes_by_space(space_id)
        split_count = 0

        for node in nodes:
            edges = self._store.get_outbound_edges(node.node_id)
            if len(edges) < 2:
                continue  # Too few edges — skip

            # Compute hit_rate per edge
            hit_rates = []
            for edge in edges:
                total = edge.hit_count + edge.miss_count
                rate = edge.hit_count / total if total > 0 else 0.5
                hit_rates.append(rate)

            # Sample variance of hit_rates
            n = len(hit_rates)
            mean = sum(hit_rates) / n
            variance = sum((r - mean) ** 2 for r in hit_rates) / n

            if variance <= SPLIT_THRESHOLD:
                continue

            # Classify edges into hit-cluster and miss-cluster
            hit_edges = [e for e, r in zip(edges, hit_rates) if r > 0.5]
            miss_edges = [e for e, r in zip(edges, hit_rates) if r <= 0.5]

            if not hit_edges or not miss_edges:
                continue  # All edges in one cluster — nothing to split

            # Cluster centers (average of target node coordinates)
            hit_center = self._cluster_center(hit_edges)
            miss_center = self._cluster_center(miss_edges)
            if hit_center is None or miss_center is None:
                continue

            orig = node.coordinates
            n_dims = len(orig)
            if len(hit_center) != n_dims or len(miss_center) != n_dims:
                continue

            # Shift 20% toward each cluster center
            coords_a = [orig[d] + 0.20 * (hit_center[d] - orig[d]) for d in range(n_dims)]
            coords_b = [orig[d] + 0.20 * (miss_center[d] - orig[d]) for d in range(n_dims)]

            # Create two child nodes
            node_a = self._store.upsert_node(
                space_id,
                coords_a,
                f"{node.label}_hit" if node.label else None,
                node.confidence,
            )
            node_b = self._store.upsert_node(
                space_id,
                coords_b,
                f"{node.label}_miss" if node.label else None,
                node.confidence,
            )

            # Re-point outbound edges: hit → node_a, miss → node_b
            for edge in hit_edges:
                self._store._conn.execute(
                    "UPDATE mycelium_edges SET from_node_id = ? WHERE edge_id = ?",
                    (node_a.node_id, edge.edge_id),
                )
            for edge in miss_edges:
                self._store._conn.execute(
                    "UPDATE mycelium_edges SET from_node_id = ? WHERE edge_id = ?",
                    (node_b.node_id, edge.edge_id),
                )

            # Re-point inbound edges to original → node_a
            self._store._conn.execute(
                "UPDATE mycelium_edges SET to_node_id = ? WHERE to_node_id = ?",
                (node_a.node_id, node.node_id),
            )

            # Delete original node
            self._store.delete_node(node.node_id)
            self._store._conn.commit()
            split_count += 1

        logger.debug("[scorer] expand(%s): split %d nodes", space_id, split_count)
        return split_count

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _cluster_center(self, edges: List[CoordEdge]) -> Optional[List[float]]:
        """
        Compute the mean coordinate vector of the target nodes for a list of edges.

        Returns None if any target node is missing, or if coordinate dimensions
        are inconsistent across the target nodes.
        """
        coord_lists: List[List[float]] = []
        for edge in edges:
            target = self._store.get_node_by_id(edge.to_node_id)
            if target is None:
                return None
            coord_lists.append(target.coordinates)

        if not coord_lists:
            return None

        n_dims = len(coord_lists[0])
        if any(len(c) != n_dims for c in coord_lists):
            return None

        return [
            sum(c[d] for c in coord_lists) / len(coord_lists)
            for d in range(n_dims)
        ]
