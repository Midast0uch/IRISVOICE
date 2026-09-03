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
    "domain",
    "style",
    "conduct",
    "chrono",
    "capability",
    "context",
    "toolpath",
]

# Outcome score deltas (Req 7.1) — now the PER-OBSERVATION base impact of a
# REQ-26/T40 evidence-weighted update, not a fixed applied delta.
#
# REQ-26 AC2 — the asymmetry is a DELIBERATE PESSIMISM PRIOR, stated, not
# implicit: a miss (-0.08) weighs 1.6x a hit (+0.05), so ~2 hits undo 1 miss.
# Rationale: in this system a wrong action writes a biased node into shared
# memory that later gets recalled AS evidence, so failures compound while
# successes self-correct — the prior is set to make the store harder to fool,
# not because misses are 1.6x more informative in the abstract.
#
# The applied delta is base * alpha where alpha = 1/(1+observation_count)
# BEFORE the observation lands, so the FIRST observation on an edge moves it
# fully and later ones converge (REQ-26 AC1: a posterior, not a
# reinforcement rule). See EdgeScorer.record_outcome.
_OUTCOME_DELTAS = {
    "hit": 0.05,
    "partial": 0.02,
    "miss": -0.08,
}

# REQ-26 AC5 (T40d): the PRIOR for an unseen (coordinate-region, mediator)
# pair — the initial score of a newly created region->mediator edge. Explicit
# and recorded so first-encounter behavior is a decision, not an accident of
# initialization: a fresh pair starts at neutral 0.5 (no evidence either way)
# and the pessimism asymmetry above does the rest. This constant is the prior
# the BehavioralPredictor reads for pairs it has never seen.
_UNSEEN_PAIR_PRIOR = 0.5


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
        Apply an outcome observation to every edge in edge_ids (Req 7.1–7.2).

        REQ-26 (T40): the update is now EVIDENCE-WEIGHTED, not a fixed delta.
        Each edge carries an ``observation_count``; the applied delta is
        ``base_delta * alpha`` where ``alpha = 1 / (1 + observation_count)``
        computed BEFORE the observation lands. The first observation on an
        edge therefore moves it fully (alpha = 1.0), the 100th barely —
        belief converges instead of oscillating, which is the entire thing a
        posterior provides. ``observation_count`` is bumped alongside
        ``traversal_count`` (via ``CoordinateStore.record_observation``), so
        the score always carries the evidence behind it.

        The asymmetry in ``_OUTCOME_DELTAS`` (miss = 1.6x hit) is a stated
        pessimism prior — see the constant's docstring.

        HIGHWAY_BONUS (+0.01) is applied in the same call when a hit pushes
        the score from below HIGHWAY_THRESHOLD (0.85) to at or above it —
        crossing counts as a single traversal (Req 7.2).

        REQ-26 AC7: this method is the ONLY place an outcome may be counted.
        ``apply_decay`` never calls it, so decay is never recorded as a miss
        and never inflates ``observation_count``.

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

            # REQ-26 AC1: diminishing update — alpha from the count BEFORE
            # this observation. First observation: alpha = 1/(1+0) = 1.0
            # (full strength); each later one converges.
            alpha = 1.0 / (1.0 + edge.observation_count)
            delta = base_delta * alpha

            # Highway bonus: add when a hit crosses HIGHWAY_THRESHOLD
            if outcome == "hit":
                projected = min(1.0, edge.score + delta)
                if edge.score < HIGHWAY_THRESHOLD <= projected:
                    delta += HIGHWAY_BONUS

            self._store.record_observation(edge_id, delta)

    def record_region_mediator_outcome(
        self,
        region_node_id: str,
        mediator: str,
        outcome: str,
    ) -> Optional[str]:
        """
        REQ-26 AC1/T40c (join with REQ-23/T37): score the ONE edge for a
        (coordinate-region, mediator) pair.

        The region is ``region_node_id`` (a coordinate node — typically an
        active node from ``SessionRegistry.get_active``); the mediator is the
        resolved tool/action identifier from ``_der_mediator_for`` (T37) — the
        tool NAME, not the args-hashed full string: the graph learns
        tool-per-region (a tool that works in one region and fails in another
        must be representable — a single global score cannot express that),
        while the args hash stays on the chain row as provenance (REQ-23 AC2).

        Resolution:
          1. Find the toolpath node labelled ``mediator`` (label identity, not
             coordinate proximity — ``store.get_node_by_label``); create it if
             absent, at the region's coordinates so condense/expand stay
             coordinate-local.
          2. Find-or-create the edge region -> mediator with
             ``_UNSEEN_PAIR_PRIOR`` as the initial score (REQ-26 AC5 — the
             prior for an unseen pair is explicit and recorded).
          3. Apply the evidence-weighted update to THAT edge only (a
             repeated failure here cannot touch region B's edge for the same
             mediator — the caller selects the edge, never the global fan-out
             the pre-REQ-26 path used).

        Returns the scored edge_id (or None if the region node is missing).
        """
        region = self._store.get_node_by_id(region_node_id)
        if region is None:
            return None

        mediator_node = self._store.get_node_by_label("toolpath", mediator)
        if mediator_node is None:
            mediator_node = self._store.upsert_node(
                space_id="toolpath",
                coordinates=list(region.coordinates),
                label=mediator,
                confidence=0.5,
            )

        edge_id = self._store.upsert_edge(
            from_node_id=region_node_id,
            to_node_id=mediator_node.node_id,
            edge_type="tool_choice",
            initial_score=_UNSEEN_PAIR_PRIOR,
        )
        self.record_outcome([edge_id], outcome)
        return edge_id

    def apply_decay(self, session_id: Optional[str] = None) -> int:
        """
        Apply time-based score decay to all edges and delete those below
        PRUNE_THRESHOLD (0.08) (Req 7.3–7.5).

        Decay formula:  score -= effective_decay_rate * caducean_multiplier * days_idle
        where days_idle = (now - last_traversed) / 86400.

        Toolpath edges use TOOLPATH_DECAY_RATE (0.02); all others use their
        stored per-edge decay_rate.  Edges with last_traversed=None (never
        traversed) are skipped — no idle time can be computed.

        Decay writes use a direct UPDATE to avoid bumping traversal_count
        (decay is not a traversal).

        REQ-26 AC7 (T40e): decay is FORGETTING, not an observation — the
        direct UPDATE below sets score only and never touches
        ``observation_count``, and decay never routes through
        ``record_outcome``, so it can never be counted as a miss nor inflate
        the evidence count behind a score.

        v2: When session_id is provided, the Caducean attentional velocity (u)
        modulates the effective decay rate:
          u > 0  (explore)  -> decay_multiplier = 0.5  (preserve learning)
          u < 0  (compress) -> decay_multiplier = 1.8  (prune unreinforced faster)
          u ≈ 0  (neutral)  -> decay_multiplier = 1.0  (default)
        Read once at start of pass — no per-edge DB hit.

        Returns:
            Number of edges deleted (pruned) during this pass.
        """
        now = time.time()
        pruned = 0

        # v2: read Caducean state once at pass start (no per-edge SQL)
        caducean_multiplier = 1.0
        if session_id is not None:
            try:
                latest = self._store.get_latest_u(session_id)
                if latest is not None:
                    u = latest.get("u", 0.0)
                    if u > 0.0:
                        caducean_multiplier = 0.5  # explore — preserve
                    elif u < 0.0:
                        caducean_multiplier = 1.8  # compress — prune
                    # else: u ≈ 0 → multiplier = 1.0 (no modulation)
            except Exception as exc:  # noqa: BLE001
                logger.debug("[scorer] caducean modulation unavailable: %s", exc)
                caducean_multiplier = 1.0  # safe default

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
            # v2: modulate by Caducean velocity (read once at pass start, applied per-edge)
            new_score = score - effective_rate * caducean_multiplier * days_idle

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

        REQ-19 vocabulary: this is NODE CONDENSE — the mycelium coordinate-graph
        compaction mechanism (scorer.condense). It is NOT Landmark.condense()
        (Landmark Crystallization, landmark.py), NOT DER "COMPRESS" (a physics
        recommendation code, int 1, agent_kernel.py), NOT DCP message pruning,
        and NOT mcm_compress (external build tooling). See the REQ-19 vocabulary
        table in specs/long-horizon-der-execution/design.md.

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

            for node_b in nodes[i + 1 :]:
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

        REQ-19 vocabulary: this is NODE EXPANSION — the mycelium coordinate-graph
        mechanism (scorer.expand). It is NOT Step Expansion (agent_kernel.py
        _growth_width -> _split_step, which creates DER sub-loop steps), NOT DER
        "EXPAND" (a physics phase), and NOT DCP message pruning. See the REQ-19
        vocabulary table in specs/long-horizon-der-execution/design.md.

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
            coords_a = [
                orig[d] + 0.20 * (hit_center[d] - orig[d]) for d in range(n_dims)
            ]
            coords_b = [
                orig[d] + 0.20 * (miss_center[d] - orig[d]) for d in range(n_dims)
            ]

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
            sum(c[d] for c in coord_lists) / len(coord_lists) for d in range(n_dims)
        ]
