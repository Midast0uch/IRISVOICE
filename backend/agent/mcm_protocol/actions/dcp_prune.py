"""
Action: dcp_prune
Loads DCP config from protocol, prunes messages, logs stats.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


def execute(ctx: dict, params: dict) -> dict:
    """
    ctx keys read:    messages, protocol
    ctx keys written: messages, dcp_stats
    Never raises.
    """
    try:
        from backend.agent.dcp import DCP
        protocol = ctx.get("protocol")
        cfg = protocol.core.dcp if protocol else None

        dcp = DCP(
            turn_protection=cfg.turn_protection if cfg else 6,
            error_age_turns=cfg.error_age_turns if cfg else 4,
        )
        pruned, stats = dcp.prune(ctx.get("messages", []))
        ctx["messages"]  = pruned
        ctx["dcp_stats"] = stats
        logger.debug(
            "[dcp_prune] %d→%d msgs, %d dedups, %d errors purged",
            stats.get("input_count", 0), stats.get("output_count", 0),
            stats.get("dedups", 0), stats.get("errors_purged", 0),
        )
    except Exception as exc:
        logger.debug("[dcp_prune] skipped: %s", exc)
    return ctx
