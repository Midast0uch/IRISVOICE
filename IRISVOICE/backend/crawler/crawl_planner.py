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
        """
        Call the agent kernel to plan the crawl.
        Returns a CrawlPlan (falls back to a minimal plan on error).
        """
        prompt = _PLAN_PROMPT.format(today=date.today().isoformat(), query=query)
        try:
            raw = await asyncio.get_event_loop().run_in_executor(
                None, self._call_llm, prompt
            )
            return self._parse(raw, query)
        except Exception as exc:
            logger.warning("[CrawlPlanner] LLM call failed: %s — using fallback plan", exc)
            return self._fallback_plan(query)

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
        """Minimal safe fallback when LLM planning fails."""
        # Use a DuckDuckGo-style search URL as a fallback source
        encoded = query.replace(" ", "+")
        return CrawlPlan(
            urls=[f"https://duckduckgo.com/html/?q={encoded}"],
            instructions=f"Extract results relevant to: {query}",
            result_type="cards",
            title=query[:60],
        )


_planner: Optional[CrawlPlanner] = None


def get_crawl_planner() -> CrawlPlanner:
    global _planner
    if _planner is None:
        _planner = CrawlPlanner()
    return _planner
