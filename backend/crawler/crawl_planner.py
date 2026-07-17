"""
Crawl Planner — uses the agent kernel to plan what to fetch for a user query.

The LLM receives the query + current date and outputs a JSON plan:
  {
    "urls": ["https://..."],       // 1–5 URLs to crawl
    "instructions": "Extract: ...", // what to extract from page content
    "result_type": "table" | "cards" | "metrics" | "mixed",
    "title": "Human-readable title"
  }

Quality-check gates applied:
  - LLM call runs in executor (sync _respond_direct, avoids blocking event loop).
  - JSON parsing is defensive — fallback plan used if LLM output is malformed.
  - URL count capped at CRAWL4AI_MAX_PAGES before returning.
  - No shared mutable state across calls.
  - Lazy import of agent_kernel — doesn't trigger model load at import time.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy-imported: SourceRegistry, SearchProvider, get_search_provider

_MAX_PAGES = int(os.environ.get("CRAWL4AI_MAX_PAGES", "5"))


@dataclass
class CrawlPlan:
    urls: list[str]
    instructions: str
    result_type: str       # 'table' | 'cards' | 'metrics' | 'mixed'
    title: str


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


class CrawlPlanner:
    """Generates a CrawlPlan for a user query via LLM."""

    async def plan(self, query: str) -> CrawlPlan:
        """Plan a crawl, using cached sources from the SourceRegistry when possible.

        1. Check SourceRegistry first — if known URLs exist with sufficient
           coverage, return a CrawlPlan from cache (skip LLM).
        2. On MISS, call the LLM to generate URLs.
        3. Learn from the result so the next similar query hits the cache.
        """
        # ── Step 1: SourceRegistry check ───────────────────────────────
        from backend.crawler.source_registry import get_source_registry

        registry = get_source_registry()
        res = await registry.resolve(query)

        if res["hit"]:
            urls = [s["url"] for s in res["sources"]]
            logger.info(
                "[CrawlPlanner] cache HIT for %r — %d URL(s) from registry",
                query[:60], len(urls),
            )
            return CrawlPlan(
                urls=urls[:_MAX_PAGES],
                instructions="Extract all relevant information from the provided pages.",
                result_type="mixed",
                title=query[:60],
            )

        # ── Step 2: MISS — call LLM for URL generation ─────────────────
        prompt = _PLAN_PROMPT.format(today=date.today().isoformat(), query=query)
        plan: CrawlPlan
        try:
            raw = await asyncio.get_event_loop().run_in_executor(
                None, self._call_llm, prompt
            )
            plan = self._parse(raw, query)
        except Exception as exc:
            logger.warning("[CrawlPlanner] LLM call failed: %s — using fallback plan", exc)
            plan = self._fallback_plan(query)

        # ── Step 3: Learn from the LLM result (if any) ─────────────────
        if plan.urls:
            from backend.crawler.search_providers.base import SearchResult, SearchResultItem

            items = [SearchResultItem(url=u) for u in plan.urls]
            await registry.learn(query, SearchResult(query=query, results=items, provider="llm"))

        return plan

    def _call_llm(self, prompt: str) -> str:
        from backend.agent import get_agent_kernel  # lazy import
        kernel = get_agent_kernel("crawl_planner")
        return kernel._respond_direct(text=prompt, context={})

    def _parse(self, raw: str, query: str) -> CrawlPlan:
        """Extract JSON from LLM response, with defensive fallback."""
        # Strip markdown code fences if present
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
        # Find first { ... } block
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            logger.warning("[CrawlPlanner] no JSON found in LLM output")
            return self._fallback_plan(query)
        try:
            data = json.loads(match.group())
            urls = [u for u in data.get("urls", []) if isinstance(u, str)][:_MAX_PAGES]
            if not urls:
                return self._fallback_plan(query)
            return CrawlPlan(
                urls=urls,
                instructions=str(data.get("instructions", "Extract all relevant information.")),
                result_type=str(data.get("result_type", "mixed")),
                title=str(data.get("title", query[:60])),
            )
        except json.JSONDecodeError as exc:
            logger.warning("[CrawlPlanner] JSON parse error: %s", exc)
            return self._fallback_plan(query)

    def _fallback_plan(self, query: str) -> CrawlPlan:
        """Fallback when LLM planning fails.

        No search engine is used (DuckDuckGo was removed — see REQ-32 follow-up:
        the project uses LLM-generated URLs as the sole source so web search stays
        free and key-less). When the LLM cannot produce URLs we return an empty
        plan; the orchestrator then emits CRAWLER_ERROR "no candidate urls" rather
        than silently querying a search engine the user opted out of.
        """
        logger.warning(
            "[CrawlPlanner] LLM planning produced no URLs for %r; "
            "no search-engine fallback (DuckDuckGo removed). Crawl will report "
            "'no candidate urls'.", query
        )
        return CrawlPlan(
            urls=[],
            instructions="Extract all relevant information.",
            result_type="mixed",
            title=query[:48],
        )


_planner: Optional[CrawlPlanner] = None


def get_crawl_planner() -> CrawlPlanner:
    global _planner
    if _planner is None:
        _planner = CrawlPlanner()
    return _planner
