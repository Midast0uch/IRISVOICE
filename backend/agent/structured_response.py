"""Parse structured speak/show JSON responses from the LLM.

Implements the Issue C.1 contract: when the agent generates a document, the
LLM returns JSON with a ``speak`` field (what TTS reads — short, conversational)
and an optional ``show`` field (what renders visually — the full content).
Plain-text responses fall through unchanged (backward compatible).

This module is intentionally dependency-free (only stdlib) so it can be
imported cheaply by both ``agent_kernel`` and ``iris_gateway`` and unit-tested
without pulling in the heavy backend package.
"""
from __future__ import annotations

import json
import re
from typing import Dict, Optional, Tuple

# Matches an optional leading/trailing markdown code fence:  ```json\n ... \n```
_FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\n(.*)\n```\s*$", re.DOTALL)


def _strip_fences(text: str) -> str:
    """Remove a surrounding ```...``` markdown code fence if present."""
    text = text.strip()
    m = _FENCE_RE.match(text)
    if m:
        return m.group(1).strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
        text = text.strip()
    return text


def parse_structured_response(text: str) -> Tuple[Optional[str], Optional[Dict]]:
    """Parse a structured speak/show response.

    Returns ``(speak, show)`` where:
      * ``speak`` is the short conversational summary for TTS (``str``) or
        ``None`` when the response is not structured.
      * ``show`` is the visual document payload (``dict`` with ``format``,
        ``content``, ``alternatives``) or ``None``.

    If the text is not valid structured JSON, returns ``(None, None)`` so the
    caller treats the entire text as a plain conversational response.  This is
    the backward-compatible fallback — old free-text behavior is preserved.
    """
    if not text or not text.strip():
        return (None, None)

    cleaned = _strip_fences(text)
    if not cleaned.startswith("{"):
        return (None, None)

    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return (None, None)

    if not isinstance(data, dict):
        return (None, None)

    speak = data.get("speak")
    show = data.get("show")

    if speak is None and show is None:
        return (None, None)

    speak_out = speak if isinstance(speak, str) else None
    show_out = show if isinstance(show, dict) else None
    return (speak_out, show_out)


def build_reformat_payload(
    reformatted_text: str,
    target_format: str,
    turn_id: Optional[str] = None,
    conversation_id: str = "default",
    original_format: Optional[str] = None,
) -> Dict:
    """Turn an LLM reformat response into a DOCUMENT_RENDER payload (Issue D.2).

    Accepts either structured JSON (``{"show": {...}}``) or plain text.  The
    original format is offered back as an alternative so the user can toggle
    between formats.  Pure and dependency-free — safe to unit test directly.
    """
    speak, show = parse_structured_response(reformatted_text)
    if show is not None:
        new_format = show.get("format", target_format)
        new_content = show.get("content", "")
        alternatives = list(show.get("alternatives", []))
    else:
        new_format = target_format
        new_content = reformatted_text
        alternatives = []
    if original_format and original_format not in alternatives:
        alternatives = [original_format] + alternatives
    return {
        "format": new_format,
        "content": new_content,
        "alternatives": alternatives,
        "turn_id": turn_id,
        "conversation_id": conversation_id,
        "reformatted": True,
    }
