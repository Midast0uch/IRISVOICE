"""
SpeculativeRouter — candidate route generation for Immortus.

Routes are built three ways:
  1. Pheromone walk (mature graph)  — follow high-weight edges
  2. Synthetic from plan           — derive route from plan step order
  3. Shallow inference             — single lightweight model call

All methods return List[CoordinateRoute].  Empty list = no viable path.
"""

from __future__ import annotations

import logging
import math
import uuid
from typing import List, Optional, TYPE_CHECKING

from .constants import (
    IMMORTUS_DEPTH_LOG_WEIGHT,
    IMMORTUS_INTERSECTION_BOOST,
)
from .route import CoordinateRoute
from .temporal import TemporalCoordinate

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SpeculativeRouter:
    """Generates candidate routes through Mycelium coordinate space."""

    def find_candidate_routes(
        self,
        entry,
        objective,
        temporal: TemporalCoordinate,
        thread_id: str,
        graph,
        max_routes: int = 3,
    ) -> List[CoordinateRoute]:
        """
        Find candidate routes via pheromone walk on the graph.
        Returns up to max_routes routes sorted by score descending.
        Falls back to [] if graph walk fails.
        """
        try:
            routes = self._pheromone_walk(entry, objective, temporal, thread_id, graph)
            routes = self._filter_candidates(routes)
            routes.sort(key=lambda r: r.current_score(temporal), reverse=True)
            return routes[:max_routes]
        except Exception as exc:
            logger.debug("[SpeculativeRouter] pheromone walk failed: %s", exc)
            return []

    def synthetic_from_plan(
        self,
        plan,
        temporal: TemporalCoordinate,
        thread_id: str,
    ) -> List[CoordinateRoute]:
        """
        Build a route directly from plan step order (cold start).
        One route per plan; score derived from step clarity.
        """
        try:
            steps = [s.step_id for s in (getattr(plan, "steps", []) or [])]
            if not steps:
                return []

            total = len(steps)
            clear = sum(
                1 for s in getattr(plan, "steps", [])
                if getattr(s, "depends_on", None) is not None
                and getattr(s, "expected_output", None)
            )
            score = (clear / total) if total else 0.5

            route = CoordinateRoute(
                route_id=f"syn-{uuid.uuid4().hex[:8]}",
                thread_id=thread_id,
                steps=steps,
                score=score,
            )
            return [route]
        except Exception as exc:
            logger.debug("[SpeculativeRouter] synthetic_from_plan failed: %s", exc)
            return []

    def inference_routes(
        self,
        plan,
        context_package,
        temporal: TemporalCoordinate,
        thread_id: str,
    ) -> List[CoordinateRoute]:
        """
        Shallow inference route — single fallback route with moderate score.
        Used when graph is immature and clarity is moderate.
        """
        steps = [s.step_id for s in (getattr(plan, "steps", []) or [])]
        route = CoordinateRoute(
            route_id=f"inf-{uuid.uuid4().hex[:8]}",
            thread_id=thread_id,
            steps=steps,
            score=0.45,   # below SYNTHETIC_TRAILS quality, above random
        )
        return [route]

    # ── Internal helpers ──────────────────────────────────────────────────

    def _pheromone_walk(
        self,
        entry,
        objective,
        temporal: TemporalCoordinate,
        thread_id: str,
        graph,
        max_steps: int = 8,
    ) -> List[CoordinateRoute]:
        """
        Walk the Mycelium graph following high-pheromone edges.
        Returns a list with a single route (best path found).
        """
        if graph is None:
            return []

        # Try to use the graph's navigate or pheromone_walk methods
        steps: List[str] = []
        score: float     = 0.5

        try:
            if hasattr(graph, "pheromone_walk"):
                path = graph.pheromone_walk(entry, max_steps=max_steps)
                if path:
                    steps = [str(p) for p in path]
                    score = min(1.0, 0.5 + len(steps) * 0.05)
            elif hasattr(graph, "_store"):
                # Fallback: use edge weights as proxy
                store = graph._store
                if hasattr(store, "_conn") and store._conn:
                    rows = store._conn.execute(
                        "SELECT edge_id, score FROM mycelium_edges "
                        "WHERE thread_id = ? ORDER BY score DESC LIMIT ?",
                        (thread_id, max_steps),
                    ).fetchall()
                    if rows:
                        steps = [r[0] for r in rows]
                        score = float(rows[0][1]) if rows[0][1] else 0.5
        except Exception:
            pass

        if not steps:
            return []

        route = CoordinateRoute(
            route_id=f"phero-{uuid.uuid4().hex[:8]}",
            thread_id=thread_id,
            steps=steps,
            score=score,
        )
        return [route]

    def _score_route(
        self,
        route: CoordinateRoute,
        temporal: TemporalCoordinate,
    ) -> float:
        depth_factor = 1.0 + math.log(temporal.identifier_depth + 1) * IMMORTUS_DEPTH_LOG_WEIGHT
        return route.score * temporal.momentum * depth_factor

    def _filter_candidates(
        self, routes: List[CoordinateRoute]
    ) -> List[CoordinateRoute]:
        """Remove zero-step or zero-score routes."""
        return [r for r in routes if r.steps and r.score > 0]
