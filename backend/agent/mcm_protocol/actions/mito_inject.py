"""
Action: mito_inject
Builds <MCM_MITO> tag from current NBL state and injects at messages[position].
Falls back to plain system message if NBL build fails.
Per JsonManagement.md: agents treat this as internal biology, not a tool.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


def execute(ctx: dict, params: dict) -> dict:
    """
    ctx keys read:    messages, mi, session_id, thread_id, task, protocol
    ctx keys written: messages (MCM_MITO inserted at position)
    Never raises.
    """
    messages = ctx.get("messages", [])
    if not messages:
        return ctx

    try:
        from backend.memory.nbl import build_nbl, build_mito_tag

        mi         = ctx.get("mi")
        session_id = ctx.get("session_id", "")
        thread_id  = ctx.get("thread_id")
        task       = ctx.get("task", "")
        protocol   = ctx.get("protocol")

        # Get DB connection
        conn = None
        if mi:
            mycelium = getattr(mi, "_mycelium", None)
            if mycelium:
                conn = getattr(mycelium, "_conn", None)

        nbl_str = build_nbl(conn, session_id, thread_id)

        compress_pct = 0.70
        if protocol:
            compress_pct = protocol.core.compression.budget_pct

        # Count active pins cheaply (best effort)
        pin_count = 0
        if conn:
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM pins WHERE permanent = 1"
                ).fetchone()
                pin_count = int(row[0]) if row else 0
            except Exception:
                pass

        tag = build_mito_tag(
            nbl_str=nbl_str,
            task_id=task[:40] if task else "active",
            workflow="pre_call",
            compress_pct=compress_pct,
            pin_count=pin_count,
        )

        pos = min(params.get("position", 1), len(messages))
        messages.insert(pos, {"role": "system", "content": tag})
        ctx["messages"] = messages
        logger.debug("[mito_inject] inserted MCM_MITO at position %d", pos)

    except Exception as exc:
        logger.debug("[mito_inject] skipped: %s", exc)

    return ctx
