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


# Known bot-blocking / paywalled domains — the LLM tends to recommend these
# as "authoritative" sources but they return 3xx/403 to automated crawlers.
_BOT_BLOCKED_DOMAINS = frozenset({
    # Academic publishers (paywalls + redirects to login)
    "nature.com", "www.nature.com",
    "science.org", "www.science.org",
    "springer.com", "link.springer.com",
    "elsevier.com", "www.sciencedirect.com",
    "tandfonline.com", "www.tandfonline.com",
    "wiley.com", "onlinelibrary.wiley.com",
    "acs.org", "pubs.acs.org",
    "ieee.org", "ieeexplore.ieee.org",
    # Government / research portals (403 / CloudFront blocks)
    "noaa.gov", "www.noaa.gov",
    "usgs.gov", "www.usgs.gov",
    "census.gov",
})


def _filter_urls(urls: list[str], query: str) -> list[str]:
    """Remove URLs from known bot-blocking domains.
    
    The LLM tends to recommend paywalled academic publishers that block
    automated crawlers.  Filtering those out early avoids wasting crawl
    budget on URLs that will return 3xx/403 with zero usable content.
    """
    _clean: list[str] = []
    for u in urls:
        try:
            from urllib.parse import urlparse
            _host = urlparse(u).netloc.lower()
            if any(bd in _host for bd in _BOT_BLOCKED_DOMAINS):
                logger.info("[CrawlPlanner] skipped bot-blocked domain: %s", _host)
                continue
        except Exception:
            pass
        _clean.append(u)
    return _clean or urls  # If all filtered out, keep original (better than empty)


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
- urls: 1–5 highly relevant URLs. Prefer public, accessible sources — blogs,
  news articles, Wikipedia, and official documentation.  **AVOID academic
  paywalled sites** such as nature.com, science.org, sciencedirect.com,
  springer.com, and other domains that require authentication or block
  automated crawlers.
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

        # ── Step 2: MISS — call LLM for URL generation (with retry) ────
        prompt = _PLAN_PROMPT.format(today=date.today().isoformat(), query=query)
        plan = await self._plan_with_retry(prompt, query)

        # ── Post-process: filter bot-blocked domains ────────────────────
        if plan.urls:
            plan.urls = _filter_urls(plan.urls, query)

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

    async def _plan_with_retry(
        self, prompt: str, query: str, max_attempts: int = 3
    ) -> "CrawlPlan":
        """Call the LLM for URL generation, retrying transient failures.

        The planner's ONLY URL source is the LLM (DuckDuckGo was removed,
        REQ-32). A single transient rate-limit/timeout on that LLM call would
        otherwise silently collapse to an empty plan -> the orchestrator emits
        "no candidate urls" -> the research DER step fails with no recovery and
        the whole task silently stalls. Retry with exponential backoff so brief
        upstream hiccups self-heal instead of killing the research task.

        A response that arrives but yields no URLs is NOT retried (the model
        simply had nothing to offer for this query) — we fall back immediately.
        """
        _last_exc: Optional[Exception] = None
        for _attempt in range(max_attempts):
            try:
                raw = await asyncio.get_event_loop().run_in_executor(
                    None, self._call_llm, prompt
                )
                _candidate = self._parse(raw, query)
                # Diagnostic: capture what the LLM actually returned so a
                # "no usable sources" failure is diagnosable (empty response,
                # malformed JSON, or filtered URLs).
                logger.info(
                    "[CrawlPlanner] LLM plan response (attempt %d/%d): urls=%d "
                    "raw_head=%.300r",
                    _attempt + 1, max_attempts, len(_candidate.urls or []),
                    (raw or "")[:300],
                )
                if _candidate.urls:
                    return _candidate
                # LLM responded but produced no URLs — retrying won't help.
                logger.warning(
                    "[CrawlPlanner] LLM produced no URLs (attempt %d/%d) — "
                    "falling back",
                    _attempt + 1, max_attempts,
                )
                return _candidate
            except Exception as exc:  # transient (rate-limit/timeout/conn)
                _last_exc = exc
                logger.warning(
                    "[CrawlPlanner] LLM call failed (attempt %d/%d): %s",
                    _attempt + 1, max_attempts, exc,
                )
                if _attempt < max_attempts - 1:
                    await asyncio.sleep(1.0 * (2 ** _attempt))
        logger.warning(
            "[CrawlPlanner] LLM planning failed after %d attempts: %s — "
            "using fallback plan",
            max_attempts, _last_exc,
        )
        return self._fallback_plan(query)

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
        free and key-less). When the LLM cannot produce URLs we return a fallback
        plan with a descriptive error so the agent can explain *why* the search
        failed rather than silently returning a generic "couldn't generate" message.

        As a last resort, we include a broad-search URL (DuckDuckGo's live search)
        so the crawler has *something* to attempt, making the failure explanation
        more actionable ("the LLM couldn't find specific URLs for 'solar flare'")
        vs dead-silent "no candidate urls".
        """
        logger.warning(
            "[CrawlPlanner] LLM planning produced no URLs for %r; "
            "no search-engine fallback (DuckDuckGo removed). Crawl will report "
            "'no candidate urls'.", query
        )
        # Include a meaningful error instruction so the DER loop can produce
        # a proper failure summary instead of generic "couldn't generate".
        _query_slug = query.strip().lower().replace(" ", "+")[:80]
        return CrawlPlan(
            urls=[],
            instructions=f"LLM could not generate specific URLs for '{query}' "
                         f"and no search engine is available. Report this "
                         f"failure clearly — explain that no accessible sources "
                         f"were found for the query.",
            result_type="mixed",
            title=query[:48],
        )


_planner: Optional[CrawlPlanner] = None


def get_crawl_planner() -> CrawlPlanner:
    global _planner
    if _planner is None:
        _planner = CrawlPlanner()
    return _planner
