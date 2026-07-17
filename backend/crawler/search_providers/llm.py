"""
LLMSearchProvider — URL generation via the local LLM (Cerebras).

This is the *existing* behavior: the LLM suggests authoritative URLs from its
parametric knowledge. No search engine API is queried. DuckDuckGo fallback has
been removed (see spec REQ-6).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date
from typing import Optional

from backend.crawler.search_providers.base import (
    SearchProvider,
    SearchResult,
    SearchResultItem,
)

logger = logging.getLogger(__name__)

_PLAN_PROMPT = """\
Today is {today}.
The user wants: {query}

Output ONLY valid JSON (no markdown, no explanation) with this exact structure:
{{
  "urls": ["<url1>", "<url2>"],
  "instructions": "<what to extract from the pages>",
  "result_type": "table",
  "title": "<short descriptive title>"
}}

Rules:
- urls: 1–5 highly relevant URLs. Prefer authoritative, up-to-date sources.
- instructions: concise sentence describing what fields/data to extract.
- result_type: "table" for lists of comparable items, "cards" for articles/results,
  "metrics" for numbers/stats, "mixed" for heterogeneous data.
- title: ≤8 words.
"""


class LLMSearchProvider(SearchProvider):
    """Generates candidate URLs from the local LLM's parametric knowledge.

    This is the original behavior of ``CrawlPlanner._call_llm``, extracted
    into a standalone ``SearchProvider`` so it can be used interchangeably
    with ``ExaSearchProvider``.
    """

    async def search(self, query: str, max_results: int = 10) -> SearchResult:
        """Request the LLM to suggest authoritative URLs for the query.

        Args:
            query: The search query.
            max_results: Max URLs to return (capped from LLM output).

        Returns:
            A ``SearchResult`` with item URLs only (no content — Crawl4AI
            fetches that later). Score is set to a neutral 0.5.
        """
        if not query or not query.strip():
            return SearchResult(query=query, provider="llm")

        prompt = _PLAN_PROMPT.format(today=date.today().isoformat(), query=query)
        try:
            raw = await asyncio.get_event_loop().run_in_executor(
                None, self._call_llm, prompt
            )
            return self._parse(raw, query, max_results)
        except Exception as exc:
            logger.warning(
                "[LLMSearchProvider] LLM call failed for %r: %s — returning empty",
                query[:60], exc,
            )
            return self._fallback(query)

    def _call_llm(self, prompt: str) -> str:
        """Synchronous LLM call (runs in executor to avoid blocking the loop)."""
        from backend.agent import get_agent_kernel  # lazy import
        kernel = get_agent_kernel("crawl_planner")
        return kernel._respond_direct(text=prompt, context={})  # noqa: SLF001

    def _parse(self, raw: str, query: str, max_results: int = 10) -> SearchResult:
        """Extract JSON from the LLM response.

        Strips markdown fences, searches for {…} JSON, extracts urls.
        Returns empty ``SearchResult`` on any parse failure.
        """
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            logger.warning("[LLMSearchProvider] no JSON in LLM output for %r", query[:60])
            return self._fallback(query)

        try:
            data = json.loads(match.group())
        except json.JSONDecodeError as exc:
            logger.warning("[LLMSearchProvider] JSON parse error: %s", exc)
            return self._fallback(query)

        urls = [u for u in data.get("urls", []) if isinstance(u, str)][:max_results]
        if not urls:
            logger.info("[LLMSearchProvider] LLM returned no URLs for %r", query[:60])
            return self._fallback(query)

        items = [
            SearchResultItem(
                url=url,
                title="",
                snippet="",
                content="",
                score=0.5,  # neutral — Crawl4AI assigns real credibility later
            )
            for url in urls
        ]
        return SearchResult(query=query, results=items, provider="llm")

    def _fallback(self, query: str) -> SearchResult:
        """Return empty result (no DuckDuckGo — per spec REQ-6)."""
        logger.info("[LLMSearchProvider] no URLs for %r — returning empty", query[:60])
        return SearchResult(query=query, provider="llm")
