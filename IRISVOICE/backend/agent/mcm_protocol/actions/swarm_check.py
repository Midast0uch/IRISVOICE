"""
Action: swarm_check
Post-DER-step action — checks for compound join opportunities and manages
collaboration state. Runs as part of swarm_flow workflow when swarm is enabled.
Under 50 lines.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def execute(ctx: dict, params: dict) -> dict:
    """
    1. If agent has an active collab and progress >= threshold → open compound mode.
    2. If agent is idle and joinable tasks exist → surface them in ctx.
    Never raises.
    """
    swarm_coord = ctx.get("swarm_coordinator")
    if not swarm_coord:
        return ctx

    try:
        # Auto-open compound mode if primary agent reached progress threshold
        collab_id    = ctx.get("active_collab_id")
        progress_pct = float(ctx.get("task_progress_pct", 0.0))
        if collab_id and progress_pct > 0:
            opened = swarm_coord.maybe_open(
                collab_id, progress_pct,
                context_pin_id=ctx.get("context_pin_id"),
            )
            if opened:
                ctx["compound_opened"] = True
                logger.info("[swarm_check] Compound opened for %s at %.0f%%",
                            collab_id, progress_pct * 100)

        # Surface joinable tasks for idle agent
        joinable = swarm_coord.find_joinable_tasks()
        if joinable:
            ctx["joinable_swarm_tasks"] = joinable
            ctx["swarm_join_available"] = True
            logger.debug("[swarm_check] %d joinable task(s) found", len(joinable))

    except Exception as exc:
        logger.debug("[swarm_check] %s", exc)

    return ctx
