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

from backend.memory.db import app_flush, app_write
from .store import CoordEdge, CoordNode, CoordinateStore
from .spaces import (
    CONDENSE_THRESHOLD,
    HIGHWAY_BONUS,
    HIGHWAY_THRESHOLD,
    PRUNE_THRESHOLD,
    SPLIT_THRESHOLD,
)

logger = logging.getLogger(__name__)

# The fixed space order for condense and expand passes (Req 7.10) is the
# registry's row order: store.spaces.ids (a new space is appended).

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

    def apply_decay(
        self,
        session_id: Optional[str] = None,
        quorum_since: Optional[float] = None,
    ) -> int:
        """
        Apply score decay to edges and delete those below PRUNE_THRESHOLD
        (0.08) (Req 7.3-7.5) - the decay half of the ONE growth/decay law
        (decay.py; MEMORY-FOUNDATION-ANALYSIS §11).

          score -= rate * m * days * a(n)
          rate = the space's own rate (toolpath 0.02) for the edges of a
                 never-rendered, behavioural space (registry.edge_rate_override),
                 else the stored per-edge decay_rate
          a(n) = 1 / (1 + observation_count) - the SAME weight record_outcome
                 gives an observation, so growth and decay run at one speed
          m    = m_channel (the weaker endpoint's Kyudo channel)
                 * m_phase (mean Caducean u over the span: expand 0.5,
                   compress 1.8; that session's rows when session_id is given)
          days = ACTIVE days (decay.ActivityClock: days with >= 1 episode)
                 since max(last_traversed, last_decayed_at) - each span is
                 counted once (the pass used to subtract the whole idle time
                 again on every run, so decay compounded)

        Edges with last_traversed=None are skipped (no idle time). The UPDATE
        sets score and last_decayed_at only: decay is FORGETTING, never an
        observation (REQ-26 AC7) - observation_count is never touched.

        quorum_since: the reorganization form (kyudo.QuorumReorganization):
        only edges traversed at or after it, days = QUORUM_SPAN_DAYS, m also
        * QUORUM_DECAY_MULTIPLIER. a(n) makes it strip new, unproven growth
        while well-proven routes barely move. last_decayed_at is left alone.

        Returns:
            Number of edges deleted (pruned) during this pass.
        """
        from . import decay as _decay  # noqa: PLC0415

        now = time.time()
        pruned = 0
        conn = self._store._conn

        # One writer: the edge scores and rows queued so far are on disk before
        # the pass reads them and decides what to prune.
        app_flush()
        incremental = _decay.has_decay_columns(conn)
        if incremental:
            rows = conn.execute(
                """
                SELECT e.edge_id, e.score, e.decay_rate, e.last_traversed,
                       e.last_decayed_at, e.observation_count, n.space_id,
                       MIN(COALESCE(n.source_channel, ?), COALESCE(t.source_channel, ?))
                FROM mycelium_edges e
                JOIN mycelium_nodes n ON e.from_node_id = n.node_id
                LEFT JOIN mycelium_nodes t ON e.to_node_id = t.node_id
                """,
                (_decay.LEGACY_CHANNEL, _decay.LEGACY_CHANNEL),
            ).fetchall()
        else:
            # A store without the bookkeeping columns (has_decay_columns).
            rows = conn.execute(
                """
                SELECT e.edge_id, e.score, e.decay_rate, e.last_traversed,
                       NULL, e.observation_count, n.space_id, NULL
                FROM mycelium_edges e
                JOIN mycelium_nodes n ON e.from_node_id = n.node_id
                """
            ).fetchall()

        refs = [
            max(r[3], r[4] or 0.0) for r in rows
            if r[3] is not None and (quorum_since is None or r[3] >= quorum_since)
        ]
        if not refs:
            return 0
        phase = _decay.phase_multiplier(conn, min(refs), session_id)
        clock = _decay.ActivityClock(conn, min(refs), now)
        quorum = 1.0
        if quorum_since is not None:
            from .kyudo import QUORUM_DECAY_MULTIPLIER  # noqa: PLC0415
            quorum = QUORUM_DECAY_MULTIPLIER

        for (edge_id, score, decay_rate, last_traversed, last_decayed_at,
             observation_count, space_id, channel) in rows:
            if last_traversed is None:
                continue  # Never traversed - skip
            if quorum_since is not None:
                if last_traversed < quorum_since:
                    continue
                days = _decay.QUORUM_SPAN_DAYS
            else:
                days = clock.days_since(max(last_traversed, last_decayed_at or 0.0))
            if days <= 0.0:
                continue

            override = self._store.spaces.edge_rate_override(space_id)
            rate = decay_rate if override is None else override
            amount = _decay.edge_decay_amount(
                rate, _decay.channel_multiplier(channel) * phase * quorum,
                days, observation_count,
            )

            if score - amount < PRUNE_THRESHOLD:
                self._store.delete_edge(edge_id)
                pruned += 1
            elif quorum_since is not None or not incremental:
                app_write(
                    conn,
                    "UPDATE mycelium_edges SET score = MAX(0.0, score - ?) WHERE edge_id = ?",
                    (amount, edge_id),
                )
            else:
                # Direct UPDATE: bypass traversal_count bump (Req 7.3).
                # One writer: the decay is subtracted on the writer thread, so an
                # observation queued between the read and this write is kept.
                app_write(
                    conn,
                    "UPDATE mycelium_edges SET score = MAX(0.0, score - ?), "
                    "last_decayed_at = ? WHERE edge_id = ?",
                    (amount, now, edge_id),
                )

        logger.debug("[scorer] apply_decay: pruned %d edges (phase=%.2f quorum=%.1f)",
                     pruned, phase, quorum)
        return pruned

    def apply_node_decay(
        self,
        session_id: Optional[str] = None,
        quorum_since: Optional[float] = None,
    ) -> int:
        """
        Decay node confidence EARNED by repetition back toward the stated
        floor (decay.node_confidence_after) - the counterpart of
        store._accumulate_confidence: a node that stops recurring loses what
        recurrence gave it and keeps what was stated. Same multipliers and
        incremental span as apply_decay; the space's own rate and floor, as
        its registry row declares them (conduct 0.008, toolpath 0.02,
        context 0.025, else 0.005; floor 0.4).

        quorum_since: the reorganization form - nodes updated at or after it,
        one QUORUM_SPAN_DAYS at m * QUORUM_DECAY_MULTIPLIER.

        Returns:
            Number of nodes whose confidence was lowered.
        """
        from . import decay as _decay  # noqa: PLC0415

        spaces = self._store.spaces
        now = time.time()
        conn = self._store._conn
        if not _decay.has_decay_columns(conn, "mycelium_nodes"):
            # Without last_decayed_at the span would be counted again on every
            # pass; a store that predates the column keeps its old behaviour.
            logger.debug("[scorer] apply_node_decay: store has no decay columns")
            return 0
        app_flush()
        rows = conn.execute(
            "SELECT node_id, space_id, confidence, updated_at, last_decayed_at, "
            "source_channel FROM mycelium_nodes WHERE confidence > ?",
            # Rows at or below every floor have nothing earned to lose; the
            # per-space floor is applied in node_confidence_after.
            (min([_decay.NODE_CONFIDENCE_FLOOR] + [spaces.confidence_floor(s) for s in spaces.ids]),),
        ).fetchall()
        refs = [
            max(r[3] or 0.0, r[4] or 0.0) for r in rows
            if quorum_since is None or (r[3] or 0.0) >= quorum_since
        ]
        if not refs:
            return 0
        phase = _decay.phase_multiplier(conn, min(refs), session_id)
        clock = _decay.ActivityClock(conn, min(refs), now)
        quorum = 1.0
        if quorum_since is not None:
            from .kyudo import QUORUM_DECAY_MULTIPLIER  # noqa: PLC0415
            quorum = QUORUM_DECAY_MULTIPLIER

        changed = 0
        for node_id, space_id, confidence, updated_at, last_decayed_at, channel in rows:
            if quorum_since is not None:
                if (updated_at or 0.0) < quorum_since:
                    continue
                days = _decay.QUORUM_SPAN_DAYS
            else:
                days = clock.days_since(max(updated_at or 0.0, last_decayed_at or 0.0))
            if days <= 0.0:
                continue
            new_conf = _decay.node_confidence_after(
                confidence,
                spaces.decay_rate(space_id),
                _decay.channel_multiplier(channel) * phase * quorum,
                days,
                floor=spaces.confidence_floor(space_id),
            )
            # updated_at is NOT bumped: decay is not an observation.
            if quorum_since is not None:
                app_write(conn, "UPDATE mycelium_nodes SET confidence = ? WHERE node_id = ?",
                          (new_conf, node_id))
            else:
                app_write(
                    conn,
                    "UPDATE mycelium_nodes SET confidence = ?, last_decayed_at = ? "
                    "WHERE node_id = ?",
                    (new_conf, now, node_id),
                )
            changed += 1

        logger.debug("[scorer] apply_node_decay: %d nodes (phase=%.2f quorum=%.1f)",
                     changed, phase, quorum)
        return changed


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
        Run condense pass across every registered space in registry order (Req 7.10).

        Returns:
            Total nodes merged (removed) across all spaces.
        """
        total = 0
        for space_id in self._store.spaces.ids:
            total += self.condense(space_id)
        return total

    def run_expand(self) -> int:
        """
        Run expand pass across every registered space in registry order (Req 7.10).

        Returns:
            Total nodes split across all spaces.
        """
        total = 0
        for space_id in self._store.spaces.ids:
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
        app_flush()  # one writer: queued node/edge writes are on disk before the scan
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
                app_write(
                    self._store._conn,
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
        app_flush()  # one writer: queued node/edge writes are on disk before the scan
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
                app_write(
                    self._store._conn,
                    "UPDATE mycelium_edges SET from_node_id = ? WHERE edge_id = ?",
                    (node_a.node_id, edge.edge_id),
                )
            for edge in miss_edges:
                app_write(
                    self._store._conn,
                    "UPDATE mycelium_edges SET from_node_id = ? WHERE edge_id = ?",
                    (node_b.node_id, edge.edge_id),
                )

            # Re-point inbound edges to original → node_a
            app_write(
                self._store._conn,
                "UPDATE mycelium_edges SET to_node_id = ? WHERE to_node_id = ?",
                (node_a.node_id, node.node_id),
            )

            # Delete original node
            self._store.delete_node(node.node_id)
            # One writer: the next node reads the edges this split re-pointed.
            app_flush()
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
