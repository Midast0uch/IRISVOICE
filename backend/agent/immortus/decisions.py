"""
RouteDecision, ColdStartStrategy, and the PIVOT helper.

TrailingDirector.check_route_viability() returns one of:
  RouteDecision.CONTINUE   — stay on committed route, nothing to do
  PIVOT(route, anchor)     — replace queue from anchor, swap committed route

ColdStartStrategy determines how the SpeculativeRouter behaves when the
Mycelium graph is immature (not enough traversal history for pheromone walks).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .route import CoordinateRoute


class ColdStartStrategy(Enum):
    SYNTHETIC_TRAILS  = "synthetic_trails"   # build route from plan step order
    SHALLOW_INFERENCE = "shallow_inference"  # one model call to generate route
    USER_CONSULT      = "user_consult"       # request clarification from user


@dataclass
class RouteDecision:
    action: str                             # "continue" | "pivot"
    route:  Optional["CoordinateRoute"] = None
    anchor: Optional[str]              = None  # step_id to pivot from

    @property
    def is_pivot(self) -> bool:
        return self.action == "pivot"


# Singleton — avoids allocating a new object on every check_route_viability() call
RouteDecision.CONTINUE = RouteDecision(action="continue")  # type: ignore[attr-defined]


def PIVOT(route: "CoordinateRoute", anchor: str) -> RouteDecision:
    """
    Convenience constructor for a pivot decision.

    Args:
        route:  The latent route to switch to.
        anchor: The step_id after which the queue is replaced.
    """
    return RouteDecision(action="pivot", route=route, anchor=anchor)
