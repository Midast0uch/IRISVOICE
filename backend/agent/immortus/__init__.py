"""Immortus 4D routing subsystem."""

import uuid

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


def generate_thread_id(prefix: str = "anon", suffix: str | None = None) -> str:
    """Build a canonical Immortus thread id: ``immortus:thread-<p>-<s>``.

    Both ``prefix`` and ``suffix`` are truncated to 4 chars.  When ``suffix``
    is omitted a random 4-char suffix is generated, so repeated calls with the
    same prefix yield distinct ids.  Shared by the REST chat endpoints and
    ``ImmortusBrain._assign_thread_id`` so the format never drifts.
    """
    p = (prefix or "anon")[:4]
    s = (suffix or uuid.uuid4().hex)[-4:]
    return f"immortus:thread-{p}-{s}"


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
    "generate_thread_id",
]
