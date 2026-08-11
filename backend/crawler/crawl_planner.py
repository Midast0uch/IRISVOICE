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

        # DIAGNOSTIC: a MISS was previously SILENT — only the HIT branch logged.
        # That made "why didn't it reuse the URLs from last time?" unanswerable
        # from the log: you could not tell whether (a) nothing was ever learned,
        # (b) sources were known but scored below the coverage threshold, or
        # (c) topic extraction produced keys that never match what learn()
        # stored. Those three have OPPOSITE fixes, so log the discriminating
        # fields on EVERY resolve, hit or miss.
        logger.info(
            "[CrawlPlanner] registry resolve q=%r hit=%s coverage=%.2f "
            "threshold=%.2f known_sources=%d topics=%s",
            query[:60],
            res.get("hit"),
            float(res.get("coverage_score") or 0.0),
            float(getattr(registry, "_threshold", 0.0) or 0.0),
            len(res.get("sources") or []),
            (res.get("topics") or [])[:6],
        )
        if not res["hit"] and (res.get("sources") or []):
            # The most informative case: we DID know sources for this query and
            # still went to the LLM. Name them so the threshold can be judged
            # against real data rather than guessed at.
            logger.info(
                "[CrawlPlanner] registry MISS despite %d known source(s) — "
                "below coverage threshold; candidates: %s",
                len(res["sources"]),
                [s.get("url", "")[:60] for s in res["sources"][:5]],
            )

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

        # ── Step 1.5: configured search provider (e.g. Exa) ─────────────
        # get_search_provider() previously had ZERO production callers — a
        # user-configured provider="exa" + EXA_API_KEY had no effect no
        # matter what was in iris_config.json (CT-9 caller-existence class
        # of defect). Try it before the LLM path. Any failure, missing key,
        # or empty result falls through to the LLM path below, which stays
        # the default and is never bypassed or deleted.
        provider_plan = await self._plan_with_configured_provider(query)
        if provider_plan is not None:
            return provider_plan

        # ── Step 2: MISS — call LLM for URL generation (with retry) ────
        # Pre-flight rate probe: the planner's ONLY URL source is the LLM, and
        # a saturated provider would burn the transport's blind 3x retry loop
        # (~90s of Retry-After sleeps) before returning empty anyway. Probe
        # the window FIRST: saturated -> honest empty plan in milliseconds, so
        # the websearch fails fast (REQ-5 honest failure) instead of stalling.
        probe = await self._probe_rate_window()
        if probe is not None and probe.get("saturated"):
            logger.warning(
                "[CrawlPlanner] rate window saturated (%d reqs / %.0fs window, "
                "ceiling %.1f rpm) — skipping LLM, honest empty plan for %r",
                probe.get("requests", 0), probe.get("window_s", 60),
                probe.get("ceiling_rpm", 0), query[:60],
            )
            return self._empty_plan(query)

        prompt = _PLAN_PROMPT.format(today=date.today().isoformat(), query=query)
        plan = await self._plan_with_retry(prompt, query)

        # ── Post-process: filter bot-blocked domains ────────────────────
        if plan.urls:
            plan.urls = _filter_urls(plan.urls, query)

        # Every plan names WHICH path produced its URLs — a silent provider
        # choice is unanswerable in logs, which is how the Exa dead-wiring
        # defect survived undetected.
        logger.info(
            "[CrawlPlanner] source=llm urls=%d query=%r", len(plan.urls), query[:60],
        )

        # ── Step 3: Learn from the LLM result (if any) ─────────────────
        if plan.urls:
            from backend.crawler.search_providers.base import SearchResult, SearchResultItem

            items = [SearchResultItem(url=u) for u in plan.urls]
            await registry.learn(query, SearchResult(query=query, results=items, provider="llm"))

        return plan

    async def _plan_with_configured_provider(self, query: str) -> Optional["CrawlPlan"]:
        """Try the configured SearchProvider (e.g. Exa) before the LLM path.

        Returns ``None`` — meaning "fall through to the LLM path" — when:
          * the configured provider IS the LLM provider (the default, or
            ``"exa"`` already fell back internally because EXA_API_KEY was
            not set — see search_providers.get_search_provider),
          * the provider raises ``SearchProviderError`` (auth/rate-limit/
            timeout/upstream error),
          * or the provider returns zero results.

        Any other exception is also treated as fall-through (fail open) so
        a misbehaving provider can never crash a research call — the LLM
        path is the one guaranteed to still work.
        """
        from backend.crawler.search_providers import get_search_provider
        from backend.crawler.search_providers.llm import LLMSearchProvider
        from backend.crawler.search_providers.base import SearchProviderError

        try:
            provider = get_search_provider()
        except Exception as exc:  # noqa: BLE001 — fail open to the LLM path
            logger.warning(
                "[CrawlPlanner] get_search_provider() failed: %s — using LLM path", exc
            )
            return None

        if isinstance(provider, LLMSearchProvider):
            # provider="llm" (default), or provider="exa" already fell back
            # to LLM internally (missing key) — nothing extra to try here.
            return None

        # Normalise the class name to the short tag used in every log line
        # ("exa", "llm", ...) — matches SearchResult.provider so a failure
        # (no result to read .provider from) still logs the same tag a
        # success would (e.g. "ExaSearchProvider" -> "exa").
        _cls_name = type(provider).__name__
        source_name = (
            _cls_name[: -len("SearchProvider")].lower()
            if _cls_name.endswith("SearchProvider")
            else _cls_name.lower()
        )
        try:
            result = await provider.search(query, max_results=_MAX_PAGES)
        except SearchProviderError as exc:
            logger.warning(
                "[CrawlPlanner] source=%s failed for %r: %s — falling back to LLM",
                source_name, query[:60], exc,
            )
            return None
        except Exception as exc:  # noqa: BLE001 — fail open, never crash the plan
            logger.warning(
                "[CrawlPlanner] source=%s raised unexpectedly for %r: %s — "
                "falling back to LLM",
                source_name, query[:60], exc,
            )
            return None

        urls = [item.url for item in result.results if item.url][:_MAX_PAGES]
        if not urls:
            logger.info(
                "[CrawlPlanner] source=%s urls=0 query=%r — falling back to LLM",
                result.provider or source_name, query[:60],
            )
            return None

        urls = _filter_urls(urls, query)

        logger.info(
            "[CrawlPlanner] source=%s urls=%d query=%r",
            result.provider or source_name, len(urls), query[:60],
        )

        from backend.crawler.source_registry import get_source_registry

        registry = get_source_registry()
        await registry.learn(query, result)

        return CrawlPlan(
            urls=urls,
            instructions="Extract all relevant information from the provided pages.",
            result_type="mixed",
            title=query[:60],
        )

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

    async def _probe_rate_window(self) -> Optional[Dict[str, Any]]:
        """Probe the provider rate window BEFORE spending an LLM call.

        Returns the router's saturation probe for the reasoning role (the role
        the planner's LLM call resolves to), or None when unknown (fail-open:
        proceed). Uses run_in_executor because provider resolution + meter read
        are sync; the probe itself never sends a request or takes a slot.
        """
        try:
            return await asyncio.get_event_loop().run_in_executor(
                None, self._probe_rate_window_sync
            )
        except Exception as exc:  # noqa: BLE001 — fail-open, never stall
            logger.warning("[CrawlPlanner] rate-window probe failed open: %s", exc)
            return None

    @staticmethod
    def _probe_rate_window_sync() -> Optional[Dict[str, Any]]:
        try:
            from backend.agent import get_agent_kernel  # lazy import

            kernel = get_agent_kernel("crawl_planner")
            router = getattr(kernel, "_router", None)
            if router is None or not hasattr(router, "rate_window_probe"):
                return None  # fail-open: no probe available
            return router.rate_window_probe("reasoning")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CrawlPlanner] rate-window probe error: %s", exc)
            return None

    @staticmethod
    def _empty_plan(query: str) -> CrawlPlan:
        """Honest empty plan: no URLs, and instructions that name WHY, so the
        DER loop reports 'provider rate-limited' instead of dead 'no candidate
        urls' (REQ-5: failures are recorded AND shown)."""
        return CrawlPlan(
            urls=[],
            instructions="LLM planning was skipped: the provider rate window "
                         "was already saturated (recent 429s). Report this "
                         "failure clearly — retry the search shortly.",
            result_type="mixed",
            title=query[:48],
        )


_planner: Optional[CrawlPlanner] = None


def get_crawl_planner() -> CrawlPlanner:
    global _planner
    if _planner is None:
        _planner = CrawlPlanner()
    return _planner
