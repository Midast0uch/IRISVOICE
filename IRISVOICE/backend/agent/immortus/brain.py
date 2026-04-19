"""
ImmortusBrain — activation gate, thread assignment, cold-start strategy.

evaluate() is called once per plan, between _plan_task() and _execute_plan_der()
in the agent kernel.  It returns an ImmortusSession (active Immortus) or None
(pass-through to standard DER, for shallow tasks below DEPTH_THRESHOLD).

All graph calls are wrapped in try/except — if the Mycelium interface doesn't
expose a method yet, Immortus degrades gracefully without crashing the kernel.
"""

from __future__ import annotations

import logging
import math
from typing import List, Optional, TYPE_CHECKING

from .constants import (
    IMMORTUS_DEPTH_THRESHOLD,
    IMMORTUS_CLARITY_THRESHOLD,
    IMMORTUS_NOVELTY_THRESHOLD,
    IMMORTUS_DRIFT_CRITICAL,
)
from .decisions import ColdStartStrategy
from .session import ImmortusSession
from .temporal import TemporalCoordinate

if TYPE_CHECKING:
    from .router import SpeculativeRouter
    from .route import CoordinateRoute

logger = logging.getLogger(__name__)


class ImmortusBrain:
    """
    Activation gate and routing orchestrator for Immortus.

    Args:
        router: SpeculativeRouter instance.
        graph:  MyceliumInterface — used for maturity check, resonance queries,
                pheromone walks, and thread depth lookups.  All calls are
                guarded; a None graph causes cold-start path.
    """

    def __init__(self, router: "SpeculativeRouter", graph) -> None:
        self.router = router
        self.graph  = graph

    def evaluate(
        self,
        plan,
        context_package,
        session_id: str,
    ) -> Optional[ImmortusSession]:
        """
        Decide whether Immortus should activate for *plan*.

        Returns an ImmortusSession if dependency depth >= IMMORTUS_DEPTH_THRESHOLD,
        otherwise None (standard DER takes over).
        """
        try:
            depth = self._compute_dependency_depth(plan.steps)
        except Exception as exc:
            logger.debug("[ImmortusBrain] depth computation failed: %s", exc)
            return None

        if depth < IMMORTUS_DEPTH_THRESHOLD:
            return None

        thread_id = self._assign_thread_id(
            getattr(plan, "plan_id", session_id), session_id
        )

        entry_coords     = self._extract_entry_coordinates(plan, context_package)
        objective_coords = self._extract_objective_coordinates(plan, context_package)
        temporal         = TemporalCoordinate.cold()

        if self._graph_is_mature():
            routes = self._find_routes(entry_coords, objective_coords, temporal, thread_id)
        else:
            routes = self._cold_start_routes(plan, context_package, temporal, thread_id)

        if not routes:
            logger.debug(
                "[ImmortusBrain] No routes found for plan %s — falling back to DER",
                getattr(plan, "plan_id", "?"),
            )
            return None

        logger.info(
            "[ImmortusBrain] Activated — thread=%s depth=%d routes=%d",
            thread_id, depth, len(routes),
        )
        return ImmortusSession(
            task_id         = getattr(plan, "plan_id", session_id),
            thread_id       = thread_id,
            committed_route = routes[0],
            latent_routes   = routes[1:],
            temporal_coord  = temporal,
            depth           = depth,
        )

    # ── Thread assignment ─────────────────────────────────────────────────

    def _assign_thread_id(self, plan_id: str, session_id: str) -> str:
        prefix = (plan_id or "anon")[:4]
        origin = (session_id or "0000")[-4:]
        return f"immortus:thread-{prefix}-{origin}"

    # ── Dependency depth ──────────────────────────────────────────────────

    def _compute_dependency_depth(self, steps) -> int:
        step_map = {s.step_id: s for s in steps}
        memo: dict = {}

        def depth_of(step_id: str) -> int:
            if step_id in memo:
                return memo[step_id]
            step = step_map.get(step_id)
            if step is None:
                memo[step_id] = 1
                return 1
            deps = getattr(step, "depends_on", None) or []
            if not deps:
                memo[step_id] = 1
            else:
                memo[step_id] = 1 + max(depth_of(d) for d in deps)
            return memo[step_id]

        if not steps:
            return 0
        return max(depth_of(s.step_id) for s in steps)

    # ── Coordinate extraction ─────────────────────────────────────────────

    def _extract_entry_coordinates(self, plan, context_package):
        if context_package and hasattr(context_package, "mycelium_path"):
            return context_package.mycelium_path
        return None

    def _extract_objective_coordinates(self, plan, context_package):
        if context_package and hasattr(context_package, "objective_coords"):
            return context_package.objective_coords
        return None

    # ── Graph helpers ─────────────────────────────────────────────────────

    def _graph_is_mature(self) -> bool:
        if self.graph is None:
            return False
        try:
            if hasattr(self.graph, "is_mature"):
                return bool(self.graph.is_mature())
            store = getattr(self.graph, "_store", None)
            if store and hasattr(store, "_conn"):
                row = store._conn.execute(
                    "SELECT COUNT(*) FROM mycelium_traversals"
                ).fetchone()
                return int(row[0]) >= 20 if row else False
        except Exception:
            pass
        return False

    def _find_routes(self, entry, objective, temporal, thread_id) -> List["CoordinateRoute"]:
        try:
            return self.router.find_candidate_routes(
                entry, objective, temporal, thread_id, self.graph
            )
        except Exception as exc:
            logger.debug("[ImmortusBrain] route finding failed: %s", exc)
            return []

    # ── Cold start ────────────────────────────────────────────────────────

    def _cold_start_routes(self, plan, context_package, temporal, thread_id) -> List["CoordinateRoute"]:
        strategy = self._select_cold_start_strategy(plan, context_package)
        logger.debug("[ImmortusBrain] cold start strategy: %s", strategy.value)

        if strategy == ColdStartStrategy.SYNTHETIC_TRAILS:
            return self.router.synthetic_from_plan(plan, temporal, thread_id)
        elif strategy == ColdStartStrategy.SHALLOW_INFERENCE:
            return self.router.inference_routes(plan, context_package, temporal, thread_id)
        else:
            self._emit_plain_language_consult(plan)
            return []

    def _select_cold_start_strategy(self, plan, context_package) -> ColdStartStrategy:
        clarity = self._score_task_clarity(plan)
        novelty = self._score_coordinate_novelty(context_package)

        if clarity > IMMORTUS_CLARITY_THRESHOLD:
            return ColdStartStrategy.SYNTHETIC_TRAILS
        elif novelty < IMMORTUS_NOVELTY_THRESHOLD and clarity > 0.4:
            return ColdStartStrategy.SHALLOW_INFERENCE
        else:
            return ColdStartStrategy.USER_CONSULT

    def _score_task_clarity(self, plan) -> float:
        steps = getattr(plan, "steps", [])
        total = len(steps)
        if total == 0:
            return 0.0
        clear = sum(
            1 for s in steps
            if getattr(s, "depends_on", None) is not None
            and getattr(s, "expected_output", None)
        )
        return clear / total

    def _score_coordinate_novelty(self, context_package) -> float:
        if not context_package:
            return 1.0
        topo = getattr(context_package, "topology_position", "") or ""
        return 0.3 if "CORE" in topo else 0.7

    def _emit_plain_language_consult(self, plan) -> None:
        logger.info(
            "[ImmortusBrain] USER_CONSULT — plan '%s' has low clarity and high novelty. "
            "Consider adding depends_on and expected_output to plan steps.",
            getattr(plan, "plan_id", "?"),
        )
