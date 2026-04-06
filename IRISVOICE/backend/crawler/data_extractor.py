"""
Data Extractor — converts raw CrawlResult pages into a structured DashboardData dict.

The LLM receives:
  - Original user query
  - Combined Markdown from all pages (BM25-filtered, already clean)
  - Extraction instructions from the planner
  - Strict JSON output instructions

Output is a DashboardData-compatible dict that can be directly serialised
and sent as the 'data' field of an open_tab WS message.

Quality-check gates applied:
  - LLM call runs in executor (sync, non-blocking).
  - Combined markdown is capped at 12,000 chars to stay within context limits.
  - JSON parsing is defensive; fallback produces a single CardsSection from raw text.
  - No model loaded at import time (lazy import of agent_kernel).
  - No shared state between extraction calls.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from .crawler_engine import CrawlResult, PageData

logger = logging.getLogger(__name__)

_MAX_CONTEXT_CHARS = 12_000  # truncate combined markdown to avoid token overflow

_EXTRACT_PROMPT = """\
You are a data extraction assistant. Extract structured information from the crawled pages below.

User query: {query}
Extraction instructions: {instructions}
Expected result type: {result_type}

Crawled content (Markdown):
{content}

Output ONLY valid JSON matching this schema (no markdown, no preamble):
{{
  "title": "<title>",
  "query": "{query}",
  "timestamp": "<ISO 8601>",
  "summary": "<1-2 sentence overview>",
  "crawled_pages": {page_count},
  "duration_ms": {duration_ms},
  "sections": [
    // Use ONE OR MORE section types:
    // MetricsSection: {{"type": "metrics", "items": [{{"label": ..., "value": ..., "delta": ..., "trend": "up"|"down"|"flat"}}]}}
    // TableSection:   {{"type": "table", "title": ..., "headers": [...], "rows": [[...]]}}
    // CardsSection:   {{"type": "cards", "title": ..., "items": [{{"title":..., "subtitle":..., "body":..., "url":..., "tag":...}}]}}
    // ChartSection:   {{"type": "chart", "title": ..., "chart_type": "bar"|"line"|"pie", "labels": [...], "datasets": [{{"label":..., "values":[...]}}]}}
  ]
}}
"""


class DataExtractor:
    """Converts a CrawlResult into a DashboardData dict via LLM extraction."""

    async def extract(
        self,
        result: CrawlResult,
        instructions: str,
        result_type: str,
        title: str,
        pin_id: Optional[str] = None,
    ) -> dict:
        """
        Run LLM extraction on the crawl result.
        Returns a DashboardData-compatible dict.
        """
        # Build combined markdown, capped at context limit
        content_parts = []
        for page in result.pages:
            if page.error:
                content_parts.append(f"[Error fetching {page.url}: {page.error}]")
                continue
            if page.markdown:
                content_parts.append(f"--- Source: {page.url} ---\n{page.markdown}")
            elif page.html:
                content_parts.append(f"--- Source: {page.url} (HTML fallback) ---\n{page.html[:2000]}")

        combined = "\n\n".join(content_parts)
        if len(combined) > _MAX_CONTEXT_CHARS:
            combined = combined[:_MAX_CONTEXT_CHARS] + "\n\n[...truncated...]"

        prompt = _EXTRACT_PROMPT.format(
            query=result.query,
            instructions=instructions,
            result_type=result_type,
            content=combined,
            page_count=len(result.pages),
            duration_ms=result.duration_ms,
        )

        try:
            raw = await asyncio.get_event_loop().run_in_executor(
                None, self._call_llm, prompt
            )
            data = self._parse(raw, result, title)
        except Exception as exc:
            logger.warning("[DataExtractor] LLM extraction failed: %s — using fallback", exc)
            data = self._fallback_data(result, title)

        if pin_id:
            data["pin_id"] = pin_id

        return data

    def _call_llm(self, prompt: str) -> str:
        from backend.agent import get_agent_kernel  # lazy import
        kernel = get_agent_kernel("data_extractor")
        return kernel._respond_direct(text=prompt, context={})

    def _parse(self, raw: str, result: CrawlResult, title: str) -> dict:
        """Extract JSON from LLM output with defensive fallback."""
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            logger.warning("[DataExtractor] no JSON in LLM output")
            return self._fallback_data(result, title)
        try:
            data = json.loads(match.group())
            # Ensure required top-level fields
            data.setdefault("title", title)
            data.setdefault("query", result.query)
            data.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
            data.setdefault("summary", "")
            data.setdefault("crawled_pages", len(result.pages))
            data.setdefault("duration_ms", result.duration_ms)
            data.setdefault("sections", [])
            return data
        except json.JSONDecodeError as exc:
            logger.warning("[DataExtractor] JSON parse error: %s", exc)
            return self._fallback_data(result, title)

    def _fallback_data(self, result: CrawlResult, title: str) -> dict:
        """Minimal fallback: wrap each page as a card."""
        items = []
        for page in result.pages:
            if page.error:
                continue
            body = page.markdown[:300] + "…" if len(page.markdown) > 300 else page.markdown
            items.append({
                "title": page.title or page.url,
                "subtitle": page.url,
                "body": body or "(no content extracted)",
                "url": page.url,
            })
        return {
            "title": title,
            "query": result.query,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": f"Crawled {len(result.pages)} pages for: {result.query}",
            "crawled_pages": len(result.pages),
            "duration_ms": result.duration_ms,
            "sections": [{"type": "cards", "items": items}] if items else [],
        }


_extractor: Optional[DataExtractor] = None


def get_data_extractor() -> DataExtractor:
    global _extractor
    if _extractor is None:
        _extractor = DataExtractor()
    return _extractor
