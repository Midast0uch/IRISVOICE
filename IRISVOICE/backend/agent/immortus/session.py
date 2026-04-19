"""ImmortusSession — active routing session for one plan execution."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional

from .route import CoordinateRoute
from .temporal import TemporalCoordinate


@dataclass
class ImmortusSession:
    """
    Active Immortus routing session created by ImmortusBrain.evaluate().

    Fields:
        task_id:          Plan / task identifier.
        thread_id:        Unique thread for this lineage in memory_chain.
        committed_route:  The route currently being executed.
        latent_routes:    Alternative routes available for pivot.
        temporal_coord:   Current 4D temporal state (updated each step).
        stable_anchor:    step_id with highest stability_score (pivot target).
        pivot_count:      Number of pivots taken this session.
        depth:            Dependency depth that triggered Immortus activation.
    """
    task_id:          str
    thread_id:        str
    committed_route:  CoordinateRoute
    latent_routes:    List[CoordinateRoute] = field(default_factory=list)
    temporal_coord:   TemporalCoordinate    = field(default_factory=TemporalCoordinate.cold)
    stable_anchor:    Optional[str]         = None
    pivot_count:      int                   = 0
    depth:            int                   = 0

    def best_latent(self) -> Optional[CoordinateRoute]:
        """Return the latent route with the highest current_score."""
        if not self.latent_routes:
            return None
        return max(
            self.latent_routes,
            key=lambda r: r.current_score(self.temporal_coord),
        )

    def can_pivot(self, max_pivots: int = 2) -> bool:
        return self.pivot_count < max_pivots

    def apply_pivot(self, new_route: CoordinateRoute) -> None:
        """Swap committed_route with new_route and increment pivot_count."""
        if new_route in self.latent_routes:
            self.latent_routes.remove(new_route)
        self.latent_routes.append(self.committed_route)
        self.committed_route = new_route
        self.pivot_count += 1
