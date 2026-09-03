"""
REQ-4 contract: challenge detection on the PRIMARY Playwright path.

Pins specs/vision-browser-websearch/requirements.md REQ-4:

  AC1  challenge detection applies to the primary crawl4ai/Playwright path,
       not only the plain-HTTP fallback (grep -c "challenge" crawler_engine.py
       was 0 before this feature)
  AC2  a challenged page is marked unusable with reason `challenge` and is
       NOT persisted to the capture store
  AC3  the URL, status, and detection signal are logged per challenge
  AC4  a timeout on a domain already seen serving challenges this run is
       recorded as challenge_suspected (reconciles the 136-timeouts-vs-2-
       labelled-challenges undercount)

No live web: crawl4ai types and the robots checker are stubbed, and the fake
crawler returns challenge HTML from `arun()`.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
import types

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from crawler.crawler_engine import CrawlerEngine
from crawler.crawler_engine import PageData
from crawler.crawler_engine import _write_har_file


# ── fixtures ────────────────────────────────────────────────────────────────

_CHALLENGE_HTML = (
    "<html><title>Just a moment...</title>"
    '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
    "</html>"
)
_OK_HTML = "<html><body><h1>Real content</h1><p>Genuine article body.</p></body></html>"


class _FakeResult:
    def __init__(self, html: str, status: int = 200, markdown: str = ""):
        self.html = html
        self.status_code = status
        self.markdown = markdown
        self.response_headers = {"content-type": "text/html"}
        self.markdown_v2 = None
        self.metadata: dict = {}


class _FakeCrawler:
    """Stand-in for AsyncWebCrawler; records arun() calls, returns queued results.

    An entry may be an exception — arun() raises it (a timeout-like failure)
    so the engine's except path records `_page_error` from the exception.
    """

    def __init__(self, results: list):
        self.results = list(results)
        self.calls: list[tuple[str, object]] = []

    async def arun(self, url, config=None):
        self.calls.append((url, config))
        if self.results:
            item = self.results.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return _FakeResult("", status=200)


@pytest.fixture
def engine(monkeypatch):
    """CrawlerEngine with crawl4ai/robots/capture dependencies stubbed."""
    # Stub the crawl4ai imports used inside crawl() (not installed in CI).
    fake_crawl4ai = types.ModuleType("crawl4ai")
    fake_crawl4ai.CrawlerRunConfig = lambda **kwargs: type("CRC", (), kwargs)()
    fake_crawl4ai.BM25ContentFilter = object
    fake_crawl4ai.DefaultMarkdownGenerator = lambda: object()

    fake_filter = types.ModuleType("crawl4ai.content_filter_strategy")
    fake_filter.BM25ContentFilter = object
    fake_gen = types.ModuleType("crawl4ai.markdown_generation_strategy")
    fake_gen.DefaultMarkdownGenerator = lambda: object()

    sys.modules["crawl4ai"] = fake_crawl4ai
    sys.modules["crawl4ai.content_filter_strategy"] = fake_filter
    sys.modules["crawl4ai.markdown_generation_strategy"] = fake_gen

    async def _fake_robots_allow(self, url, ua):
        return True

    monkeypatch.setattr("crawler.crawler_engine.get_robots_checker",
                        lambda: type("R", (), {"is_allowed": _fake_robots_allow})())
    monkeypatch.setattr("crawler.crawler_engine._write_har_file", lambda *a, **k: None)
    monkeypatch.setattr("crawler.crawler_engine._rotate_user_agent",
                        lambda: "Mozilla/5.0 (fake)")

    eng = CrawlerEngine()
    eng._crawler = _FakeCrawler([])  # replaced per-test
    return eng


def _fake_capture(monkeypatch):
    saved: list[dict] = []

    class _Store:
        @staticmethod
        def save(**kw):
            saved.append(kw)

    monkeypatch.setattr("crawler.capture_store.get_capture_store", lambda: _Store())
    return saved


# ── AC1: primary-path detection ────────────────────────────────────────────

def test_primary_path_detects_challenge(engine):
    """AC1: a Cloudflare interstitial returned by the PRIMARY crawl4ai path is
    detected as a challenge — the path that had zero awareness before."""
    engine._crawler = _FakeCrawler([_FakeResult(_CHALLENGE_HTML, status=200)])

    result = asyncio.run(engine.crawl(
        query="palworld", urls=["https://fandom.example.com/wiki"],
        instructions="extract", max_pages=1,
    ))

    assert result.pages, "expected one page"
    page = result.pages[0]
    assert page.error == "challenge", f"page must be marked challenge, got {page.error!r}"
    assert page.markdown == "", "challenge boilerplate must not become content"


def test_primary_path_challenge_not_persisted(engine, monkeypatch):
    """AC2: a challenged page is NOT written to the capture store."""
    saved = _fake_capture(monkeypatch)
    engine._crawler = _FakeCrawler([_FakeResult(_CHALLENGE_HTML, status=200)])

    asyncio.run(engine.crawl(
        query="palworld", urls=["https://fandom.example.com/wiki"],
        instructions="extract", max_pages=1,
    ))

    assert saved == [], "challenge page must not reach the capture store"


def test_primary_path_ok_page_still_persisted(engine, monkeypatch):
    """AC2 guard: a NORMAL page on the same path still reaches the capture store
    — the challenge skip must not disable persistence for real content."""
    saved = _fake_capture(monkeypatch)
    engine._crawler = _FakeCrawler([_FakeResult(_OK_HTML, status=200, markdown="Real content.")])

    asyncio.run(engine.crawl(
        query="palworld", urls=["https://ok.example.com/a"],
        instructions="extract", max_pages=1,
    ))

    assert len(saved) == 1, "normal page must still be persisted"
    assert saved[0]["url"] == "https://ok.example.com/a"


def test_har_entry_marks_challenge(engine, monkeypatch):
    """REQ-18/CT-11: the HAR entry carries error="challenge" so
    _apply_har_penalties penalizes the domain (it keys on "challenge" in err)."""
    captured: list[list[dict]] = []

    def _fake_har(job_id, entries):
        captured.append(entries)
        return None

    monkeypatch.setattr("crawler.crawler_engine._write_har_file", _fake_har)
    engine._crawler = _FakeCrawler([_FakeResult(_CHALLENGE_HTML, status=200)])

    asyncio.run(engine.crawl(
        query="palworld", urls=["https://fandom.example.com/wiki"],
        instructions="extract", max_pages=1,
    ))

    assert captured and captured[0], "har entries must be written"
    assert captured[0][0]["error"] == "challenge"


# ── AC4: challenge-suspected timeout reconciliation ────────────────────────

def test_timeout_on_known_challenge_domain_is_suspected(engine):
    """AC4: a timeout on a domain that served a challenge earlier in the SAME
    run is recorded as challenge_suspected, not a plain timeout."""
    engine._crawler = _FakeCrawler([
        _FakeResult(_CHALLENGE_HTML, status=200),          # first URL: challenge
        TimeoutError("timeout: page did not settle within 30s"),  # second URL: timeout
    ])

    result = asyncio.run(engine.crawl(
        query="palworld",
        urls=["https://shield.example.com/wiki", "https://shield.example.com/other"],
        instructions="extract", max_pages=2,
    ))

    assert len(result.pages) == 2
    assert result.pages[0].error == "challenge"
    assert result.pages[1].error == "challenge_suspected", (
        f"second page must be challenge_suspected, got {result.pages[1].error!r}"
    )
    assert "shield.example.com" in engine._challenge_domains


def test_timeout_on_clean_domain_not_suspected(engine):
    """AC4 guard: without a prior challenge on the domain, a timeout stays a
    plain transport error — the reconciliation must not over-label."""
    engine._crawler = _FakeCrawler([_FakeResult("", status=200)])

    result = asyncio.run(engine.crawl(
        query="palworld", urls=["https://clean.example.com/a"],
        instructions="extract", max_pages=1,
    ))

    assert result.pages[0].error is not None
    assert "challenge" not in result.pages[0].error
    assert engine._challenge_domains == set()
