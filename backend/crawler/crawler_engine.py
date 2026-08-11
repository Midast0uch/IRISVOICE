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
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from .capture_store import accepts_capture_page as _accepts_capture_page
from .robots_checker import get_robots_checker
from .usability import is_challenge_page  # REQ-4 primary-path detection

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
# NOTE (T11, REQ-5): _STEALTH_EXTRA_HEADERS is applied at BrowserConfig level —
# crawl4ai 0.8.6's CrawlerRunConfig has NO per-request `headers` param (verified
# via inspect.signature: extra headers are BrowserConfig-level, set once at
# browser launch). Passing this to CrawlerRunConfig(...) raises TypeError (see
# the 403-retry site below). BrowserConfig.__init__ DOES accept `headers`, so
# T11 wires it there (crawler_engine.py:__aenter__).
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
# T11 (REQ-5): randomised inter-request delay. Actual sleep is
# base * uniform(1-jitter, 1+jitter), so the crawl is not a metronome.
_DELAY_JITTER = float(os.environ.get("CRAWL4AI_DELAY_JITTER", "0.5"))
_MAX_PAGES = int(os.environ.get("CRAWL4AI_MAX_PAGES", "5"))
_TIMEOUT_MS = int(os.environ.get("CRAWL4AI_TIMEOUT", "10000"))
_BM25_THRESHOLD = float(os.environ.get("CRAWL4AI_BM25_THRESHOLD", "1.0"))


def _jittered_delay_ms(base_ms: int, jitter: float = _DELAY_JITTER) -> float:
    """Randomised delay around base_ms (T11, REQ-5).

    Pure function so tests can pin the range without sleeping. Zero jitter
    returns the exact base (deterministic politeness).
    """
    if jitter <= 0.0:
        return float(base_ms)
    low = max(0.0, base_ms * (1.0 - jitter))
    high = max(low + 1.0, base_ms * (1.0 + jitter))
    return random.uniform(low, high)


class RunCookieJar:
    """Run-scoped per-domain cookie persistence (T11, REQ-5).

    Deliberately NOT cross-run: the jar lives for the lifetime of one
    CrawlerEngine instance (one run) and is deleted on close. No credentials,
    no stable identity — a fresh run starts with an empty jar. This must not
    weaken robots_checker.py (REQ-5 AC3, CT-8) — the robots gate lives in
    crawl() and is untouched by this jar.
    """

    def __init__(self, job_id: str) -> None:
        self._job_id = job_id
        # domain -> list of cookie dicts captured this run
        self._cookies: dict[str, list[dict]] = {}

    def record_set_cookie(self, url: str, response_headers: Optional[dict]) -> None:
        """Harvest a Set-Cookie header from a response, scoped to its domain."""
        if not response_headers:
            return
        try:
            from urllib.parse import urlparse

            domain = urlparse(url).netloc
            for k, v in response_headers.items():
                if str(k).lower() == "set-cookie" and v:
                    self._cookies.setdefault(domain, []).append(
                        {"name": str(v).split("=", 1)[0], "value": str(v).split("=", 1)[1].split(";")[0]}
                    )
        except Exception as exc:  # noqa: BLE001 — cookie harvest must never break a fetch
            logger.debug("[RunCookieJar] harvest failed: %s", exc)

    def domain_cookies(self, url: str) -> list[dict]:
        from urllib.parse import urlparse

        return self._cookies.get(urlparse(url).netloc, [])

    @property
    def is_empty(self) -> bool:
        return not any(self._cookies.values())

    def clear(self) -> None:
        self._cookies.clear()


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
    # T1 (in-app-browser-surface): raw captured-HTML byte size, recorded for
    # EVERY page regardless of markdown presence. The replay store (T5) must
    # retain the raw HTML the agent reasoned over; this is the measured basis
    # for the REQ-1 AC5 retention bound and the srcdoc-vs-HTTP transport choice.
    html_bytes: Optional[int] = None


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
        # T11 (REQ-5): run-scoped cookie jar — created lazily on first crawl
        # (job_id known there), cleared on close. No cross-run identity.
        self._cookie_jar: Optional[RunCookieJar] = None
        # REQ-4 AC4: domains that served a challenge this run, so a later
        # timeout on the same domain can be recorded as challenge-suspected
        # (the 136-timeouts-vs-2-labelled-challenges undercount this fixes).
        self._challenge_domains: set[str] = set()

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
            # T11 (REQ-5): coherent stealth header set at the ONLY level
            # crawl4ai 0.8.6 accepts it (BrowserConfig, set once at launch).
            headers=dict(_STEALTH_EXTRA_HEADERS),
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
        # T11 (REQ-5): the run-scoped cookie jar dies with the run.
        if self._cookie_jar is not None:
            self._cookie_jar.clear()
            self._cookie_jar = None
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
        page_offset: int = 0,
        # on_page_done(url, page_number, total, title, snippet, capture_page)
    ) -> CrawlResult:
        """
        Crawl up to max_pages URLs using BM25 filtering keyed on query.
        on_page_done is called after each successful page fetch.

        HAR evidence (REQ-13): each individual request is recorded as a light
        HAR entry (no full bodies) and, after the run, written to
        data/har/<job_id>.har. job_id is threaded from the orchestrator so the
        file is deterministically named and linkable from document_data.

        ``page_offset`` reserves this call's block in the job's CAPTURE address
        space, which is NOT the UI's progress counter. Per-URL dispatch
        (orchestrator.dispatch_urls) runs one single-URL crawl per URL, so every
        such crawl would otherwise number its only page 1 and all five URLs
        would overwrite data/captures/<job>/1.html — the iframe then 404s for
        pages 2..5 (live 2026-08-11 16:11). The offset gives each URL its own
        block; ``capture_page`` is reported to on_page_done so the panel is told
        the number the bytes were actually SAVED under. Default 0 keeps the
        batch path (one crawl, all URLs) numbering exactly as before.
        """
        if self._crawler is None:
            raise RuntimeError("CrawlerEngine must be used as async context manager")

        if not job_id:
            job_id = uuid.uuid4().hex

        # T11 (REQ-5): run-scoped cookie jar, one per job. Robots gate is NOT
        # weakened — get_robots_checker() still gates every URL below.
        if self._cookie_jar is None:
            self._cookie_jar = RunCookieJar(job_id)

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
        # Probe ONCE, outside the loop: a `try capture_page / except TypeError`
        # retry per page would re-invoke (and double-emit) whenever the callback
        # itself raised TypeError internally. Signature inspection cannot
        # misread a runtime error as a signature mismatch.
        _cb_takes_capture_page = _accepts_capture_page(on_page_done)

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
            gen_exc: Optional[Exception] = None
            try:
                result = None
                status = None
                resp_headers = {}
                md = ""
                try:
                    result = await self._crawler.arun(url=url, config=request_config)
                    status = getattr(result, "status_code", None)

                    # --- 403 retry (T13) ---
                    # A bot-challenge interstitial is NOT a UA problem. Turnstile
                    # /cf-chl does not care which browser string asked, so the
                    # retry cannot win: it pays a 2s sleep plus a second full
                    # arun() (up to _TIMEOUT_MS) per challenged URL and then
                    # detects the same challenge. Under per-URL dispatch that
                    # cost is paid once PER URL, and challenged URLs are exactly
                    # the ones that go on to pay a vision escalation as well.
                    # Skip straight to the challenge verdict so the escalation
                    # starts sooner (REQ-4 AC1 already routes it).
                    if status == 403 and is_challenge_page(getattr(result, "html", None)):
                        logger.info(
                            "[CrawlerEngine] 403 + challenge markers url=%s — "
                            "skipping the UA retry (a rotated UA cannot pass a "
                            "challenge); escalating instead",
                            url,
                        )
                    elif status == 403:
                        old_ua = self._current_ua
                        self._current_ua = _rotate_user_agent()
                        logger.warning(
                            "[CrawlerEngine] 403 forbidden url=%s old_ua=%s... new_ua=%s...",
                            url, old_ua[:60], self._current_ua[:60],
                        )
                        await asyncio.sleep(2.0)
                        # D3 (T36 live smoke, 2026-08-09): this used to pass
                        # headers=_STEALTH_EXTRA_HEADERS here, but crawl4ai 0.8.6's
                        # CrawlerRunConfig has NO `headers` parameter (verified via
                        # inspect.signature — extra headers are a BrowserConfig-level
                        # concept in this version, set once at browser launch, not
                        # per-run). Every 403 retry raised
                        # "CrawlerRunConfig.__init__() got an unexpected keyword
                        # argument 'headers'" immediately, so the retry NEVER
                        # actually re-navigated — it always fell straight to the
                        # except-generation-failed branch below and the T13 retry
                        # was a no-op. Dropped the invalid kwarg so the retry
                        # attempt (new UA, fresh arun()) actually runs.
                        request_config = CrawlerRunConfig(
                            markdown_generator=md_generator,
                            page_timeout=_TIMEOUT_MS,
                            user_agent=self._current_ua,
                        )
                        result = await self._crawler.arun(url=url, config=request_config)
                        status = getattr(result, "status_code", None)
                        logger.info(
                            "[CrawlerEngine] 403 retry complete url=%s status=%s",
                            url, status,
                        )

                    resp_headers = _coerce_headers(getattr(result, "response_headers", {}) or {})
                    if hasattr(result, "markdown_v2") and result.markdown_v2:
                        # crawl4ai ≥0.4 uses markdown_v2 for filtered content
                        md = result.markdown_v2.fit_markdown or result.markdown_v2.raw_markdown or ""
                    elif hasattr(result, "markdown") and result.markdown:
                        md = result.markdown if isinstance(result.markdown, str) else ""
                except Exception as exc:
                    # crawl4ai's DefaultMarkdownGenerator throws
                    # "Separator is not found, and chunk exceed the limit" on
                    # pages with no clean separators. Fall through to the
                    # plain-HTTP path below instead of failing the page.
                    logger.warning(
                        "[CrawlerEngine] crawl4ai generation failed for %s (%s) — plain-HTTP fallback",
                        url, exc,
                    )
                    status = None
                    gen_exc = exc

                body = md or ""
                _page_error: Optional[str] = None
                if not body:
                    # crawl4ai failed or produced no markdown for this URL
                    # (generation crash on huge / separator-less / JS-heavy
                    # pages — the historical "Separator is not found, and chunk
                    # exceed the limit" family). Record the failure; the runner
                    # re-fetches failed URLs over plain HTTP with the full
                    # contract (HAR evidence + metadata), so DER still gets
                    # content and the citation pipeline stays fed. The original
                    # exception is preserved for diagnostics.
                    # The original exception message is preserved verbatim as
                    # the page error (contract: page.error == str(exception)).
                    _page_error = (
                        str(gen_exc) if gen_exc is not None
                        else "no usable markdown from crawl4ai"
                    )
                    logger.warning(
                        "[CrawlerEngine] no usable markdown for %s (status=%s): %s",
                        url, status, _page_error,
                    )

                har_entries.append({
                    "url": url, "method": "GET",
                    "status": status,
                    "response_headers": resp_headers,
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "content_length": len(body),
                    "body_sha256": hashlib.sha256(body.encode("utf-8", "replace")).hexdigest(),
                    "error": _page_error,
                })
                # T11 (REQ-5): harvest Set-Cookie into the run-scoped jar,
                # scoped to the response's domain. Best-effort, never raises.
                if self._cookie_jar is not None:
                    self._cookie_jar.record_set_cookie(url, resp_headers)
                metadata = (result.metadata if result is not None else {}) or {}
                title = metadata.get("title", "") or ""
                # T1: the raw HTML byte size is recorded for EVERY page. The
                # replay store (T5) must retain the raw HTML the agent reasoned
                # over, so we measure it even when markdown succeeded (where
                # `html` itself is still discarded to keep payloads small).
                _raw_html = getattr(result, "html", None) or None
                # REQ-4 AC1/AC2: challenge detection on the PRIMARY path.
                # The old detector lived in crawl_runner with a single caller
                # inside the plain-HTTP fallback; the primary Playwright path
                # had ZERO awareness (grep -c "challenge" crawler_engine.py = 0).
                # is_challenge_page now lives in usability.py (REQ-1 shared
                # predicate) and is judged here against the raw HTML — the
                # structural markers (challenge-platform, cf-turnstile, …) are
                # what distinguish a real interstitial from prose containing
                # "just a moment" (REQ-4 edge case).
                _challenged = False
                if isinstance(_raw_html, str) and _raw_html:
                    _challenged = is_challenge_page(_raw_html)
                    if _challenged:
                        # AC3: log URL, status, and the detection signal so
                        # challenge frequency is measurable per domain.
                        logger.warning(
                            "[CrawlerEngine] CHALLENGE url=%s status=%s marker=structural — "
                            "page NOT persisted as content",
                            url, status,
                        )
                        from urllib.parse import urlparse
                        self._challenge_domains.add(urlparse(url).netloc)
                        _page_error = "challenge"
                        # AC2: the challenge interstitial must not reach the
                        # capture store (its boilerplate is not content).
                        _raw_html = None
                        # REQ-18/CT-11: the HAR entry must carry the challenge
                        # marker too — _apply_har_penalties keys on
                        # `"challenge" in entry["error"]` to penalize the
                        # source domain. The entry was appended above with the
                        # pre-detection error; overwrite it.
                        if har_entries:
                            har_entries[-1]["error"] = "challenge"
                elif _page_error and _page_error.startswith("timeout"):
                    # AC4: a timeout on a domain already seen serving
                    # challenges this run is challenge-suspected — reconcile
                    # the two buckets instead of undercounting challenges.
                    from urllib.parse import urlparse
                    if urlparse(url).netloc in self._challenge_domains:
                        _page_error = "challenge_suspected"
                        logger.warning(
                            "[CrawlerEngine] CHALLENGE-SUSPECTED url=%s timeout on "
                            "domain with prior challenge this run",
                            url,
                        )
                pages.append(PageData(
                    url=url,
                    title=title,
                    markdown=md,
                    html=result.html if (result is not None and not md) else None,
                    metadata=metadata,
                    error=_page_error,
                    html_bytes=len(_raw_html) if isinstance(_raw_html, str) else 0,
                ))
                # T5 (REQ-1 AC1/AC2): persist the raw captured HTML keyed by
                # job_id+page_number for the browser panel replay. OFF the hot
                # path: save() is best-effort, never raises, and a storage
                # failure never fails the fetch (REQ-1 AC5).
                if isinstance(_raw_html, str) and _raw_html:
                    try:
                        from .capture_store import get_capture_store

                        get_capture_store().save(
                            job_id=job_id,
                            page_number=page_offset + i + 1,
                            url=url,
                            html=_raw_html,
                        )
                    except Exception:  # noqa: BLE001 — capture write must not fail the crawl
                        pass
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
                    # capture_page is the STORAGE address the bytes were saved
                    # under; i + 1 is this crawl's own page counter. They differ
                    # whenever page_offset is set (per-URL dispatch). Passed as a
                    # trailing kwarg so callbacks that predate it still work.
                    if _cb_takes_capture_page:
                        on_page_done(
                            url, i + 1, total, title, snippet,
                            capture_page=page_offset + i + 1,
                        )
                    else:
                        on_page_done(url, i + 1, total, title, snippet)
                except Exception:
                    pass

            # Polite delay between requests (skip after last URL). T11 (REQ-5):
            # randomised jitter so the crawl is not a metronome (anti-detection,
            # same politeness budget on average).
            if i < total - 1 and delay_ms > 0:
                await asyncio.sleep(_jittered_delay_ms(delay_ms) / 1000.0)

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
