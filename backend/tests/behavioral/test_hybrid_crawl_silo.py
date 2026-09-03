"""Behavioral test: hybrid fetch.crawl — Tier-1 Fast-HTTP, Tier-2 browser_pool (REQ-3).

Drives the real ``FetchCrawlCapability.fetch_one`` with mocked transport:

  1. A static URL is served by Tier-1 async HTTP (httpx) with NO browser lease —
     the ~150 ms / 0 MB browser-overhead path (REQ-3 AC3.2/AC3.3).
  2. A challenge page escalates to Tier-2 ``browser_pool.acquire_browser()`` with
     an isolated context (REQ-3 AC3.4/AC3.5, REQ-4 AC4.2/AC4.3).

Never hits live web — the fetch engine is mocked.
"""

from __future__ import annotations

import asyncio

from backend.crawler.capabilities import FetchCrawlCapability


class _FakeResponse:
    def __init__(self, html, status=200, headers=None):
        self.text = html
        self.status_code = status
        self.headers = headers or {}


class _FakeAsyncClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        return self._response


STATIC_HTML = (
    "<html><head><title>Example</title></head><body>"
    "<article><p>This is a real static article with enough content to be "
    "usable by the page_is_usable predicate.</p></article></body></html>"
)

CHALLENGE_HTML = (
    "<html><head><title>Just a moment...</title></head><body>"
    "<div class='cf-chl-'>Checking your browser before accessing the site.</div>"
    "</body></html>"
)

RENDERED_HTML = (
    "<html><body><article>Rendered SPA content that is long enough to be "
    "usable by the page_is_usable predicate.</article></body></html>"
)


def test_static_url_uses_tier1_no_browser(monkeypatch):
    import httpx

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(_FakeResponse(STATIC_HTML))
    )
    browser_calls = {"n": 0}

    def _fail(*a, **kw):
        browser_calls["n"] += 1
        raise AssertionError("browser_pool must not be used for a static page")

    monkeypatch.setattr("backend.vision.browser_pool.acquire_browser", _fail)

    cap = FetchCrawlCapability()
    outcome = asyncio.run(cap.fetch_one("https://example.com", "goal", "job1"))

    assert outcome.verdict.usable, "static page must be usable via Tier-1"
    assert outcome.page is not None
    assert outcome.har_entries, "Tier-1 must attach real HAR evidence"
    assert browser_calls["n"] == 0, "no browser lease for a static page"


def test_challenge_page_escalates_to_browser_pool(monkeypatch):
    import httpx

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(_FakeResponse(CHALLENGE_HTML))
    )
    acquired = {"n": 0}

    class _FakePage:
        async def goto(self, url, **kw):
            return None

        async def wait_for_load_state(self, *a, **kw):
            return None

        async def content(self):
            return RENDERED_HTML

        async def title(self):
            return "Rendered"

        async def evaluate(self, js):
            return "Rendered SPA content that is long enough to be usable by the page_is_usable predicate."

    class _FakeContext:
        async def new_page(self):
            return _FakePage()

        async def close(self):
            return None

    class _FakeBrowser:
        async def new_context(self):
            return _FakeContext()

    class _FakeLease:
        def release(self):
            return None

    async def _acquire(max_lease_ms=0.0):
        acquired["n"] += 1
        return _FakeBrowser(), _FakeLease()

    monkeypatch.setattr("backend.vision.browser_pool.acquire_browser", _acquire)

    cap = FetchCrawlCapability()
    outcome = asyncio.run(cap.fetch_one("https://challenge.example.com", "goal", "job1"))

    assert acquired["n"] == 1, "challenge page must escalate to browser_pool"
    assert outcome.verdict.usable, "rendered SPA content must be usable"
    assert outcome.page is not None
    assert outcome.har_entries, "Tier-2 must attach real HAR evidence"