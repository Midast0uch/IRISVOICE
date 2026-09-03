"""
CoordinateNavigator — graph traversal, session convergence, and delta-path generation.

SessionRegistry tracks which nodes are active in each session (preventing duplicate
traversal of already-registered nodes in sub-agent delta paths).

CoordinateNavigator handles:
- Entry-node matching from task text keywords
- Hop-limited traversal along highest-scored outbound edges
- navigate_all_spaces() — best node per space with cold-start inject
- author_edge() — agent-facing edge authoring
- connect_nodes() — internal graph maintenance only
"""

import logging
import time
import uuid
from typing import Dict, List, Optional, Set, Tuple

from .store import CoordNode, CoordEdge, CoordinateStore, MemoryPath, _short_uuid
from .spaces import SPACES, CONDUCT_COLD_START_DEFAULT

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SessionRegistry
# ---------------------------------------------------------------------------

class SessionRegistry:
    """
    Tracks active node IDs per session to prevent duplicate traversal.

    In-memory only — cleared on session end or app restart.
    """

    def __init__(self) -> None:
        self._active: Dict[str, Set[str]] = {}

    def register(self, session_id: str, node_ids: List[str]) -> None:
        """Add node_ids to the active set for a session."""
        if session_id not in self._active:
            self._active[session_id] = set()
        self._active[session_id].update(node_ids)

    def get_active(self, session_id: str) -> Set[str]:
        """Return the set of active node IDs for a session (empty set if unknown)."""
        return self._active.get(session_id, set())

    def clear(self, session_id: str) -> None:
        """Remove all tracking for a single session."""
        self._active.pop(session_id, None)

    def clear_all(self) -> None:
        """Remove all session tracking (used on shutdown or full reset)."""
        self._active.clear()


# ---------------------------------------------------------------------------
# CoordinateNavigator
# ---------------------------------------------------------------------------

class CoordinateNavigator:
    """
    Graph traversal engine for the Mycelium coordinate graph.

    Finds entry nodes from task keywords, traverses high-scored edges, and
    returns compact MemoryPath objects ready for encoding.
    """

    # Default edge score threshold below which edges are not followed
    _DEFAULT_MIN_SCORE: float = 0.2
    # Maximum hops per traversal
    _DEFAULT_MAX_HOPS: int = 4

    def __init__(
        self,
        store: CoordinateStore,
        registry: SessionRegistry,
    ) -> None:
        """
        Args:
            store:    CoordinateStore backed by the shared connection.
            registry: SessionRegistry for convergence tracking.
        """
        self._store = store
        self._registry = registry

    # ------------------------------------------------------------------
    # Primary traversal
    # ------------------------------------------------------------------

    def navigate_from_task(
        self,
        task_text: str,
        session_id: str,
        max_hops: int = _DEFAULT_MAX_HOPS,
        min_score: float = _DEFAULT_MIN_SCORE,
        spaces: Optional[List[str]] = None,
        channel_profile: Optional[str] = None,
    ) -> MemoryPath:
        """
        Find the best coordinate path for a task description (Req 5.1–5.5).

        1. Match task keywords to node labels as entry nodes.
        2. Fallback when no matches: all domain+style nodes with confidence > 0.7.
        3. Traverse outbound edges by score, skipping already-active nodes.
        4. Optionally filter to specific spaces or a channel_profile's readable spaces.
        5. Register all traversed node_ids into SessionRegistry.

        Args:
            task_text:       Free-form task description to match against node labels.
            session_id:      Current session identifier.
            max_hops:        Maximum traversal hops from each entry node.
            min_score:       Minimum edge score to follow.
            spaces:          When provided, only traverse nodes in these spaces.
            channel_profile: When provided, restrict to spaces readable by this profile
                             (lazy-imports SUBAGENT_CHANNEL_PROFILES from kyudo.py).

        Returns:
            MemoryPath with all traversed nodes, cumulative score, and traversal_id.
            Returns an empty MemoryPath when the graph has no nodes (Req 5.6).
        """
        # Resolve space filter from channel_profile if given
        allowed_spaces: Optional[Set[str]] = None
        if spaces is not None:
            allowed_spaces = set(spaces)
        if channel_profile is not None:
            readable = self._get_profile_readable_spaces(channel_profile)
            if readable:
                allowed_spaces = (allowed_spaces & readable) if allowed_spaces else readable

        active_nodes = self._registry.get_active(session_id)
        keywords = self._extract_keywords(task_text)

        # Find entry nodes
        entry_nodes = self._match_entry_nodes(keywords, allowed_spaces, active_nodes)

        # Fallback: domain + style nodes with high confidence
        if not entry_nodes:
            entry_nodes = self._fallback_nodes(allowed_spaces, active_nodes)

        # Empty graph — return empty path (Req 5.6)
        if not entry_nodes:
            return MemoryPath(
                nodes=[],
                cumulative_score=0.0,
                token_encoding="",
                spaces_covered=[],
                traversal_id=_short_uuid(),
            )

        # BFS/greedy traversal from all entry nodes
        visited_ids: Set[str] = set()
        result_nodes: List[CoordNode] = []
        cumulative_score = 0.0
        edge_count = 0

        frontier = list(entry_nodes)
        for node in frontier:
            if node.node_id not in visited_ids and node.node_id not in active_nodes:
                visited_ids.add(node.node_id)
                result_nodes.append(node)
                self._store.record_access(node.node_id)

        # Hop traversal
        hops = 0
        current_frontier = list(entry_nodes)
        while hops < max_hops and current_frontier:
            next_frontier: List[CoordNode] = []
            for node in current_frontier:
                edges = self._store.get_outbound_edges(node.node_id, min_score)
                for edge in edges:
                    target_id = edge.to_node_id
                    if target_id in visited_ids or target_id in active_nodes:
                        continue
                    target = self._store.get_node_by_id(target_id)
                    if target is None:
                        continue
                    if allowed_spaces and target.space_id not in allowed_spaces:
                        continue
                    visited_ids.add(target_id)
                    result_nodes.append(target)
                    self._store.record_access(target_id)
                    cumulative_score += edge.score
                    edge_count += 1
                    next_frontier.append(target)
            current_frontier = next_frontier
            hops += 1

        # Normalise cumulative score
        if edge_count > 0:
            cumulative_score /= edge_count

        # Register traversed nodes into SessionRegistry (Req 5.5)
        self._registry.register(session_id, [n.node_id for n in result_nodes])

        spaces_covered = list({n.space_id for n in result_nodes})

        return MemoryPath(
            nodes=result_nodes,
            cumulative_score=cumulative_score,
            token_encoding="",  # caller invokes PathEncoder.encode()
            spaces_covered=spaces_covered,
            traversal_id=_short_uuid(),
        )

    def navigate_all_spaces(self, session_id: str) -> List[CoordNode]:
        """
        Return the highest-confidence node from each of the 6 non-toolpath spaces (Req 5.4).

        Cold-start inject: when conduct space is empty AND is_mature() is False,
        injects a synthetic CoordNode from CONDUCT_COLD_START_DEFAULT.
        The synthetic node is NEVER persisted (Req 4.26–4.27).

        The is_mature() check requires the caller (MyceliumInterface) to pass
        maturity state. For navigator, we check whether any conduct nodes exist —
        if none, we inject the synthetic node unconditionally (maturity is gated
        upstream in MyceliumInterface.get_context_path).
        """
        profile_spaces = [s for s in SPACES if s != "toolpath"]
        result: List[CoordNode] = []

        for space_id in profile_spaces:
            nodes = self._store.get_nodes_by_space(space_id)
            if nodes:
                # Highest confidence
                best = max(nodes, key=lambda n: n.confidence)
                result.append(best)
            elif space_id == "conduct":
                # Cold-start inject (Req 4.26-4.27) — never persisted
                synthetic = CoordNode(
                    node_id="__cold_start__",
                    space_id="conduct",
                    coordinates=list(CONDUCT_COLD_START_DEFAULT),
                    label="cold_start_default",
                    confidence=0.2,
                    created_at=time.time(),
                    updated_at=time.time(),
                    access_count=0,
                    last_accessed=None,
                )
                result.append(synthetic)

        return result

    # ------------------------------------------------------------------
    # Outcome recording
    # ------------------------------------------------------------------

    def record_path_outcome(
        self,
        path: MemoryPath,
        outcome: str,
        session_id: str,
        task_summary: str,
    ) -> None:
        """
        Update edge scores for a completed path and log the traversal (Req 5.7).

        Args:
            path:         The MemoryPath returned by navigate_from_task().
            outcome:      One of "hit", "partial", "miss".
            session_id:   Current session ID.
            task_summary: Short description for the traversal log.
        """
        # Build node_id list for edge lookup
        node_ids = [n.node_id for n in path.nodes]

        # Update edges between consecutive nodes in the path
        for i in range(len(node_ids) - 1):
            from_id = node_ids[i]
            to_id = node_ids[i + 1]
            edges = self._store.get_outbound_edges(from_id)
            for edge in edges:
                if edge.to_node_id == to_id:
                    delta = {"hit": 0.05, "partial": 0.02, "miss": -0.08}.get(outcome, 0.0)
                    self._store.update_edge_score(edge.edge_id, delta)
                    # Update hit/miss counters
                    if outcome == "hit":
                        self._store._conn.execute(
                            "UPDATE mycelium_edges SET hit_count = hit_count + 1 WHERE edge_id = ?",
                            (edge.edge_id,),
                        )
                    elif outcome == "miss":
                        self._store._conn.execute(
                            "UPDATE mycelium_edges SET miss_count = miss_count + 1 WHERE edge_id = ?",
                            (edge.edge_id,),
                        )
                    break

        self._store._conn.commit()

        # Log traversal
        self._store.log_traversal(
            session_id=session_id,
            task_summary=task_summary,
            path_node_ids=node_ids,
            path_score=path.cumulative_score,
            outcome=outcome,
            tokens_saved=None,
        )

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def clear_session(self, session_id: str) -> None:
        """Wipe SessionRegistry entry for this session only (Req 5.9)."""
        self._registry.clear(session_id)

    # ------------------------------------------------------------------
    # Edge authoring
    # ------------------------------------------------------------------

    def author_edge(
        self,
        from_space: str,
        from_coords: List[float],
        to_space: str,
        to_coords: List[float],
        edge_type: str,
    ) -> CoordEdge:
        """
        Agent-facing method to link two concepts (Req 5.8).

        Resolves nearest existing nodes in each space (or creates new nodes),
        then writes an edge at initial score 0.4.

        This is the ONLY method agents should call for graph authoring.
        Initial score is always 0.4 — not configurable by agents.
        """
        from_node = self._store.nearest_node(from_space, from_coords)
        if from_node is None:
            from_node = self._store.upsert_node(from_space, from_coords, None, 0.4)

        to_node = self._store.nearest_node(to_space, to_coords)
        if to_node is None:
            to_node = self._store.upsert_node(to_space, to_coords, None, 0.4)

        edge_id = self._store.upsert_edge(
            from_node.node_id, to_node.node_id, edge_type, initial_score=0.4
        )
        edge = self._store.get_edge_by_id(edge_id)
        if edge is None:
            # Should not happen — upsert_edge always writes or finds
            raise RuntimeError(f"author_edge: edge not found after upsert: {edge_id}")
        return edge

    def connect_nodes(  # INTERNAL: not for agent use
        self,
        from_node_id: str,
        to_node_id: str,
        edge_type: str,
        initial_score: float,
    ) -> str:
        """
        Internal-only method for graph maintenance (Req 5.10).

        Called only by Mycelium internals (LandmarkMerger, MapManager) when
        re-pointing edges. Takes explicit initial_score — bypasses node resolution.
        External code MUST NOT call this method directly.
        """
        return self._store.upsert_edge(from_node_id, to_node_id, edge_type, initial_score)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_keywords(task_text: str) -> List[str]:
        """Extract lowercase word tokens from task text for label matching."""
        return [w.lower().strip(".,!?;:\"'()[]") for w in task_text.split() if len(w) > 2]

    def _match_entry_nodes(
        self,
        keywords: List[str],
        allowed_spaces: Optional[Set[str]],
        active_nodes: Set[str],
    ) -> List[CoordNode]:
        """Find nodes whose label contains any keyword (case-insensitive)."""
        results: List[CoordNode] = []
        seen: Set[str] = set()

        spaces_to_search = list(allowed_spaces) if allowed_spaces else list(SPACES.keys())

        for space_id in spaces_to_search:
            for node in self._store.get_nodes_by_space(space_id):
                if node.node_id in active_nodes or node.node_id in seen:
                    continue
                label = (node.label or "").lower()
                if any(kw in label for kw in keywords):
                    results.append(node)
                    seen.add(node.node_id)

        return results

    def _fallback_nodes(
        self,
        allowed_spaces: Optional[Set[str]],
        active_nodes: Set[str],
    ) -> List[CoordNode]:
        """Fallback: domain + style nodes with confidence > 0.7 (Req 5.2)."""
        results: List[CoordNode] = []
        fallback_spaces = {"domain", "style"}
        if allowed_spaces:
            fallback_spaces &= allowed_spaces

        for space_id in fallback_spaces:
            for node in self._store.get_nodes_by_space(space_id):
                if node.node_id not in active_nodes and node.confidence > 0.7:
                    results.append(node)

        return results

    @staticmethod
    def _get_profile_readable_spaces(channel_profile: str) -> Set[str]:
        """
        Get readable spaces for a channel profile.

        Lazy-imports SUBAGENT_CHANNEL_PROFILES from kyudo.py to avoid circular
        imports (kyudo imports navigator indirectly through interface).
        Returns empty set if kyudo is not yet built.
        """
        try:
            from .kyudo import SUBAGENT_CHANNEL_PROFILES  # noqa: PLC0415
            profile = SUBAGENT_CHANNEL_PROFILES.get(channel_profile, {})
            readable = profile.get("read", [])
            if readable == "all":
                return set(SPACES.keys())
            return set(readable)
        except ImportError:
            logger.debug("[navigator] kyudo not available yet — ignoring channel_profile filter")
            return set()
