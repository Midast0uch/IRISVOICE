"""Typed, routable node outcomes (REQ-1).

The vocabulary every action in the application returns. Seeded from the
crawler's proven ``UsabilityReason`` (backend/crawler/usability.py) — the
working prototype of a routable failure vocabulary — and widened only from
measured need. Adding a member to :class:`Reason` is a deliberate act: routing
decisions are decidable because the vocabulary is closed (REQ-1 AC3).

Three rules every node obeys (REQ-1):
  * A node returns a :class:`NodeOutcome`; it never signals failure by raising
    into the planner (AC2 — the runner converts any raise to
    ``NodeOutcome(FAILED, UNEXPECTED)``, see runner.py).
  * A partial result is a distinct status from success and failure (AC4) so
    the planner can decide whether partial is sufficient.
  * The typed reason survives into the existing node-record / error_type
    machinery (AC5, CT-3) — never into a parallel structure.

Refusals are a *status*, not a reason to route around (design D3). REFUSED
carrying ROBOTS_REFUSED / PERMISSION_DENIED is structurally terminal: the
router never re-routes it (REQ-4 AC4, REQ-8 AC3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional


class NodeStatus(str, Enum):
    """Terminal and intermediate statuses of a node execution (REQ-1)."""

    OK = "ok"
    PARTIAL = "partial"  # produced something, not everything (REQ-1 AC4)
    FAILED = "failed"
    REFUSED = "refused"  # deliberate: robots, permission, policy — TERMINAL (REQ-4 AC4)
    UNAVAILABLE = "unavailable"  # backing service absent (REQ-6 AC5)


class Reason(str, Enum):
    """Closed, enumerated failure vocabulary (REQ-1 AC3).

    Seeded from the crawler's proven set (backend/crawler/usability.py
    ``UsabilityReason``) and widened only from measured need. The crawler's
    reasons map 1:1 at the boundary (T11); the rest are the generalised forms
    the websearch funnel demonstrated — planner-gave-nothing, walls that park,
    deliberate refusals that terminate, and the reserved UNEXPECTED that the
    runner writes when a node raises despite REQ-1 AC2.

    Terminal members (never routed around): ROBOTS_REFUSED, PERMISSION_DENIED,
    and any REFUSED-status outcome.
    """

    NONE = "none"
    EMPTY = "empty"
    TOO_SHORT = "too_short"
    CHALLENGE = "challenge"
    TRANSPORT_ERROR = "transport_error"
    NO_CANDIDATES = "no_candidates"  # nothing to work on (e.g. planner gave 0 URLs)
    WALL = "wall"  # CAPTCHA / login / paywall -> park + ask
    ROBOTS_REFUSED = "robots_refused"  # TERMINAL, never routed around
    PERMISSION_DENIED = "permission_denied"  # TERMINAL
    BUDGET_EXCEEDED = "budget_exceeded"
    UPSTREAM_ERROR = "upstream_error"
    UNEXPECTED = "unexpected"  # reserved for REQ-1 AC2 raise-conversion


# Reasons that must NEVER be re-routed (REQ-4 AC4, REQ-8 AC3, design D3).
TERMINAL_REASONS: frozenset[Reason] = frozenset(
    {Reason.ROBOTS_REFUSED, Reason.PERMISSION_DENIED}
)


def is_terminal_reason(reason: Optional[Reason]) -> bool:
    """True when *reason* is structurally terminal — never routed around."""
    return reason in TERMINAL_REASONS


@dataclass(frozen=True)
class NodeOutcome:
    """The one outcome type every node returns (REQ-1 AC1)."""

    status: NodeStatus
    reason: Reason = Reason.NONE
    detail: str = ""
    artifact: Optional["Artifact"] = None
    # REQ-3 AC2: sub-node outcomes of a composite, recorded individually while
    # the composite keeps one outer outcome (design D5).
    sub_outcomes: List["NodeOutcome"] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        """True when the outcome is usable as a success (incl. partial)."""
        return self.status in (NodeStatus.OK, NodeStatus.PARTIAL)

    @property
    def terminal(self) -> bool:
        """True when this outcome must not be routed around."""
        return self.status == NodeStatus.REFUSED or is_terminal_reason(self.reason)

    def as_dict(self) -> dict:
        """Structured shape for logging / node-record plumbing (REQ-1 AC5)."""
        return {
            "status": self.status.value,
            "reason": self.reason.value,
            "detail": self.detail,
            "artifact_kind": self.artifact.kind if self.artifact else None,
            "sub_outcome_count": len(self.sub_outcomes),
        }


@dataclass
class Artifact:
    """The produced value of a node (REQ-6).

    Passed by REFERENCE for large media (design D7): a video or audio file is
    never materialised into the graph — ``ref`` carries the handle/path and the
    contract does not force materialisation (REQ-6 edge case).
    """

    kind: str  # "pages" | "text" | "audio_ref" | "video_ref" | "frames" | ...
    value: Any = None  # inline for small values
    ref: Optional[str] = None  # handle/path for large media

    @classmethod
    def by_ref(cls, kind: str, ref: str) -> "Artifact":
        """Build a by-reference artifact (large media — never inlined)."""
        return cls(kind=kind, ref=ref)
