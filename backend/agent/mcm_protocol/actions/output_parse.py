"""
Action: output_parse / OutputParser
Multi-format LLM output parser with NBL extraction.

Format priority:
  1. OpenAI tool_calls object  (API path — fastest)
  2. <tool_call name="...">...</tool_call>  (local model XML)
  3. ```json\\n{...}\\n```  (markdown-fenced JSON)
  4. Bare {"tool":...} or {"name":...}  (raw JSON)
  5. Plain text fallback

Also strips <MCM_MITO> blocks before storing as episode.
Extracts MYCELIUM: lines as nbl_state for context orchestrator.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ParsedResponse:
    tool_calls: list[dict]         = field(default_factory=list)
    content:    str                = ""
    nbl_state:  Optional[str]      = None   # extracted MYCELIUM: line if present
    raw:        str                = ""     # original response unchanged


class OutputParser:
    """Parse raw LLM output into structured tool calls + free text."""

    # MCM_MITO tag pattern
    _MITO_RE   = re.compile(r"<MCM_MITO>.*?</MCM_MITO>", re.DOTALL)
    # NBL line pattern
    _NBL_RE    = re.compile(r"(MYCELIUM:.*?)(?:\n|$)")
    # XML tool_call pattern
    _XML_TC_RE = re.compile(
        r'<tool_call\s+name=["\']([^"\']+)["\']>(.*?)</tool_call>',
        re.DOTALL,
    )
    # Markdown-fenced JSON
    _MD_JSON_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)

    def parse(self, response, model_name: str = "") -> ParsedResponse:
        """
        Main entry point.
        `response` can be an OpenAI response object or a plain string.
        """
        # ── Extract raw text ──────────────────────────────────────────────
        if isinstance(response, str):
            raw = response
            openai_tool_calls = None
        else:
            # OpenAI response object
            raw = ""
            openai_tool_calls = None
            try:
                choice = response.choices[0]
                raw = (choice.message.content or "")
                openai_tool_calls = getattr(choice.message, "tool_calls", None)
            except Exception:
                raw = str(response)

        result = ParsedResponse(raw=raw)

        # Extract NBL state before stripping tags
        nbl_match = self._NBL_RE.search(raw)
        if nbl_match:
            result.nbl_state = nbl_match.group(1).strip()

        # Strip MCM_MITO from content
        content_clean = self._MITO_RE.sub("", raw).strip()
        result.content = content_clean

        # ── Pass 1: OpenAI tool_calls object ─────────────────────────────
        if openai_tool_calls:
            try:
                for tc in openai_tool_calls:
                    fn   = tc.function
                    args = json.loads(fn.arguments) if isinstance(fn.arguments, str) else fn.arguments
                    result.tool_calls.append({"name": fn.name, "arguments": args})
                return result
            except Exception:
                pass

        # ── Pass 2: XML-style <tool_call> ────────────────────────────────
        xml_matches = self._XML_TC_RE.findall(content_clean)
        if xml_matches:
            for name, body in xml_matches:
                try:
                    args = json.loads(body.strip())
                except Exception:
                    args = {"raw": body.strip()}
                result.tool_calls.append({"name": name, "arguments": args})
            return result

        # ── Pass 3: Markdown-fenced JSON ─────────────────────────────────
        md_match = self._MD_JSON_RE.search(content_clean)
        if md_match:
            try:
                data = json.loads(md_match.group(1))
                tc   = self._extract_tool_from_dict(data)
                if tc:
                    result.tool_calls.append(tc)
                    return result
            except Exception:
                pass

        # ── Pass 4: Bare JSON object ──────────────────────────────────────
        stripped = content_clean.strip()
        if stripped.startswith("{"):
            try:
                data = json.loads(stripped)
                tc   = self._extract_tool_from_dict(data)
                if tc:
                    result.tool_calls.append(tc)
                    return result
            except Exception:
                pass

        # ── Pass 5: Plain text fallback ───────────────────────────────────
        return result

    @staticmethod
    def _extract_tool_from_dict(data: dict) -> Optional[dict]:
        """Try to extract a tool call from a parsed JSON dict."""
        # Handle OpenAI-style tool_calls array embedded in a JSON string
        # (e.g. local model outputting OpenAI-compatible JSON as text)
        if "tool_calls" in data and isinstance(data["tool_calls"], list) and data["tool_calls"]:
            tc_item = data["tool_calls"][0]
            fn = tc_item.get("function", {})
            name = fn.get("name") or tc_item.get("name")
            if name:
                args_raw = fn.get("arguments", {})
                args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
                return {"name": str(name), "arguments": args}
        name = data.get("tool") or data.get("name") or data.get("function")
        if not name:
            return None
        args = data.get("arguments") or data.get("parameters") or data.get("params") or {}
        return {"name": str(name), "arguments": args}


def execute(ctx: dict, params: dict) -> dict:
    """Action module wrapper — parse response_text and store in ctx."""
    try:
        raw = ctx.get("response_text") or ctx.get("raw_response", "")
        if not raw:
            return ctx
        parsed = OutputParser().parse(raw)
        ctx["parsed_response"] = parsed
        if parsed.nbl_state:
            ctx["nbl_state"] = parsed.nbl_state
    except Exception as exc:
        logger.debug("[output_parse] skipped: %s", exc)
    return ctx
