"""
Action: pacman_recall
Fetches episodic context for the current task and inserts as system message.
Capped at max_tokens to avoid bloating context.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


def execute(ctx: dict, params: dict) -> dict:
    """
    ctx keys read:    mi, task, messages, protocol
    ctx keys written: messages (episodic context inserted after MCM_MITO)
    Never raises.
    """
    try:
        mi   = ctx.get("mi")
        task = ctx.get("task", "")

        if not mi or not task:
            return ctx

        episodic = getattr(mi, "episodic", None)
        if not episodic:
            return ctx

        ep_ctx = episodic.assemble_episodic_context(task)
        if not ep_ctx or not ep_ctx.strip():
            return ctx

        # Enforce token cap (rough: chars / 4)
        max_tokens = params.get("max_tokens", 2000)
        max_chars  = max_tokens * 4
        if len(ep_ctx) > max_chars:
            ep_ctx = ep_ctx[:max_chars] + "\n[...truncated]"

        messages = ctx.get("messages", [])
        # Insert after MCM_MITO (position 2) so system prompt stays at 0
        insert_pos = min(2, len(messages))
        messages.insert(insert_pos, {
            "role": "system",
            "content": f"## Episodic Context\n{ep_ctx.strip()}",
        })
        ctx["messages"] = messages
        logger.debug("[pacman_recall] inserted episodic context (%d chars)", len(ep_ctx))

    except Exception as exc:
        logger.debug("[pacman_recall] skipped: %s", exc)

    return ctx
