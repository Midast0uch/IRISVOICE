"""Outcome-driven router (REQ-4, REQ-8) — the edge that did not exist today.

When a node fails with a typed reason, the router matches that reason against
nodes that *advertise* recovery (``NodeSpec.recovers_reasons``) — nobody edits
the failing node's module to add a recovery path (design D4). This is the
property that makes new pipelines compose without new dispatch code.

Guards (REQ-4 AC4, REQ-8):
  * Terminal reasons (REFUSED / ROBOTS_REFUSED / PERMISSION_DENIED) are never
    routed around (CT-5). The robots case is not hypothetical — escalating a
    robots.txt refusal to a browser node that does not consult robots.txt
    would route around compliance for the exact URL just refused.
  * A recovery node's permission tier is evaluated exactly as a planned node's
    and may not exceed the approved tier (REQ-8 AC1/AC2) — routing never
    becomes a way around a permission gate (REQ-8).
  * Recovery attempts are bounded per originating step (REQ-4 AC3) — a node
    failing identically twice is terminal for that branch; cyclic advertisement
    is guarded by the same bound (REQ-4 edge).

Kill switch (REQ-7 AC4/AC5, design D8): when routing is disabled the router
returns no candidate and DER behaves exactly as before — the rollback path is
the precondition for landing this incrementally on a 12,291-line kernel.
"""

from __future__ import annotations

import logging
import os
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .outcome import NodeOutcome, NodeStatus, Reason, is_terminal_reason
from .spec import NodeSpec
from .telemetry import log_routing_decision

logger = logging.getLogger(__name__)

# ── Kill switch (REQ-7 AC4/AC5, design D8) ─────────────────────────────────
# One setting disables outcome-driven routing entirely, restoring today's
# behaviour. Default ON (routing enabled). Follows the repo's env-var-with-
# default pattern (e.g. CRAWL_MIN_CONTENT_CHARS in crawler/usability.py).
_ROUTING_ENV = "IRIS_NODE_ROUTING_ENABLED"


def routing_enabled() -> bool:
    """True when outcome-driven routing is on (REQ-7 AC4/AC5).

    ``IRIS_NODE_ROUTING_ENABLED=0`` (or "false"/"off") disables it — the router
    then returns no candidate and the loop behaves byte-for-byte as today.
    """
    _val = os.environ.get(_ROUTING_ENV, "1")
    return _val.strip().lower() not in ("0", "false", "off", "no")


# ── Bounds (REQ-4 AC3, REQ-4 edge) ─────────────────────────────────────────
# Recovery attempts per originating step. The second identical failure is
# terminal for that branch; cycles are guarded by the same bound.
DEFAULT_RECOVERY_BOUND = int(os.environ.get("IRIS_NODE_RECOVERY_BOUND", "1"))

# Memory bound on the per-step attempt counters. The router is a process-wide
# singleton whose step_ids are per-URL, so without a cap the map grows with
# every distinct URL for the life of the backend. Far above any single run's
# working set (a run tracks a handful of step_ids), so eviction can only ever
# reach counters from runs that are already over.
MAX_TRACKED_STEPS = int(os.environ.get("IRIS_NODE_MAX_TRACKED_STEPS", "512"))


# ── Permission tiers (REQ-8) ───────────────────────────────────────────────
_TIER_RANK = {"read_only": 0, "side_effect": 1, "destructive": 2}


def _tier_rank(tier: str) -> int:
    return _TIER_RANK.get(tier, 0)


@dataclass
class RouteRequest:
    """One failure to route (REQ-4 AC5 — the reason that triggered it)."""

    task_id: str
    step_id: str
    node: str
    outcome: NodeOutcome
    approved_tier: str = "read_only"  # the tier the user approved for this step
    attempts_remaining: int = 0  # per-step bound; <=0 means bound exhausted


@dataclass
class RouteDecision:
    """The router's answer (REQ-4 AC5, REQ-9 AC2)."""

    reason: Reason
    candidates: List[NodeSpec] = field(default_factory=list)
    selected: Optional[NodeSpec] = None
    blocked_by: Optional[str] = None  # "permission" | "terminal" | "bound"
    recorded: bool = True


class NodeRouter:
    """Matches a failure reason against nodes advertising recovery.

    Selection is deterministic (REQ-4 edge): nodes advertising the reason are
    ranked by declared ``preference`` (higher wins), then by name for stable
    ordering — cost/measured-success tie-breaks are an Open Question, deferred
    to REQ-9 AC2 data.
    """

    def __init__(self, recovery_bound: int = DEFAULT_RECOVERY_BOUND):
        self._recovery_bound = recovery_bound
        # name -> NodeSpec; populated once by the registry (T7) at startup.
        self._nodes: Dict[str, NodeSpec] = {}
        # step_id -> remaining recovery attempts (REQ-4 AC3).
        #
        # BOUNDED. This router is a process-wide singleton and step_ids are
        # per-URL ("esc:<url>", "race:<url>"), so entries are removed only by an
        # explicit reset_attempts — any run that aborts before its reset leaks
        # its entry for the life of the process, and the dict grows with every
        # distinct URL IRIS has ever seen. Oldest-first eviction is safe by
        # construction: dropping an entry restores the FULL recovery bound for a
        # step nobody is tracking anymore, so a live step's bound is never
        # loosened (a live step is, by definition, among the most recent).
        self._attempts: "OrderedDict[str, int]" = OrderedDict()

    # ── Registry wiring (called by tool_registry on register_node) ────────
    def register_node(self, spec: NodeSpec) -> None:
        self._nodes[spec.name] = spec

    def unregister_node(self, name: str) -> None:
        self._nodes.pop(name, None)

    def get_node(self, name: str) -> Optional[NodeSpec]:
        return self._nodes.get(name)

    def all_nodes(self) -> List[NodeSpec]:
        return list(self._nodes.values())

    # ── Routing ────────────────────────────────────────────────────────────
    def route(self, req: RouteRequest) -> Optional[RouteDecision]:
        """Pick a recovery node for *req*, or None when none exists / routing
        is disabled / the failure is terminal (REQ-4 AC6 — honest reporting).

        Returns a decision with candidates and selection when a route is taken;
        a decision with ``blocked_by`` when one was blocked; None when nothing
        advertises the reason or routing is disabled.
        """
        reason = req.outcome.reason

        # Kill switch (REQ-7 AC4): routing disabled -> today's path, no decision.
        if not routing_enabled():
            return None

        # Terminal reasons are never routed around (REQ-4 AC4, REQ-8 AC3, CT-5).
        if req.outcome.status == NodeStatus.REFUSED or is_terminal_reason(reason):
            log_routing_decision(
                task_id=req.task_id, step_id=req.step_id, node=req.node,
                reason=reason.value, candidates=[], selected=None,
                blocked_by="terminal",
            )
            return RouteDecision(reason=reason, blocked_by="terminal")

        candidates = [
            spec for spec in self._nodes.values()
            if spec.advertises_recovery(reason)
            and spec.name != req.node  # never route to the failing node itself
        ]
        if not candidates:
            # REQ-4 AC6: report honestly rather than retrying the same node.
            log_routing_decision(
                task_id=req.task_id, step_id=req.step_id, node=req.node,
                reason=reason.value, candidates=[], selected=None,
            )
            return None

        # Deterministic tie-break: preference desc, then name (REQ-4 edge).
        candidates.sort(key=lambda s: (-s.preference, s.name))

        # Attempt bound (REQ-4 AC3): the second identical failure is terminal.
        remaining = self._attempts.get(req.step_id, self._recovery_bound)
        if remaining <= 0:
            log_routing_decision(
                task_id=req.task_id, step_id=req.step_id, node=req.node,
                reason=reason.value, candidates=[s.name for s in candidates],
                selected=None, bound_hit=True,
            )
            return RouteDecision(
                reason=reason, candidates=candidates, blocked_by="bound",
            )

        # Permission guard (REQ-8 AC1/AC2): a recovery node may not exceed the
        # approved tier. Evaluate exactly as a planned node's tier.
        for spec in candidates:
            if _tier_rank(spec.permission_tier) > _tier_rank(req.approved_tier):
                log_routing_decision(
                    task_id=req.task_id, step_id=req.step_id, node=req.node,
                    reason=reason.value,
                    candidates=[s.name for s in candidates],
                    selected=spec.name, blocked_by="permission",
                )
                # REQ-8 edge: offer to the user rather than take silently —
                # recorded here; the DER integration surfaces it.
                return RouteDecision(
                    reason=reason, candidates=candidates,
                    selected=spec, blocked_by="permission",
                )

        selected = candidates[0]
        self._attempts[req.step_id] = remaining - 1
        self._attempts.move_to_end(req.step_id)
        while len(self._attempts) > MAX_TRACKED_STEPS:
            _stale, _ = self._attempts.popitem(last=False)
            logger.debug(
                "[router] evicting stale attempt counter step_id=%s "
                "(tracked=%d, bound=%d)",
                _stale, len(self._attempts), MAX_TRACKED_STEPS,
            )
        log_routing_decision(
            task_id=req.task_id, step_id=req.step_id, node=req.node,
            reason=reason.value,
            candidates=[s.name for s in candidates],
            selected=selected.name,
        )
        return RouteDecision(reason=reason, candidates=candidates, selected=selected)

    def reset_attempts(self, step_id: str) -> None:
        """Clear the per-step attempt counter (new step / new task)."""
        self._attempts.pop(step_id, None)

    def reset_all_attempts(self) -> None:
        self._attempts.clear()


# Process-wide router, wired by the registry at startup (T7).
_router: Optional[NodeRouter] = None


def get_node_router() -> NodeRouter:
    """Process-wide router instance (lazily created, wired by the registry)."""
    global _router
    if _router is None:
        _router = NodeRouter()
    return _router
