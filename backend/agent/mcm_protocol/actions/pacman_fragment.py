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

# Tools whose output derives from external/web sources. Their fragments are
# routed to the 'reference' zone (episodic.py:_ZONE_REFERENCE, reserved for
# "external content (future)") so untrusted web content is never mixed into
# the trusted/user or tool zones. See trust-routing plan W1.
_EXTERNAL_TOOLS = frozenset({"web_search", "crawler_query"})

# Zone used for external/web-derived fragments. Reuses the existing 'reference'
# slot rather than introducing a new enum value (plan decision #1).
_EXTERNAL_ZONE = "reference"


def _zone_for_tool(tool_name: str) -> str | None:
    """Return the zone a fragment should land in for ``tool_name``.

    External/web tools -> 'reference'; everything else -> None (let
    EpisodicStore apply its chunk_type default: trusted / tool).
    """
    if tool_name and tool_name in _EXTERNAL_TOOLS:
        return _EXTERNAL_ZONE
    return None


def is_external_tool(tool_name: str) -> bool:
    """True if ``tool_name`` derives output from external/web sources.

    Shared by W1 (zone routing) and W2 (per-turn external flag) so the
    external-tool vocabulary lives in exactly one place.
    """
    return bool(tool_name) and tool_name in _EXTERNAL_TOOLS


def _serialize_credibility(meta: dict) -> str:
    """Compact, stable JSON for credibility/citation metadata (REQ-22)."""
    import json
    try:
        return json.dumps(meta, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        return json.dumps({"_unserializable": True}, default=str)


def _store_credibility_metadata(episodic, session_id: str, tool_name: str,
                                 credibility_map, citation_index) -> None:
    """Persist credibility + citation provenance to the 'reference' (untrusted)
    zone so untrusted web scoring is recallable but never mixed into trusted
    zones (REQ-22). Never raises.
    """
    try:
        payload: dict = {}
        if credibility_map is not None:
            # CredibilityMap may be a dataclass or dict; normalize to primitives.
            if hasattr(credibility_map, "__dict__"):
                cm = {k: v for k, v in vars(credibility_map).items()
                      if not k.startswith("_")}
            elif isinstance(credibility_map, dict):
                cm = credibility_map
            else:
                cm = {"value": str(credibility_map)}
            payload["credibility_map"] = cm
        if citation_index is not None:
            payload["citation_index"] = citation_index
        if not payload:
            return
        blob = (
            f"<CREDIBILITY_META tool={tool_name}>\n"
            f"{_serialize_credibility(payload)}\n"
            f"</CREDIBILITY_META>"
        )
        episodic.fragment_and_store(
            content=blob,
            session_id=session_id,
            chunk_type="der_output",
            zone=_EXTERNAL_ZONE,  # reference / untrusted
            tool_name=tool_name or None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[pacman_fragment] credibility metadata skipped: %s", exc)


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

        # Persist credibility/citation provenance for external/web tools
        # (REQ-22) BEFORE the content fragment, so the untrusted scoring is
        # recallable in the reference zone. Never blocks the content store.
        if is_external_tool(tool_name):
            _store_credibility_metadata(
                episodic,
                session_id,
                tool_name,
                ctx.get("credibility_map"),
                ctx.get("citation_index"),
            )

        # Strip MCM_MITO tags before storing
        import re
        clean_text = re.sub(r"<MCM_MITO>.*?</MCM_MITO>", "", response_text,
                            flags=re.DOTALL).strip()

        if not _is_fragment_candidate(clean_text):
            return ctx

        chunk_type = "der_output" if tool_name else "context_fragment"
        # An explicit zone hint (e.g. from a turn that touched external
        # sources) wins; otherwise route by tool_name. See trust-routing W2.
        zone = ctx.get("zone") or _zone_for_tool(tool_name)
        episodic.fragment_and_store(
            content=clean_text,
            session_id=session_id,
            chunk_type=chunk_type,
            zone=zone,
            tool_name=tool_name or None,
        )
        logger.debug("[pacman_fragment] stored %s fragment (%d chars)",
                     chunk_type, len(clean_text))

    except Exception as exc:
        logger.debug("[pacman_fragment] skipped: %s", exc)

    return ctx
