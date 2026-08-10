"""Node-graph observability (REQ-9) — off the critical path.

Every node execution, routing decision, graph amendment, and refused
amendment is logged with its task identifier so the executed graph is
reconstructable from the log alone (REQ-9 AC4). This codebase's history of
silent selection (19 built-but-never-called mechanisms; the Exa provider went
unused and undetected) is the reason: an unlogged routing decision is
unanswerable (REQ-9 Verified).

AC5: logging failure never propagates — every emit is wrapped so a logging
defect can never crash or block a node run.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("iris.nodes")

# REQ-9 edge case: high-fan-out graphs log rate-limited summaries rather than
# per-item lines. The router passes through summaries; per-item emission is the
# default and the caller may batch.
_MAX_DETAIL_CHARS = 400


def _safe_log(fn, fmt: str, *args: Any) -> None:
    try:
        fn(fmt, *args)
    except Exception:  # noqa: BLE001 — REQ-9 AC5: logging never propagates
        pass


def log_node_execution(
    *,
    task_id: str,
    node: str,
    status: str,
    reason: str,
    duration_ms: int,
    sub_count: int = 0,
) -> None:
    _safe_log(
        logger.info,
        "[NODE_EXEC] task=%s node=%s status=%s reason=%s duration_ms=%d subs=%d",
        task_id, node, status, reason, duration_ms, sub_count,
    )


def log_routing_decision(
    *,
    task_id: str,
    step_id: str,
    node: str,
    reason: str,
    candidates: list,
    selected: Optional[str],
    bound_hit: bool = False,
    blocked_by: Optional[str] = None,
) -> None:
    """REQ-9 AC2: every routing decision with reason, candidates, selection.

    ``blocked_by`` records permission/terminal-guard blocks (REQ-8 AC4).
    """
    _safe_log(
        logger.info,
        "[ROUTE] task=%s step=%s node=%s reason=%s candidates=%s selected=%s "
        "bound_hit=%s blocked_by=%s",
        task_id, step_id, node, reason, list(candidates),
        selected or "none", bound_hit, blocked_by or "none",
    )


def log_amendment(
    *,
    task_id: str,
    kind: str,  # "amend" | "refused"
    cause: str,
    detail: str = "",
) -> None:
    """REQ-9 AC3: every graph amendment and every refused amendment, with cause."""
    _safe_log(
        logger.info,
        "[AMEND] task=%s kind=%s cause=%s detail=%s",
        task_id, kind, cause, (detail or "")[:_MAX_DETAIL_CHARS],
    )
