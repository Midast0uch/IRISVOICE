"""
Action: mcm_check_compress
Checks if the context has hit the compression budget threshold.
If yes (or force=True), runs MCM.compress() and injects recovery preamble.
Sets ctx["compressed"] = True when compression fires.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


def execute(ctx: dict, params: dict) -> dict:
    """
    ctx keys read:    mi, session_id, thread_id, messages, protocol
    ctx keys written: messages (replaced with recovery on compression),
                      compressed (bool)
    Never raises.
    """
    ctx["compressed"] = False

    try:
        from backend.agent.mcm import MCM

        mi         = ctx.get("mi")
        session_id = ctx.get("session_id", "")
        thread_id  = ctx.get("thread_id")
        messages   = ctx.get("messages", [])
        protocol   = ctx.get("protocol")
        force      = params.get("force", False)

        if not mi:
            return ctx

        # Get budget from protocol config
        budget_pct = 0.70
        max_tokens_hint = 32768
        if protocol:
            budget_pct = protocol.core.compression.budget_pct

        mcm = MCM(
            memory_interface=mi,
            session_id=session_id,
            thread_id=thread_id,
            budget_pct=budget_pct,
        )

        current_tokens = MCM.count_tokens(messages)

        if not force and not mcm.should_compress(current_tokens, max_tokens_hint):
            return ctx

        # Fire compression
        active_task = ctx.get("task", "")
        compressed = mcm.compress(
            active_task=active_task or None,
            active_files=ctx.get("active_files", []),
            unverified_edits=ctx.get("unverified_edits", []),
            warnings=ctx.get("warnings", []),
        )

        ctx["messages"]   = mcm.inject_recovery(messages, compressed)
        ctx["compressed"] = True
        logger.info(
            "[mcm_check_compress] compression fired — %d→%d messages, NBL: %s",
            len(messages), len(ctx["messages"]),
            compressed.get("nbl", "")[:60],
        )

    except Exception as exc:
        logger.warning("[mcm_check_compress] failed: %s", exc)

    return ctx
