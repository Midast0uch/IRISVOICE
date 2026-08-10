"""Node runner — invoke a node, never let a raise reach the planner (REQ-1 AC2).

The runner is the only place a node's outcome is produced:

  * A declared node (has a NodeSpec) is invoked through the supplied executor
    (in production ``AgentToolBridge.execute_tool`` — the existing dispatch
    path, untouched) and its free-form result is adapted to a :class:`NodeOutcome`.
  * An undeclared legacy tool runs exactly as it does today (REQ-7 AC1) — the
    adapter maps its free-form result to a default outcome without blocking it.
  * Any raise is converted to ``NodeOutcome(FAILED, UNEXPECTED)`` (REQ-1 AC2,
    design Error Handling): the task must never die because a node raised.

The executor is injected (constructor / parameter) so the runner stays import-
lazy and unit-testable; nothing here imports agent_kernel.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional

from .outcome import Artifact, NodeOutcome, NodeStatus, Reason
from .spec import NodeSpec

logger = logging.getLogger(__name__)

# An executor runs one tool and returns its free-form result dict (the shape
# AgentToolBridge.execute_tool returns today: {"success": bool, "result": ...}
# or {"error": ...}).
Executor = Callable[[str, Dict[str, Any], str], Awaitable[Dict[str, Any]]]


# ── Result adaptation (REQ-7 AC1, REQ-1 edge cases) ────────────────────────


def adapt_legacy_outcome(
    tool_name: str,
    result: Any,
    *,
    started: float,
    artifact_kind: str = "text",
) -> NodeOutcome:
    """Adapt a free-form legacy tool result to a NodeOutcome (REQ-7 AC1).

    Deterministic mapping of today's result shapes — never blocks an undeclared
    tool, never requires its module to change:
      * ``{"success": True, "result": ...}``            -> OK
      * ``{"success": False, "error": ...}``            -> FAILED / typed reason
      * ``{"error": ...}`` (no success key)             -> FAILED / typed reason
      * anything else (raw text, dict without markers)  -> OK (best-effort)

    Failure error strings are mapped through the crawler vocabulary (T11
    boundary): "challenge detected" -> CHALLENGE, "no candidate urls" ->
    NO_CANDIDATES, "robots.txt refused" -> ROBOTS_REFUSED, etc. — the same
    mapping the DER seam and crawler use, so a legacy tool's failure becomes
    a routable reason (REQ-1 AC3). Unknown errors fall back to
    TRANSPORT_ERROR, and a legacy consumer still sees the identical free-form
    result it always saw.
    """
    detail = ""
    if isinstance(result, dict):
        success = bool(result.get("success"))
        error = result.get("error")
        if success or (error is None and "error" not in result):
            artifact = Artifact(kind=artifact_kind, value=result.get("result", result))
            outcome = NodeOutcome(
                status=NodeStatus.OK,
                detail=f"duration_ms={int((time.monotonic() - started) * 1000)}",
                artifact=artifact,
            )
        else:
            detail = str(error) if error else "legacy tool returned failure"
            outcome = outcome_from_crawler_error(detail, started)
    else:
        # Raw non-dict result (str / None / list) — treat as success with the
        # value as artifact, exactly as today's callers consume it.
        outcome = NodeOutcome(
            status=NodeStatus.OK,
            detail=f"duration_ms={int((time.monotonic() - started) * 1000)}",
            artifact=Artifact(kind=artifact_kind, value=result),
        )
    logger.debug(
        "[node:runner][tool=%s] adapted legacy outcome status=%s reason=%s",
        tool_name, outcome.status.value, outcome.reason.value,
    )
    return outcome


def outcome_from_crawler_error(error_str: str, started: float) -> NodeOutcome:
    """Map a crawler failure string to a typed reason (T11 boundary).

    The crawler's own vocabulary is ``backend/crawler/usability.py``
    ``UsabilityReason`` (OK/EMPTY/TOO_SHORT/CHALLENGE/TRANSPORT_ERROR). The
    orchestrator additionally emits string reasons this project already
    established — map the ones the router can act on here, at the boundary,
    so ``usability.py`` itself needs no change.
    """
    low = (error_str or "").lower()
    reason = Reason.TRANSPORT_ERROR
    if "no candidate" in low or "no urls" in low or "zero urls" in low:
        reason = Reason.NO_CANDIDATES
    elif "robots" in low:
        # Must precede the "bot" check — "robots.txt" contains "bot".
        reason = Reason.ROBOTS_REFUSED
    elif "challenge" in low or "bot" in low or "captcha" in low:
        reason = Reason.CHALLENGE
    elif "below rerank" in low or "below threshold" in low:
        reason = Reason.EMPTY
    elif "budget" in low or "exhausted" in low:
        reason = Reason.BUDGET_EXCEEDED
    return NodeOutcome(
        status=NodeStatus.FAILED,
        reason=reason,
        detail=error_str or "",
        artifact=None,
    )


# ── Runner ─────────────────────────────────────────────────────────────────


class NodeRunner:
    """Invoke nodes through an injected executor, converting everything to
    outcomes (REQ-1 AC2) and adapting legacy tools (REQ-7 AC1)."""

    def __init__(self, executor: Optional[Executor] = None):
        # Production wiring happens once at startup (tool_bridge / kernel);
        # tests inject a fake executor.
        self._executor: Optional[Executor] = executor

    def set_executor(self, executor: Executor) -> None:
        self._executor = executor

    async def run(
        self,
        name: str,
        params: Dict[str, Any],
        *,
        node_spec: Optional[NodeSpec] = None,
        session_id: str = "",
        plan_title: str = "",
    ) -> NodeOutcome:
        """Invoke *name* and return its outcome. Never raises (REQ-1 AC2).

        ``node_spec`` is the declared metadata when the tool has one; when
        None the tool is treated as legacy and adapted (REQ-7 AC1).
        """
        if self._executor is None:
            return NodeOutcome(
                status=NodeStatus.UNAVAILABLE,
                reason=Reason.UPSTREAM_ERROR,
                detail="node runner has no executor wired",
            )
        started = time.monotonic()
        try:
            result = await self._executor(name, params, session_id)
        except Exception as exc:  # noqa: BLE001 — REQ-1 AC2: raise -> UNEXPECTED
            logger.warning(
                "[node:runner][tool=%s] raised during execution: %s", name, exc,
                exc_info=True,
            )
            return NodeOutcome(
                status=NodeStatus.FAILED,
                reason=Reason.UNEXPECTED,
                detail=f"{type(exc).__name__}: {exc}",
            )
        return adapt_legacy_outcome(name, result, started=started)


# Module-level convenience instance (wired at startup, imported lazily).
_runner: Optional[NodeRunner] = None


def get_node_runner() -> NodeRunner:
    """Process-wide runner. The executor is wired once at startup."""
    global _runner
    if _runner is None:
        _runner = NodeRunner()
    return _runner


async def run_node(
    name: str,
    params: Dict[str, Any],
    *,
    node_spec: Optional[NodeSpec] = None,
    session_id: str = "",
    plan_title: str = "",
) -> NodeOutcome:
    """Standalone convenience: run one node through the process-wide runner."""
    return await get_node_runner().run(
        name, params, node_spec=node_spec, session_id=session_id, plan_title=plan_title,
    )
