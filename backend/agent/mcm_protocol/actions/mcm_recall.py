"""
Action: mcm_recall
Runs the NBL-first recall fallback ladder and stores results in ctx.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


def execute(ctx: dict, params: dict) -> dict:
    """
    ctx keys read:    mi, session_id, thread_id, task
    ctx keys written: recall_results (list[dict])
    Never raises.
    """
    ctx["recall_results"] = []

    try:
        from backend.agent.mcm import MCM

        mi         = ctx.get("mi")
        session_id = ctx.get("session_id", "")
        thread_id  = ctx.get("thread_id")
        query      = ctx.get("task", "") or ctx.get("query", "")

        if not mi or not query:
            return ctx

        mcm = MCM(memory_interface=mi, session_id=session_id, thread_id=thread_id)
        results = mcm.recall(query)
        ctx["recall_results"] = results
        logger.debug("[mcm_recall] %d results for query '%s'", len(results), query[:40])

    except Exception as exc:
        logger.debug("[mcm_recall] skipped: %s", exc)

    return ctx
