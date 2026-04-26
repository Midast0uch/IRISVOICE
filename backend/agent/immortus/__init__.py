"""Immortus 4D routing subsystem."""

from .constants import (
    IMMORTUS_DEPTH_THRESHOLD,
    IMMORTUS_CLARITY_THRESHOLD,
    IMMORTUS_NOVELTY_THRESHOLD,
    IMMORTUS_DRIFT_CRITICAL,
    IMMORTUS_DRIFT_WARNING,
    IMMORTUS_ROUTE_PIVOT_THRESHOLD,
    IMMORTUS_ROUTE_MAX_PIVOTS,
    IMMORTUS_ROUTE_CHECK_MIN_STEPS,
    IMMORTUS_DEPTH_LOG_WEIGHT,
    IMMORTUS_INTERSECTION_BOOST,
    IMMORTUS_CONDENSE_DEPTH_THRESHOLD,
    IMMORTUS_CONDENSE_CONFIDENCE_THRESHOLD,
)
from .temporal import TemporalCoordinate
from .route import CoordinateRoute
from .session import ImmortusSession
from .decisions import RouteDecision, ColdStartStrategy, PIVOT
from .brain import ImmortusBrain
from .router import SpeculativeRouter

__all__ = [
    "IMMORTUS_DEPTH_THRESHOLD",
    "IMMORTUS_CLARITY_THRESHOLD",
    "IMMORTUS_NOVELTY_THRESHOLD",
    "IMMORTUS_DRIFT_CRITICAL",
    "IMMORTUS_DRIFT_WARNING",
    "IMMORTUS_ROUTE_PIVOT_THRESHOLD",
    "IMMORTUS_ROUTE_MAX_PIVOTS",
    "IMMORTUS_ROUTE_CHECK_MIN_STEPS",
    "IMMORTUS_DEPTH_LOG_WEIGHT",
    "IMMORTUS_INTERSECTION_BOOST",
    "IMMORTUS_CONDENSE_DEPTH_THRESHOLD",
    "IMMORTUS_CONDENSE_CONFIDENCE_THRESHOLD",
    "TemporalCoordinate",
    "CoordinateRoute",
    "ImmortusSession",
    "RouteDecision",
    "ColdStartStrategy",
    "PIVOT",
    "ImmortusBrain",
    "SpeculativeRouter",
]
