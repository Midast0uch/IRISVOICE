"""Fetch capabilities — REQ-6.

Capability registry for the fetch layer. Each capability is a named, async
single-URL fetcher that returns a standardized :class:`FetchOutcome`. The
research orchestrator selects between ``fetch.crawl`` (headless markdown
extraction) and ``fetch.vision`` (vision-guided browser session) per URL
(REQ-6 AC3, design D2).

The registry is the integration point the DER node machinery consumes: the
orchestrator's per-URL dispatch (T12) and any DER plan step that needs a
``fetch.*`` node read from :data:`CAPABILITIES` instead of hard-coding a
backend. No agent_kernel edits are required here.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol

from backend.crawler.robots_checker import get_robots_checker
from backend.crawler.usability import UsabilityReason

logger = logging.getLogger(__name__)

# ── Browser-availability latch (session 365) ────────────────────────────────
# Tier-2 (pooled browser) escalation is the RECOVERY path for a Tier-1 challenge
# (401/403/CAPTCHA). When the browser cannot launch at all — Playwright's
# binaries are not installed ("BrowserType.launch: Executable doesn't exist ...
# run `playwright install`") — the escalation can NEVER succeed, yet it was
# retried PER URL, each attempt costing up to the 45 s pool lease. MEASURED: five
# walled URLs = 157 s for a crawl that ends in "all pages failed to fetch"
# anyway. The budget was never the problem; the retry of an impossible action was.
#
# A missing browser is an ENVIRONMENT fact, not a per-URL outcome, so it is
# latched once and the escalation is skipped until the TTL expires. The latch is
# TIME-BOUNDED rather than permanent on purpose: `playwright install` can be run
# while this process lives, and a permanent latch would keep Tier-2 disabled in
# production long after the fix.
_BROWSER_UNAVAILABLE_UNTIL: float = 0.0
_BROWSER_UNAVAILABLE_REASON: str = ""
_BROWSER_LATCH_S = float(
    os.environ.get("IRIS_BROWSER_UNAVAILABLE_LATCH_S", "300")
)
# Substrings that mean "the browser cannot run here", as opposed to "this URL
# failed". Kept narrow so a genuine per-page error never disables Tier-2.
_BROWSER_ENV_FAILURES = (
    "executable doesn't exist",
    "playwright install",
    "browsertype.launch",
)


def _browser_latched() -> bool:
    """True while a known-missing browser should suppress Tier-2 escalation."""
    return time.monotonic() < _BROWSER_UNAVAILABLE_UNTIL


def _latch_browser_unavailable(exc: object) -> bool:
    """Latch the browser as unavailable when *exc* is an environment failure.

    Returns True when this call latched (i.e. the caller should treat Tier-2 as
    unavailable from now on). Never raises.
    """
    global _BROWSER_UNAVAILABLE_UNTIL, _BROWSER_UNAVAILABLE_REASON
    try:
        text = str(exc or "").lower()
        if not any(_s in text for _s in _BROWSER_ENV_FAILURES):
            return False
        _BROWSER_UNAVAILABLE_UNTIL = time.monotonic() + _BROWSER_LATCH_S
        _BROWSER_UNAVAILABLE_REASON = str(exc or "")[:200]
        logger.warning(
            "[capabilities] Tier-2 pooled browser is UNAVAILABLE (%s) — "
            "skipping browser escalation for %.0fs so a doomed launch is not "
            "retried per URL. Run `playwright install` to restore it.",
            _BROWSER_UNAVAILABLE_REASON, _BROWSER_LATCH_S,
        )
        return True
    except Exception:  # noqa: BLE001 — a latch must never raise
        return False


class WallKind(str, Enum):
    """Interstitial walls a vision session can hit (REQ-7)."""

    CAPTCHA = "captcha"
    LOGIN = "login"
    PAYWALL = "paywall"
    UNKNOWN = "unknown"


class FetchCapability(Protocol):
    """A named way to fetch one URL (design.md verbatim interface)."""

    name: str  # "fetch.crawl" | "fetch.vision"

    async def available(self) -> bool: ...

    async def fetch_one(self, url: str, goal: str, job_id: str) -> "FetchOutcome": ...


@dataclass
class FetchOutcome:
    """Outcome of one capability fetch (design.md verbatim interface)."""

    url: str
    capability: str
    page: Optional["PageData"]  # noqa: F821 — imported lazily for typing
    verdict: "UsabilityVerdict"  # noqa: F821
    settled_dom: Optional[str] = None  # vision hands this to crawl (REQ-6 AC5)
    wall: Optional[WallKind] = None  # CAPTCHA | LOGIN | PAYWALL | UNKNOWN
    actions_taken: int = 0
    duration_ms: int = 0
    # Per-request HAR evidence (REQ-13). The hybrid fetch tiers populate this with
    # the REAL request record (status, response headers, body sha256) so
    # dispatch_urls can score actual transport facts instead of a synthesized light
    # entry. Empty when a capability produced none (e.g. vision).
    har_entries: list = field(default_factory=list)


# Identity Tier-1 presents when fetching (REQ-5 AC3: the robots gate below
# checks the SAME identity the fetch would present — checking any other UA
# would be compliance theatre).
#
# A descriptive UA (app name + contact URL) that follows common bot policies — a
# generic browser UA got 403 from Wikipedia (UA policy), a policy UA got 200 in
# 0.54 s (measured 2026-09-30). Used for page fetches AND robots.txt. Override
# with IRIS_CRAWL_USER_AGENT.
_TIER1_USER_AGENT = os.environ.get("IRIS_CRAWL_USER_AGENT") or (
    "IRISVoice/1.0 (+https://github.com/Midast0uch/IRISVOICE; research assistant)"
)

# Tier-2 setup steps (new_context / new_page) had no timeout: a wedged browser
# held the URL until the whole run budget cut it. Bounded well inside the
# per-URL budget; goto has its own 8 s bound below.
_TIER2_STEP_TIMEOUT_S = 5.0


class FetchCrawlCapability:
    """``fetch.crawl`` — hybrid browser-silo fetch (REQ-3 / REQ-4).

    Tier 1 (REQ-3 AC3.2/AC3.3): fast async HTTP retrieval (httpx) + readable-text
    extraction, ~150 ms with 0 MB browser overhead. Handles the large majority of
    static informational pages. When Tier 1 is usable the capture is stored and the
    result returned WITHOUT launching Chromium.

    Tier 2 (REQ-3 AC3.4/AC3.5, REQ-4 AC4.2/AC4.3): on a challenge page, CAPTCHA,
    401/403, or a dynamic client-side SPA with insufficient text, escalate to the
    shared pooled browser via ``backend.vision.browser_pool.acquire_browser()``,
    using an isolated ``browser.new_context()`` per fetch. The pool's idle watchdog
    (IRIS_BROWSER_IDLE_TIMEOUT, 180 s) reclaims Chromium when unused (REQ-4 AC4.4).

    Browser-panel events (CRAWLER_PAGE_FETCHED) and capture paths are preserved so
    the in-app browser panel shows pages arriving exactly as before (REQ-3 AC3.1).
    """

    name = "fetch.crawl"

    async def available(self) -> bool:
        # Headless extraction is always available; no external server needed.
        return True

    async def fetch_one(
        self,
        url: str,
        goal: str,
        job_id: str,
        on_progress=None,
        page_offset: int = 0,
    ) -> FetchOutcome:
        """Hybrid fetch: Tier 1 Fast-HTTP first, escalate to Tier 2 pooled browser.

        ``on_progress`` and ``page_offset`` remain OPTIONAL keywords (the protocol
        call stays 3-positional so capabilities remain interchangeable, REQ-6 AC1).
        ``on_progress`` is load-bearing for the UI: without it CRAWLER_PAGE_FETCHED
        never reaches the browser panel. ``page_offset`` reserves this URL's block
        of the job's capture address space so concurrent single-URL fetches do not
        overwrite each other's captured bytes.
        """
        # REQ-5 AC3 (CT-8): robots gate FIRST — Tier-1's raw httpx fetch must
        # not route around robots compliance. crawler_engine.crawl() gates
        # every URL the same way; the capability path consults the same
        # checker before spending any fetch resource. A refusal returns
        # TRANSPORT_ERROR with engine-identical evidence and is never
        # escalated to Tier 2 (the orchestrator excludes transport_error
        # wholesale — the guard covers all of it, not only robots detail).
        try:
            _robots_allowed = await get_robots_checker().is_allowed(url, _TIER1_USER_AGENT)
        except Exception:  # noqa: BLE001 — checker failure fails OPEN;
            # a broken checker must never break a fetch (the checker itself
            # already fails open for unreachable robots.txt; this covers
            # malformed URLs and checker bugs). fetch_one never raises.
            _robots_allowed = True
        if not _robots_allowed:
            logger.info(
                "[capabilities][job_id=%s] robots.txt refused %s — no fetch "
                "(REQ-5 AC3)", job_id, url,
            )
            return FetchOutcome(
                url=url,
                capability="fetch.crawl",
                page=None,
                verdict=_unusable_verdict(detail="error=blocked by robots.txt"),
                duration_ms=0,
                har_entries=[{
                    "url": url, "method": "GET", "status": "robots_blocked",
                    "response_headers": {}, "duration_ms": 0,
                    "content_length": 0, "body_sha256": "",
                    "error": "blocked by robots.txt",
                    "capability": "fetch.crawl",
                }],
            )
        # ── Tier 1: Fast-HTTP (REQ-3 AC3.2) ───────────────────────────────
        # REQ-15 AC15.1: .pdf URLs route to fetch.pdf BEFORE the HTML path —
        # a browser/HTML parse of binary PDF bytes is never usable.
        if url.lower().split("?")[0].split("#")[0].endswith(".pdf") and (
            "fetch.pdf" in CAPABILITIES
        ):
            return await get_capability("fetch.pdf").fetch_one(
                url, goal, job_id, on_progress=on_progress, page_offset=page_offset,
            )
        outcome = await _fast_http_fetch_one(url, goal, job_id, page_offset, on_progress)
        if outcome.verdict.usable:
            # REQ-3 AC3.3: usable static content — capture stored + page event
            # emitted inside _fast_http_fetch_one; no Chromium was launched.
            return outcome

        # ── Tier 2: pooled-browser escalation (REQ-3 AC3.4) ───────────────
        # A browser that cannot launch is an ENVIRONMENT fact, not a per-URL
        # outcome: escalating again would burn another pool lease for every
        # remaining URL (measured: 45 s x 5 URLs = 157 s) and still fail. Return
        # the Tier-1 verdict so the caller sees the honest "challenge" outcome
        # at once. See _BROWSER_UNAVAILABLE_UNTIL.
        # A bare 401/403 (verdict BLOCKED) is a refusal, not a challenge: a
        # browser meets the same refusal, so the URL goes back to the caller to
        # be parked and recorded — never fought with Chromium.
        if outcome.verdict.reason == UsabilityReason.BLOCKED:
            logger.info(
                "[capabilities][job_id=%s] fetch.crawl Tier-1 blocked (%s) — "
                "browser escalation SKIPPED: %s",
                job_id, outcome.verdict.detail, url,
            )
            return outcome
        if _browser_latched():
            logger.info(
                "[capabilities][job_id=%s] fetch.crawl Tier-1 unusable "
                "(reason=%s) — browser escalation SKIPPED (latched unavailable): %s",
                job_id, outcome.verdict.reason.value, url,
            )
            return outcome
        logger.info(
            "[capabilities][job_id=%s] fetch.crawl Tier-1 unusable (reason=%s) — "
            "escalating to pooled browser: %s",
            job_id, outcome.verdict.reason.value, url,
        )
        # CONFLICT-FLAG (stash pop): stashed side gave fetch_one a 3-arg body
        # delegating to CrawlOrchestrator().fetch_url (no page_offset); kept
        # upstream Tier1/Tier2 hybrid — line 143's _browser_pool_fetch_one
        # needs page_offset, so the stashed body would NameError here.
        return await _browser_pool_fetch_one(url, goal, job_id, page_offset, on_progress)


# ── Hybrid fetch helpers (REQ-3 / REQ-4) ───────────────────────────────────


def _host(url: str) -> str:
    """Best-effort hostname for progress payloads (never raises)."""
    try:
        from urllib.parse import urlparse

        return urlparse(url).netloc or url
    except Exception:  # noqa: BLE001
        return url


def _emit_page_fetched(on_progress, url: str, title: str, job_id: str, capture_page: int) -> None:
    """Emit CRAWLER_PAGE_FETCHED through the capability's on_progress consumer.

    Mirrors the orchestrator's payload shape (orchestrator.py ~:1683) so the
    browser panel builds the same replay URL /api/browser/capture/{job_id}/{page}.
    page_number/total are the single-URL fetch's own counter (1/1); the OUTER run
    renumbers them in dispatch_urls._forward. capture_page is the storage address
    and is NOT renumbered. Never raises — a failing emitter must never break a fetch.
    """
    if on_progress is None:
        return
    try:
        from backend.crawler.orchestrator import CrawlProgress

        payload = {
            "url": url,
            "page_number": 1,
            "total": 1,
            "host": _host(url),
            "title": title,
            "snippet": "",
            "job_id": job_id,
            "capture_page": capture_page,
            "capture_available": True,
        }
        on_progress(CrawlProgress("CRAWLER_PAGE_FETCHED", payload))
    except Exception:  # noqa: BLE001 — never fail a fetch on a progress emit
        pass


def _strip_html_to_text(html: str) -> str:
    """Strip scripts/styles/tags to readable text (shared by both tiers)."""
    import re

    stripped = re.sub(
        r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=re.I
    )
    stripped = re.sub(r"<[^>]+>", " ", stripped)
    return re.sub(r"\s+", " ", stripped).strip()


def _extract_title(html: str, fallback: str) -> str:
    import re

    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    return m.group(1).strip() if m else fallback


class FetchPDFCapability:
    """``fetch.pdf`` — native PDF/technical-document extraction (REQ-15).

    Download + parse with PyMuPDF (``fitz``) directly — no Chromium, ~<1.5 s
    for ≤100 pages. Robots-gated exactly like fetch.crawl (REQ-5 AC3) BEFORE
    any bytes move. fitz is imported lazily inside the methods (its import
    pulls numpy/the fitz chain, which is the +315 MB first-touch commit the
    REQ-23 baseline is currently attributing; it must not load here).
    """

    name = "fetch.pdf"

    async def available(self) -> bool:
        try:
            import fitz  # noqa: F401
        except ImportError:
            return False
        return True

    async def fetch_one(
        self,
        url: str,
        goal: str,
        job_id: str,
        on_progress=None,
        page_offset: int = 0,
    ) -> FetchOutcome:
        try:
            _allowed = await get_robots_checker().is_allowed(url, _TIER1_USER_AGENT)
        except Exception:  # noqa: BLE001 — fail open, as in fetch.crawl
            _allowed = True
        if not _allowed:
            logger.info(
                "[capabilities][job_id=%s] robots.txt refused %s — no download "
                "(REQ-5 AC3)", job_id, url,
            )
            return FetchOutcome(
                url=url, capability=self.name, page=None,
                verdict=_unusable_verdict(detail="error=blocked by robots.txt"),
                duration_ms=0,
                har_entries=[{
                    "url": url, "method": "GET", "status": "robots_blocked",
                    "response_headers": {}, "duration_ms": 0,
                    "content_length": 0, "body_sha256": "",
                    "error": "blocked by robots.txt", "capability": self.name,
                }],
            )

        import hashlib

        import httpx

        from backend.crawler.crawler_engine import PageData
        from backend.crawler.usability import page_is_usable

        t0 = time.monotonic()
        try:
            # Session 365: 60 s -> 8 s. This is the Tier-1 plain-HTTP fetch, the
            # CHEAP path, and at 60 s one slow host could eat the entire run
            # ceiling by itself. A static fetch that cannot answer in 8 s is not
            # going to answer usefully inside a 25 s run.
            async with httpx.AsyncClient(follow_redirects=True, timeout=8.0) as client:
                resp = await client.get(
                    url, headers={"User-Agent": _TIER1_USER_AGENT}
                )
                resp.raise_for_status()
                pdf_bytes = resp.content
            markdown = await asyncio.to_thread(self._extract_text, pdf_bytes)
            page = PageData(
                url=url, title=url.rsplit("/", 1)[-1] or url,
                markdown=markdown, html=None, metadata={"content_type": "application/pdf"},
                error=None, html_bytes=len(pdf_bytes),
            )
            verdict = page_is_usable(page)
            return FetchOutcome(
                url=url, capability=self.name,
                page=page if verdict.usable else None, verdict=verdict,
                duration_ms=int((time.monotonic() - t0) * 1000),
                har_entries=[{
                    "url": url, "method": "GET", "status": resp.status_code,
                    "response_headers": dict(resp.headers),
                    "duration_ms": int((time.monotonic() - t0) * 1000),
                    "content_length": len(pdf_bytes),
                    "body_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
                    "error": None, "capability": self.name,
                }],
            )
        except Exception as exc:  # noqa: BLE001 — capability never raises
            logger.info(
                "[capabilities][job_id=%s] fetch.pdf failed %s: %s", job_id, url, exc
            )
            return FetchOutcome(
                url=url, capability=self.name, page=None,
                verdict=_unusable_verdict(detail=str(exc)[:120]),
                duration_ms=int((time.monotonic() - t0) * 1000),
                har_entries=[],
            )

    @staticmethod
    def _extract_text(pdf_bytes: bytes) -> str:
        """Lazy fitz import + parse — kept off the async caller thread."""
        import fitz

        parts: list[str] = []
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                text = page.get_text("text")
                if text.strip():
                    parts.append(text.strip())
        return "\n\n".join(parts)

    async def render_target_page_png(self, pdf_bytes: bytes, page_index: int) -> Optional[bytes]:
        """REQ-15 AC15.3: render ONLY the requested page (0-based) as PNG for
        the VLM's chart/diagram inspection path. Bytes are bounded (single page
        at 150 DPI ≈ 1–2 MB). Never raises."""
        import fitz

        try:
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                if not (0 <= page_index < len(doc)):
                    return None
                pix = doc[page_index].get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72))
                return pix.tobytes("png")
        except Exception:  # noqa: BLE001
            return None


async def _fast_http_fetch_one(url, goal, job_id, page_offset, on_progress) -> FetchOutcome:
    """Tier 1: async HTTP retrieval (httpx) + readable-text extraction.

    REQ-3 AC3.2. Returns a FetchOutcome carrying REAL per-request HAR evidence
    (status, response headers, body sha256). Never raises — any failure returns
    an unusable verdict so the caller escalates to Tier 2.
    """
    import hashlib

    import httpx

    from backend.crawler.capture_store import get_capture_store
    from backend.crawler.crawler_engine import PageData, _coerce_headers
    from backend.crawler.usability import is_challenge_page, page_is_usable

    t0 = time.monotonic()
    capture_page = page_offset + 1
    try:
        # Session 365: 30 s -> 8 s, same reasoning as the Tier-1 fetch above —
        # one host must never be able to consume the whole run ceiling.
        async with httpx.AsyncClient(follow_redirects=True, timeout=8.0) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": _TIER1_USER_AGENT},
            )
        html = resp.text
        status = resp.status_code
        # REQ-15 AC15.1: content-type routing — a server that answers
        # application/pdf on a non-.pdf URL hands off to fetch.pdf (which
        # downloads and parses the bytes natively; the HTML path that follows
        # would only garble the binary).
        if "application/pdf" in (resp.headers.get("content-type") or "").lower():
            if "fetch.pdf" in CAPABILITIES:
                return await get_capability("fetch.pdf").fetch_one(
                    url, goal, job_id, on_progress=on_progress, page_offset=page_offset,
                )
        text = _strip_html_to_text(html)
        title = _extract_title(html, url)

        # REQ-3 AC3.4 triggers: challenge page / CAPTCHA (markers) -> escalate.
        # A bare 401/403 WITHOUT markers is "blocked": a refusal that Tier 2
        # cannot fix, so it parks instead of escalating (spec A2, D3).
        challenged = is_challenge_page(html)
        blocked = status in (401, 403) and not challenged
        _err = "challenge" if challenged else ("blocked" if blocked else None)
        page = PageData(
            url=url,
            title=title,
            markdown=text,
            html=None,
            metadata={},
            error=_err,
            html_bytes=len(html),
        )
        verdict = page_is_usable(page)
        duration_ms = int((time.monotonic() - t0) * 1000)

        # Real per-request HAR evidence (REQ-13) for dispatch penalty scoring.
        har = {
            "url": url,
            "method": "GET",
            "status": status,
            "response_headers": _coerce_headers(dict(resp.headers)),
            "duration_ms": duration_ms,
            "content_length": len(html),
            "body_sha256": hashlib.sha256(html.encode("utf-8", "replace")).hexdigest(),
            "error": _err,
            "capability": "fetch.crawl",
        }

        if verdict.usable and not (challenged or blocked):
            # REQ-3 AC3.3: persist the capture + emit the page event so the
            # browser panel shows the page arriving — all without Chromium.
            try:
                get_capture_store().save(
                    job_id=job_id, page_number=capture_page, url=url, html=html
                )
            except Exception:  # noqa: BLE001 — capture failure never fails a fetch
                pass
            _emit_page_fetched(on_progress, url, title, job_id, capture_page)
        return FetchOutcome(
            url=url,
            capability="fetch.crawl",
            page=page if verdict.usable else None,
            verdict=verdict,
            duration_ms=duration_ms,
            har_entries=[har],
        )
    except Exception as exc:  # noqa: BLE001 — Tier-1 failure escalates to Tier 2
        logger.info(
            "[capabilities][job_id=%s] Tier-1 fast-http failed %s: %s", job_id, url, exc
        )
        return FetchOutcome(
            url=url,
            capability="fetch.crawl",
            page=None,
            verdict=_unusable_verdict(),
            duration_ms=int((time.monotonic() - t0) * 1000),
            har_entries=[],
        )


async def _browser_pool_fetch_one(url, goal, job_id, page_offset, on_progress) -> FetchOutcome:
    """Tier 2: pooled-browser fetch via backend.vision.browser_pool.

    REQ-3 AC3.5 / REQ-4 AC4.2/AC4.3. Uses ``acquire_browser()`` + an isolated
    ``browser.new_context()`` so cookies/storage/sessions stay isolated per fetch.

    Extraction is CONTENT-AWARE, not a naive tag-strip: it reads the RENDERED
    visible text (``innerText``), preferring the semantic main-content container
    (``<article>`` / ``<main>``) over the whole body so nav/footer/boilerplate is
    excluded. ``innerText`` reflects the JS-settled DOM and skips hidden elements
    — the whole reason this tier escalates to a browser for SPAs/dynamic pages.
    The ``goal`` is logged as the extraction target; downstream rerank scores the
    extracted content against it.

    The pool's idle watchdog (IRIS_BROWSER_IDLE_TIMEOUT, 180 s) reclaims Chromium
    when unused (REQ-4 AC4.4). Returns a FetchOutcome carrying REAL per-request
    HAR evidence; never raises.
    """
    import hashlib

    from backend.crawler.capture_store import get_capture_store
    from backend.crawler.crawler_engine import PageData
    from backend.crawler.usability import page_is_usable

    t_start = time.monotonic()
    capture_page = page_offset + 1
    lease = None
    context = None
    status = None
    try:
        from backend.vision.browser_pool import acquire_browser

        browser, lease = await acquire_browser(max_lease_ms=45_000.0)
        # REQ-4 AC4.3: isolated context per fetch (cookies/storage/session).
        context = await asyncio.wait_for(
            browser.new_context(), timeout=_TIER2_STEP_TIMEOUT_S
        )
        pg = await asyncio.wait_for(context.new_page(), timeout=_TIER2_STEP_TIMEOUT_S)
        logger.info(
            "[capabilities][job_id=%s] Tier-2 browser fetch (goal=%r): %s",
            job_id, (goal or "")[:60], url,
        )
        # Session 365 — PER-PAGE bounds must fit inside the run ceiling
        # (IRIS_WEBSEARCH_MAX_WALL_MS, 25 s). These were goto=30 s and
        # networkidle=10 s, i.e. a SINGLE page could consume 40 s — more than
        # the whole run budget — so the outer bound always won and the crawl
        # died with an unnamed TimeoutError instead of an honest per-page limit.
        # The owner's requirement is a web step that finishes well inside 30 s,
        # so one page is bounded here at ~8 s of navigation.
        response = await pg.goto(url, wait_until="domcontentloaded", timeout=8_000)
        status = response.status if response is not None else None
        # Best-effort wait for client-side rendering to settle; some SPAs never
        # reach networkidle, so a timeout here is non-fatal. Bounded small: this
        # is a SETTLE allowance, not a load budget.
        try:
            await pg.wait_for_load_state("networkidle", timeout=2_000)
        except Exception:  # noqa: BLE001
            pass
        html = await pg.content()
        title = await pg.title() or _extract_title(html, url)

        # Content-aware extraction: read the RENDERED visible text, preferring the
        # semantic main-content container (<article>/<main>) over the whole body so
        # nav/footer/boilerplate is excluded. innerText reflects the JS-settled DOM
        # and skips hidden elements — the reason this tier exists.
        try:
            text = await pg.evaluate(
                "() => {"
                " const root = document.querySelector('article')"
                " || document.querySelector('main')"
                " || document.body;"
                " return root ? root.innerText : '';"
                "}"
            )
        except Exception:  # noqa: BLE001 — fall back to stripping raw HTML
            text = ""
        if not (text or "").strip():
            text = _strip_html_to_text(html)
        text = (text or "").strip()

        page_data = PageData(
            url=url,
            title=title,
            markdown=text,
            html=None,
            metadata={},
            error=None,
            html_bytes=len(html),
        )
        verdict = page_is_usable(page_data)
        duration_ms = int((time.monotonic() - t_start) * 1000)

        # Real per-request HAR evidence (REQ-13) for dispatch penalty scoring.
        har = {
            "url": url,
            "method": "GET",
            "status": status,
            "response_headers": {},
            "duration_ms": duration_ms,
            "content_length": len(html),
            "body_sha256": hashlib.sha256(html.encode("utf-8", "replace")).hexdigest(),
            "error": None,
            "capability": "fetch.crawl",
        }

        if verdict.usable:
            try:
                get_capture_store().save(
                    job_id=job_id, page_number=capture_page, url=url, html=html
                )
            except Exception:  # noqa: BLE001
                pass
            _emit_page_fetched(on_progress, url, title, job_id, capture_page)

        return FetchOutcome(
            url=url,
            capability="fetch.crawl",
            page=page_data if verdict.usable else None,
            verdict=verdict,
            duration_ms=duration_ms,
            har_entries=[har],
        )
    except Exception as exc:  # noqa: BLE001 — capability must never raise
        # A launch/environment failure disables Tier-2 for the latch window, so
        # the next URL does not pay another pool lease to fail identically.
        _latch_browser_unavailable(exc)
        logger.warning(
            "[capabilities][job_id=%s] Tier-2 browser-pool fetch failed %s: %s",
            job_id, url, exc,
        )
        return FetchOutcome(
            url=url,
            capability="fetch.crawl",
            page=None,
            verdict=_unusable_verdict(),
            duration_ms=int((time.monotonic() - t_start) * 1000),
            har_entries=[],
        )
    finally:
        # REQ-4 AC4.3: ALWAYS close the isolated context + release the lease on
        # every exit path (normal + exception) so the pool is never leaked.
        if context is not None:
            try:
                await context.close()
            except Exception:  # noqa: BLE001
                pass
        if lease is not None:
            try:
                lease.release()
            except Exception:  # noqa: BLE001
                pass


# Registry (REQ-6 AC3: dispatch reads CAPABILITIES, never hard-coded backends).
# REQ-2 AC4 (specs/dag-node-execution-model, T11): the registry is a FACADE
# over the unified tool registry — every capability registered here ALSO
# declares its NodeSpec (artifact types + advertised recovery) in
# backend.agent.tool_registry, so the parallel node-registry mechanism is
# retired: node metadata has ONE home, and the planner sees fetch.crawl /
# fetch.vision exactly like any other node (REQ-2 AC3). The dict below
# remains as the EXECUTION binding (capability object -> fetch_one), not as
# a second place to declare routing behavior.
CAPABILITIES: dict[str, FetchCapability] = {}


def register_capability(cap: FetchCapability) -> None:
    """Register a fetch capability (execution) + its node metadata (REQ-2 AC4).

    Execution binding lives in :data:`CAPABILITIES`; node metadata (produces/
    emits/recovers) is declared ONCE in the unified registry via NodeSpec, so
    the router can match failure reasons to this capability's advertised
    recovery (REQ-4 AC1) and the planner can compose it (REQ-3 AC1).
    """
    CAPABILITIES[cap.name] = cap
    _declare_node_metadata(cap)


def _declare_node_metadata(cap: FetchCapability) -> None:
    """Declare the capability's NodeSpec in the unified registry (REQ-2 AC4).

    Advertisements encode the recovery decisions the websearch spec previously
    hand-wrote as branches (T13 deletes those branches; the advertisement is
    their replacement):
      * fetch.vision  recovers CHALLENGE / EMPTY / TOO_SHORT  — the fresh-
        failure escalation set (never TRANSPORT_ERROR: robots/DNS must not be
        routed around — REQ-5 AC3 / REQ-8 AC3, pinned by BT-12).
      * search_discovery recovers NO_CANDIDATES — the planner-gave-nothing
        pivot (REQ-19), replacing the hand-written discovery trigger.
      * fetch.crawl emits the UsabilityReason-derived set and recovers nothing.
    """
    from backend.agent.nodes.outcome import Reason
    from backend.agent.nodes.spec import NodeSpec
    from backend.agent.tool_registry import (
        ToolSpec,
        get_node_spec,
        register_node,
        register_tool,
        resolve_tool,
    )

    if get_node_spec(cap.name) is not None:
        return  # already declared (idempotent facade)

    _produces = "pages" if cap.name.startswith("fetch.") else "text"
    _emits = frozenset({
        Reason.EMPTY, Reason.TOO_SHORT, Reason.CHALLENGE, Reason.TRANSPORT_ERROR,
    })
    _recovers: frozenset = frozenset()
    if cap.name == "fetch.vision":
        # CHALLENGE IS DELIBERATELY NOT HERE ANY MORE.
        #
        # Advertising it made fetch.vision a challenge-recovery node, which meant
        # it only ever ran on URLs the crawl had already failed — in practice,
        # Cloudflare-walled pages. A headless browser fails those too. Measured
        # live 2026-08-11 (job 40e4e523…): three escalations, 240s + 188s + 243s,
        # ALL THREE returning status=challenge. A 0/3 success rate for roughly
        # four minutes of a seven-minute turn, while the one source that did
        # yield content came from the ordinary crawl.
        #
        # The inversion that caused: vision spent all its time on the job it is
        # worst at and none on the job it exists for — being the live reading
        # surface on pages we CAN reach, scrolling the iframe so the user watches
        # the search happen. A walled page now parks immediately (REQ-13 AC2
        # already handles that path) and the run moves to the next Exa URL, which
        # is cheap because the planner returns more candidates than it dispatches.
        #
        # EMPTY / TOO_SHORT are RETAINED: those are pages the crawl reached but
        # could not extract from — reachable, and exactly where a reading pass
        # adds content instead of fighting a wall. transport_error stays absent:
        # robots.txt refusal and DNS must never be routed around (REQ-5 AC3 /
        # REQ-8 AC3), which is unchanged.
        _recovers = frozenset({Reason.EMPTY, Reason.TOO_SHORT})
    elif cap.name == "search_discovery":
        _recovers = frozenset({Reason.NO_CANDIDATES})
    try:
        if resolve_tool(cap.name) is None:
            register_tool(ToolSpec(
                name=cap.name,
                description=f"{cap.name} fetch capability (REQ-2 AC4)",
                parameters={},
                category="web",
                permission_tier="read_only",
                executor="crawler",
                # fetch.vision is the crawl's internal recovery session, not a
                # tool the LLM can call: the bridge has no executor for it and
                # it once leaked into the tool-model grammar. The agent-facing
                # way to drive a page is browser_open / browser_observe /
                # browser_act. The node router still consults the spec.
                hidden=(cap.name == "fetch.vision"),
            ))
        register_node(NodeSpec(
            tool=resolve_tool(cap.name),
            produces=_produces,
            emits_reasons=_emits,
            recovers_reasons=_recovers,
        ))
    except Exception as _decl_exc:  # noqa: BLE001 — declaration must never break registration
        logger.warning("[capabilities] node metadata declaration for %s failed: %s", cap.name, _decl_exc)


def get_capability(name: str) -> FetchCapability:
    """Look up a capability by name. Raises KeyError for unknown names."""
    try:
        return CAPABILITIES[name]
    except KeyError:
        raise KeyError(f"unknown fetch capability: {name!r}") from None


def register_default_capabilities() -> dict[str, FetchCapability]:
    """Register fetch.crawl always; fetch.vision best-effort (REQ-6 AC3).

    A missing/import-broken vision stack must never break fetch.crawl, so the
    vision capability is registered inside try/except.
    """
    if "fetch.crawl" not in CAPABILITIES:
        register_capability(FetchCrawlCapability())
    if "fetch.vision" not in CAPABILITIES:
        try:
            from backend.vision.fetch_vision import FetchVisionCapability

            register_capability(FetchVisionCapability())
        except Exception as exc:  # noqa: BLE001 — optional capability
            logger.warning("[capabilities] fetch.vision unavailable: %s", exc)
    if "fetch.pdf" not in CAPABILITIES:
        try:
            register_capability(FetchPDFCapability())
        except Exception as exc:  # noqa: BLE001 — optional capability
            logger.warning("[capabilities] fetch.pdf unavailable: %s", exc)
    _register_search_discovery_node()
    _register_crawler_query_composite()
    return CAPABILITIES


def _register_crawler_query_composite() -> None:
    """Declare crawler_query as the reference composite (REQ-3 AC5 / T12).

    ``crawler_query`` stays a SINGLE callable unit — one outer outcome, so the
    existing UI card and callers are unchanged (REQ-3 AC4, design D5) — while
    its sub-graph (fetch.crawl / fetch.vision / search_discovery) is declared
    as ``composite_of`` so the planner can see and re-route at sub-node
    boundaries (REQ-3 AC2/AC3). Idempotent.
    """
    from backend.agent.nodes.outcome import Reason  # noqa: F401 — frozenset members
    from backend.agent.nodes.spec import NodeSpec
    from backend.agent.tool_registry import (
        ToolSpec,
        get_node_spec,
        register_node,
        register_tool,
        resolve_tool,
    )

    if get_node_spec("crawler_query") is not None:
        return
    try:
        if resolve_tool("crawler_query") is None:
            register_tool(ToolSpec(
                name="crawler_query",
                description=(
                    "Deep web research crawl — the reference composite "
                    "(REQ-3 AC5): plans URLs, fetches via fetch.crawl / "
                    "fetch.vision with advertisement-driven recovery, and "
                    "returns a structured summary + extracted content."
                ),
                parameters={"query": {"type": "string", "description": "The research topic"}},
                category="web",
                permission_tier="read_only",
                executor="crawler",
                requires_internet=True,
            ))
        register_node(NodeSpec(
            tool=resolve_tool("crawler_query"),
            produces="pages",
            emits_reasons=frozenset({
                Reason.NO_CANDIDATES,
                Reason.CHALLENGE,
                Reason.EMPTY,
                Reason.TOO_SHORT,
                Reason.TRANSPORT_ERROR,
                Reason.BUDGET_EXCEEDED,
            }),
            recovers_reasons=frozenset(),
            composite_of=("fetch.crawl", "fetch.vision", "search_discovery"),
        ))
    except Exception as _cq_exc:  # noqa: BLE001 — declaration must never break import
        logger.warning("[capabilities] crawler_query composite declaration failed: %s", _cq_exc)


def _register_search_discovery_node() -> None:
    """Declare the vision search-discovery node (REQ-19 / T13).

    ``search_discovery`` is a module function (backend/vision/search_discovery
    ``discover_urls_via_vision``), not a FetchCapability — it does not live in
    CAPABILITIES. It is registered as a node advertising NO_CANDIDATES recovery
    so the orchestrator's zero-URL pivot consults the router instead of a
    hand-written discovery branch (design D4: no branch in the failing node's
    module). Idempotent.
    """
    from backend.agent.nodes.outcome import Reason
    from backend.agent.nodes.spec import NodeSpec
    from backend.agent.tool_registry import (
        ToolSpec,
        get_node_spec,
        register_node,
        register_tool,
        resolve_tool,
    )

    if get_node_spec("search_discovery") is not None:
        return
    try:
        if resolve_tool("search_discovery") is None:
            register_tool(ToolSpec(
                name="search_discovery",
                description=(
                    "Drive a search engine in a vision browser session and "
                    "harvest candidate result URLs (REQ-19 discovery)"
                ),
                parameters={},
                category="web",
                permission_tier="read_only",
                executor="crawler",
                # Session-326: internal recovery node — the node router
                # consults it, but the LLM must never see it: the bridge
                # cannot execute it (was: "Unknown tool: search_discovery").
                hidden=True,
            ))
        register_node(NodeSpec(
            tool=resolve_tool("search_discovery"),
            produces="urls",
            emits_reasons=frozenset(),
            recovers_reasons=frozenset({Reason.NO_CANDIDATES}),
        ))
    except Exception as _sd_exc:  # noqa: BLE001 — declaration must never break import
        logger.warning("[capabilities] search_discovery node declaration failed: %s", _sd_exc)


def _unusable_verdict(detail: str = ""):
    from backend.crawler.usability import UsabilityReason, UsabilityVerdict

    return UsabilityVerdict(usable=False, reason=UsabilityReason.TRANSPORT_ERROR, detail=detail)


# module-level convenience (REQ-6 AC3): importing the crawler package registers
# the default capabilities so orchestrator dispatch works out of the box.
try:
    register_default_capabilities()
except Exception:  # noqa: BLE001 — import-time registration must never break import
    logger.exception("[capabilities] default registration failed")
