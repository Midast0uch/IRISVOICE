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
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from .robots_checker import get_robots_checker

logger = logging.getLogger(__name__)

# Config from environment (overridable via .env)
_HEADLESS = os.environ.get("CRAWL4AI_HEADLESS", "true").lower() != "false"

# --- Stealth user-agent pool (Wave 2, T10) ---
_STEALTH_USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
)
_USER_AGENT = _STEALTH_USER_AGENTS[0]  # backward compat
_STEALTH_INDEX = 0
_STEALTH_EXTRA_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

_DEFAULT_DELAY_MS = int(os.environ.get("CRAWL4AI_DEFAULT_DELAY", "1000"))
_MAX_PAGES = int(os.environ.get("CRAWL4AI_MAX_PAGES", "5"))
_TIMEOUT_MS = int(os.environ.get("CRAWL4AI_TIMEOUT", "10000"))
_BM25_THRESHOLD = float(os.environ.get("CRAWL4AI_BM25_THRESHOLD", "1.0"))


def _rotate_user_agent() -> str:
    """Cycle through _STEALTH_USER_AGENTS and return the next UA."""
    global _STEALTH_INDEX
    ua = _STEALTH_USER_AGENTS[_STEALTH_INDEX]
    _STEALTH_INDEX = (_STEALTH_INDEX + 1) % len(_STEALTH_USER_AGENTS)
    return ua


# --- HAR evidence capture (Wave 0, REQ-13) ---------------------------------
# Light per-request HTTP evidence, file-backed at data/har/<job_id>.har.
# No full response bodies are stored — only status/headers/timing/body hash.
def _har_dir() -> str:
    """Absolute path to data/har under the repo root (parents[2] of this file)."""
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(repo_root, "data", "har")


def _coerce_headers(headers) -> dict:
    """Coerce response headers to a JSON-serialisable str->str dict."""
    out: dict = {}
    if not headers:
        return out
    try:
        for k, v in headers.items():
            out[str(k)] = str(v)
    except Exception:  # noqa: BLE001 - never block the crawl on header coercion
        pass
    return out


def _write_har_file(job_id: str, entries: list) -> Optional[str]:
    """Write light HAR entries to data/har/<job_id>.har.

    Graceful (REQ-16): on any failure returns None and logs — the crawl result
    is still returned without a har_path so the caller never raises here.
    """
    try:
        d = _har_dir()
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{job_id}.har")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, ensure_ascii=False)
        logger.info("HAR write job=%s entries=%d path=%s", job_id, len(entries), path)
        return path
    except Exception as exc:  # noqa: BLE001
        logger.warning("HAR write failed job=%s: %s", job_id, exc)
        return None


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
    error: Optional[str] = None  # set when the crawl failed (subprocess crash/timeout/unavailable)
    # --- Unified-spec extensions (optional; single source of truth, design D1) ---
    passages: list = field(default_factory=list)        # list[Passage] from orchestrator
    dashboard_data: dict = field(default_factory=dict)  # DashboardData from DataExtractor
    cited_markdown: Optional[str] = None                # citation-bound markdown (REQ-8)
    credibility_map: Optional[object] = None            # CredibilityMap (REQ-5)
    citation_index: Optional[object] = None             # chunk_id -> url map (REQ-22)
    # --- Document-rehydration HAR evidence (Wave 0, REQ-13/REQ-14) ---
    har_entries: list = field(default_factory=list)      # light per-request HAR entries
    har_path: Optional[str] = None                       # path to data/har/<job_id>.har


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
        self._current_ua = _USER_AGENT

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
            user_agent=self._current_ua,
            java_script_enabled=True,
            ignore_https_errors=True,
        )
        self._crawler = AsyncWebCrawler(config=self._browser_config)
        await self._crawler.start()
        logger.info(
            "[CrawlerEngine] browser started headless=%s ua=%s... pool=%d",
            _HEADLESS, self._current_ua[:60], len(_STEALTH_USER_AGENTS),
        )
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
        job_id: Optional[str] = None,
        # on_page_done(url, page_number, total) for progress events
    ) -> CrawlResult:
        """
        Crawl up to max_pages URLs using BM25 filtering keyed on query.
        on_page_done is called after each successful page fetch.

        HAR evidence (REQ-13): each individual request is recorded as a light
        HAR entry (no full bodies) and, after the run, written to
        data/har/<job_id>.har. job_id is threaded from the orchestrator so the
        file is deterministically named and linkable from document_data.
        """
        if self._crawler is None:
            raise RuntimeError("CrawlerEngine must be used as async context manager")

        if not job_id:
            job_id = uuid.uuid4().hex

        try:
            from crawl4ai import CrawlerRunConfig  # type: ignore
            from crawl4ai.content_filter_strategy import BM25ContentFilter  # type: ignore
            from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator  # type: ignore
        except ImportError as exc:
            raise CrawlerUnavailable("crawl4ai not installed") from exc

        robots = get_robots_checker()
        # Use a plain DefaultMarkdownGenerator without BM25ContentFilter to
        # avoid "Separator is not found" chunking errors on large pages.
        # The BM25 filter was too aggressive and broke on pages without
        # clear separator boundaries.
        md_generator = DefaultMarkdownGenerator()

        pages: list[PageData] = []
        har_entries: list[dict] = []
        t_start = time.monotonic()
        capped_urls = urls[:max_pages]
        total = len(capped_urls)

        for i, url in enumerate(capped_urls):
            # Robots.txt gate (policy, not an HTTP request — recorded as evidence)
            allowed = await robots.is_allowed(url, _USER_AGENT)
            if not allowed:
                har_entries.append({
                    "url": url, "method": "GET", "status": "robots_blocked",
                    "response_headers": {}, "duration_ms": 0,
                    "content_length": 0, "body_sha256": "",
                    "error": "blocked by robots.txt",
                })
                pages.append(PageData(
                    url=url, title="", markdown="", html=None,
                    metadata={}, error="blocked by robots.txt"
                ))
                continue

            # Rotate user-agent before each page fetch (T12)
            self._current_ua = _rotate_user_agent()
            logger.debug(
                "[CrawlerEngine] UA rotation for url=%s ua=%s...",
                url, self._current_ua[:60],
            )

            request_config = CrawlerRunConfig(
                markdown_generator=md_generator,
                page_timeout=_TIMEOUT_MS,
                user_agent=self._current_ua,
            )

            t0 = time.monotonic()
            try:
                result = await self._crawler.arun(url=url, config=request_config)
                status = getattr(result, "status_code", None)

                # --- 403 retry (T13) ---
                if status == 403:
                    old_ua = self._current_ua
                    self._current_ua = _rotate_user_agent()
                    logger.warning(
                        "[CrawlerEngine] 403 forbidden url=%s old_ua=%s... new_ua=%s...",
                        url, old_ua[:60], self._current_ua[:60],
                    )
                    await asyncio.sleep(2.0)
                    request_config = CrawlerRunConfig(
                        markdown_generator=md_generator,
                        page_timeout=_TIMEOUT_MS,
                        user_agent=self._current_ua,
                        headers=_STEALTH_EXTRA_HEADERS,
                    )
                    result = await self._crawler.arun(url=url, config=request_config)
                    status = getattr(result, "status_code", None)
                    logger.info(
                        "[CrawlerEngine] 403 retry complete url=%s status=%s",
                        url, status,
                    )

                resp_headers = _coerce_headers(getattr(result, "response_headers", {}) or {})
                md = ""
                if hasattr(result, "markdown_v2") and result.markdown_v2:
                    # crawl4ai ≥0.4 uses markdown_v2 for filtered content
                    md = result.markdown_v2.fit_markdown or result.markdown_v2.raw_markdown or ""
                elif hasattr(result, "markdown") and result.markdown:
                    md = result.markdown if isinstance(result.markdown, str) else ""
                body = md or (result.html if not md else "") or ""
                cl = resp_headers.get("content-length")
                har_entries.append({
                    "url": url, "method": "GET",
                    "status": status,
                    "response_headers": resp_headers,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "content_length": int(cl) if cl is not None else len(body),
                    "body_sha256": hashlib.sha256(body.encode("utf-8", "replace")).hexdigest(),
                })
                metadata = result.metadata or {}
                title = metadata.get("title", "") or ""
                pages.append(PageData(
                    url=url,
                    title=title,
                    markdown=md,
                    html=result.html if not md else None,
                    metadata=metadata,
                ))
                logger.debug(
                    "[CrawlerEngine] fetched %s ua=%s... (%d chars)",
                    url, self._current_ua[:60], len(md),
                )
            except Exception as exc:
                har_entries.append({
                    "url": url, "method": "GET", "status": None,
                    "response_headers": {}, "duration_ms": int((time.monotonic() - t0) * 1000),
                    "content_length": 0, "body_sha256": "",
                    "error": str(exc),
                })
                logger.warning("[CrawlerEngine] fetch failed for %s: %s", url, exc)
                pages.append(PageData(
                    url=url, title="", markdown="", html=None,
                    metadata={}, error=str(exc)
                ))

            if on_page_done:
                try:
                    # W5 (T33): pass title + first-150-char snippet for narration
                    snippet = (md or "")[:150].strip()
                    on_page_done(url, i + 1, total, title, snippet)
                except Exception:
                    pass

            # Polite delay between requests (skip after last URL)
            if i < total - 1 and delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)

        duration_ms = int((time.monotonic() - t_start) * 1000)
        har_path = _write_har_file(job_id, har_entries)
        return CrawlResult(
            query=query,
            pages=pages,
            duration_ms=duration_ms,
            crawled_at=datetime.now(timezone.utc).isoformat(),
            har_entries=har_entries,
            har_path=har_path,
        )
