"""CoordinateRoute — a candidate execution path through Mycelium space."""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import List, Optional

from .constants import IMMORTUS_DEPTH_LOG_WEIGHT
from .temporal import TemporalCoordinate


@dataclass
class CoordinateRoute:
    """
    A candidate execution path through coordinate space.

    Fields:
        route_id:        Unique identifier.
        thread_id:       Immortus thread that owns this route.
        steps:           Ordered list of step_ids this route covers.
        score:           Base route quality score (0.0 - 1.0).
        entry_coords:    Starting coordinate (from context_package).
        objective_coords: Target coordinate (from plan objective).
        pheromone_weight: Accumulated pheromone strength along this path.
    """
    route_id:         str
    thread_id:        str
    steps:            List[str]        = field(default_factory=list)
    score:            float            = 0.5
    entry_coords:     Optional[object] = None
    objective_coords: Optional[object] = None
    pheromone_weight: float            = 0.0

    def current_score(self, temporal: TemporalCoordinate) -> float:
        """
        Score adjusted by current temporal state.
        Formula: score * momentum * depth_factor
        """
        depth_factor = 1.0 + math.log(temporal.identifier_depth + 1) * IMMORTUS_DEPTH_LOG_WEIGHT
        return self.score * temporal.momentum * depth_factor

    def projected_score(self, temporal: TemporalCoordinate) -> float:
        """
        Projected score accounting for drift risk.
        Formula: score * (1 - drift * 0.5) * depth_factor
        """
        depth_factor = 1.0 + math.log(temporal.identifier_depth + 1) * IMMORTUS_DEPTH_LOG_WEIGHT
        return self.score * (1.0 - temporal.drift * 0.5) * depth_factor

    def steps_from(self, anchor_step_id: str) -> List[str]:
        """
        Return the sub-list of steps starting at (and including) anchor_step_id.
        Returns full list if anchor not found.
        """
        try:
            idx = self.steps.index(anchor_step_id)
            return self.steps[idx:]
        except ValueError:
            return list(self.steps)
