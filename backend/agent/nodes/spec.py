"""NodeSpec — node metadata wrapping the existing ToolSpec (REQ-2).

Design D1: extend the existing tool registry rather than creating a third
registry. ``NodeSpec`` *wraps* ``ToolSpec`` — it never duplicates its fields —
so every existing registration stays valid unchanged (REQ-7 AC3) and the
planner sees one interface for in-process, MCP-backed, subprocess-backed, and
composite nodes (REQ-2 AC3).

An undeclared tool (no NodeSpec) remains callable exactly as today (REQ-2 AC5,
REQ-7 AC1) via the runner's legacy adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional, Tuple

from .outcome import Reason

if TYPE_CHECKING:  # pragma: no cover — ToolSpec is pure data, import is safe
    from backend.agent.tool_registry import ToolSpec


@dataclass
class NodeSpec:
    """Declarative node metadata for one registered action.

    Fields:
      tool             — the existing ToolSpec descriptor, untouched (design D1).
      consumes         — artifact kinds accepted (REQ-6 AC2): which nodes can
                         legally follow which.
      produces         — artifact kind produced (REQ-6 AC2).
      emits_reasons    — the failure reasons this node can emit (closed set;
                         REQ-1 AC3 — a node cannot emit an unregistered reason,
                         CT-2).
      recovers_reasons — failure reasons this node can plausibly recover from
                         (REQ-4 AC1) — the advertisement the router matches on.
      preference       — deterministic tie-break when several nodes advertise
                         the same reason; higher wins (REQ-4 edge).
      composite_of     — sub-graph node names (REQ-3 AC1); when non-empty this
                         node is a composite whose sub-node outcomes are
                         recorded individually (REQ-3 AC2).
    """

    tool: "ToolSpec"
    consumes: Tuple[str, ...] = ()
    produces: str = ""
    emits_reasons: frozenset = frozenset()  # frozenset[Reason]
    recovers_reasons: frozenset = frozenset()  # frozenset[Reason]
    preference: int = 0
    composite_of: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate the closed vocabulary at registration (CT-2, REQ-1 AC3).

        A node declaring a reason that is not a :class:`Reason` member is a
        registration-time error — routing must never string-match.
        """
        for _r in self.emits_reasons:
            if not isinstance(_r, Reason):
                raise TypeError(
                    f"node {self.name!r} emits_reasons must contain Reason members, "
                    f"got {_r!r}"
                )
        for _r in self.recovers_reasons:
            if not isinstance(_r, Reason):
                raise TypeError(
                    f"node {self.name!r} recovers_reasons must contain Reason members, "
                    f"got {_r!r}"
                )

    # ── Pass-throughs to the wrapped ToolSpec (design D1 — no duplication) ──
    @property
    def name(self) -> str:
        return self.tool.name

    @property
    def description(self) -> str:
        return self.tool.description

    @property
    def permission_tier(self) -> str:
        """The wrapped tool's tier (read_only | side_effect | destructive).

        REQ-8 AC1/AC2: a recovery node's tier is evaluated exactly as a planned
        node's and may not exceed the approved tier — the router reads this
        property to enforce it.
        """
        return self.tool.permission_tier

    @property
    def executor(self) -> str:
        return self.tool.executor

    @property
    def is_composite(self) -> bool:
        return bool(self.composite_of)

    def advertises_recovery(self, reason: Reason) -> bool:
        """True when this node declares it can recover *reason* (REQ-4 AC1)."""
        return reason in self.recovers_reasons
