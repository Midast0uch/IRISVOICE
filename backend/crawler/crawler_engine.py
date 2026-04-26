"""
Crawler Engine — thin wrapper around Crawl4AI AsyncWebCrawler.

Quality-check gates applied:
  - Crawl4AI imported lazily (inside __aenter__) so the module loads fast even
    if crawl4ai is not yet installed; ImportError surfaces as CrawlerUnavailable.
  - One browser context per CrawlerEngine instance; never shared between tasks.
  - Context manager protocol enforces proper browser lifecycle (start → crawl → close).
  - Per-page errors do not abort the whole crawl — recorded in PageData.error.
  - BM25 threshold exposed as parameter; default 1.0 per spec.
  - Delay between requests enforced with asyncio.sleep.
  - Total crawl duration measured and returned in CrawlResult.
  - Robots.txt checked before each URL.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from .robots_checker import get_robots_checker

logger = logging.getLogger(__name__)

# Config from environment (overridable via .env)
_HEADLESS = os.environ.get("CRAWL4AI_HEADLESS", "true").lower() != "false"
_USER_AGENT = os.environ.get(
    "CRAWL4AI_USER_AGENT",
    "IRIS-Agent/1.0 (research assistant; respectful crawling)"
)
_DEFAULT_DELAY_MS = int(os.environ.get("CRAWL4AI_DEFAULT_DELAY", "1000"))
_MAX_PAGES = int(os.environ.get("CRAWL4AI_MAX_PAGES", "5"))
_TIMEOUT_MS = int(os.environ.get("CRAWL4AI_TIMEOUT", "10000"))
_BM25_THRESHOLD = float(os.environ.get("CRAWL4AI_BM25_THRESHOLD", "1.0"))


class CrawlerUnavailable(RuntimeError):
    """Raised when crawl4ai is not installed."""


@dataclass
class PageData:
    url: str
    title: str
    markdown: str            # Primary: clean LLM-ready text from BM25 filter
    html: Optional[str]      # Fallback raw HTML if markdown empty
    metadata: dict           # og tags, dates, authors, etc.
    error: Optional[str] = None


@dataclass
class CrawlResult:
    query: str
    pages: list[PageData]
    duration_ms: int
    crawled_at: str          # ISO 8601 UTC


class CrawlerEngine:
    """
    Async context manager that wraps Crawl4AI.
    Usage:
        async with CrawlerEngine() as engine:
            result = await engine.crawl(query, urls, instructions)
    """

    def __init__(self) -> None:
        self._crawler = None
        self._browser_config = None

    async def __aenter__(self) -> "CrawlerEngine":
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig  # type: ignore
        except ImportError as exc:
            raise CrawlerUnavailable(
                "crawl4ai is not installed. Run: pip install crawl4ai && "
                "python -m playwright install chromium"
            ) from exc

        self._browser_config = BrowserConfig(
            headless=_HEADLESS,
            user_agent=_USER_AGENT,
        )
        self._crawler = AsyncWebCrawler(config=self._browser_config)
        await self._crawler.start()
        logger.info("[CrawlerEngine] browser started (headless=%s)", _HEADLESS)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._crawler:
            try:
                await self._crawler.close()
            except Exception as exc:
                logger.debug("[CrawlerEngine] close error: %s", exc)
            finally:
                self._crawler = None
        logger.debug("[CrawlerEngine] browser closed")

    async def crawl(
        self,
        query: str,
        urls: list[str],
        instructions: str,
        max_pages: int = _MAX_PAGES,
        delay_ms: int = _DEFAULT_DELAY_MS,
        on_page_done: Optional[Callable[[str, int, int], None]] = None,
        # on_page_done(url, page_number, total) for progress events
    ) -> CrawlResult:
        """
        Crawl up to max_pages URLs using BM25 filtering keyed on query.
        on_page_done is called after each successful page fetch.
        """
        if self._crawler is None:
            raise RuntimeError("CrawlerEngine must be used as async context manager")

        try:
            from crawl4ai import CrawlerRunConfig  # type: ignore
            from crawl4ai.content_filter_strategy import BM25ContentFilter  # type: ignore
        except ImportError as exc:
            raise CrawlerUnavailable("crawl4ai not installed") from exc

        robots = get_robots_checker()
        content_filter = BM25ContentFilter(
            user_query=query,
            bm25_threshold=_BM25_THRESHOLD,
        )
        run_config = CrawlerRunConfig(
            content_filter=content_filter,
            page_timeout=_TIMEOUT_MS,
        )

        pages: list[PageData] = []
        t_start = time.monotonic()
        capped_urls = urls[:max_pages]
        total = len(capped_urls)

        for i, url in enumerate(capped_urls):
            # Robots.txt gate
            allowed = await robots.is_allowed(url, _USER_AGENT)
            if not allowed:
                pages.append(PageData(
                    url=url, title="", markdown="", html=None,
                    metadata={}, error="blocked by robots.txt"
                ))
                continue

            try:
                result = await self._crawler.arun(url=url, config=run_config)
                md = ""
                if hasattr(result, "markdown_v2") and result.markdown_v2:
                    # crawl4ai ≥0.4 uses markdown_v2 for filtered content
                    md = result.markdown_v2.fit_markdown or result.markdown_v2.raw_markdown or ""
                elif hasattr(result, "markdown") and result.markdown:
                    md = result.markdown if isinstance(result.markdown, str) else ""

                metadata = result.metadata or {}
                title = metadata.get("title", "") or ""
                pages.append(PageData(
                    url=url,
                    title=title,
                    markdown=md,
                    html=result.html if not md else None,
                    metadata=metadata,
                ))
                logger.debug("[CrawlerEngine] fetched %s (%d chars markdown)", url, len(md))
            except Exception as exc:
                logger.warning("[CrawlerEngine] fetch failed for %s: %s", url, exc)
                pages.append(PageData(
                    url=url, title="", markdown="", html=None,
                    metadata={}, error=str(exc)
                ))

            if on_page_done:
                try:
                    on_page_done(url, i + 1, total)
                except Exception:
                    pass

            # Polite delay between requests (skip after last URL)
            if i < total - 1 and delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)

        duration_ms = int((time.monotonic() - t_start) * 1000)
        return CrawlResult(
            query=query,
            pages=pages,
            duration_ms=duration_ms,
            crawled_at=datetime.now(timezone.utc).isoformat(),
        )
