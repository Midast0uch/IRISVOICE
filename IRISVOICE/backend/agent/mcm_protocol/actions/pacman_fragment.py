"""
Action: pacman_fragment
Stores the current LLM response as an episodic fragment for future recall.
Skips conversational turns — only stores tool outputs and DER results.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

# Minimum chars to bother storing
_MIN_FRAGMENT_CHARS = 80

# Keywords that indicate a DER/tool output worth storing
_DER_SIGNALS = [
    "completed", "created", "updated", "wrote", "found", "error",
    "step", "result", "output", "tool", "file", "function",
]


def _is_fragment_candidate(text: str) -> bool:
    """Return True if text looks like a DER step output worth storing."""
    if len(text) < _MIN_FRAGMENT_CHARS:
        return False
    text_lower = text.lower()
    return any(kw in text_lower for kw in _DER_SIGNALS)


def execute(ctx: dict, params: dict) -> dict:
    """
    ctx keys read:    mi, session_id, response_text, tool_name
    Never raises.
    """
    try:
        mi            = ctx.get("mi")
        response_text = ctx.get("response_text", "")
        tool_name     = ctx.get("tool_name", "")
        session_id    = ctx.get("session_id", "")

        if not mi or not response_text:
            return ctx

        episodic = getattr(mi, "episodic", None)
        if not episodic or not hasattr(episodic, "fragment_and_store"):
            return ctx

        # Strip MCM_MITO tags before storing
        import re
        clean_text = re.sub(r"<MCM_MITO>.*?</MCM_MITO>", "", response_text,
                            flags=re.DOTALL).strip()

        if not _is_fragment_candidate(clean_text):
            return ctx

        chunk_type = "der_output" if tool_name else "context_fragment"
        episodic.fragment_and_store(
            content=clean_text,
            session_id=session_id,
            chunk_type=chunk_type,
            tool_name=tool_name or None,
        )
        logger.debug("[pacman_fragment] stored %s fragment (%d chars)",
                     chunk_type, len(clean_text))

    except Exception as exc:
        logger.debug("[pacman_fragment] skipped: %s", exc)

    return ctx
