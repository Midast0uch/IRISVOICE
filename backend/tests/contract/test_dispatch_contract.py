"""Contract tests for T12 (REQ-10): concurrent per-URL dispatch + conditional
racing gated on source_registry failure history, with loser cancellation.

Hermetic: fake capabilities replace the registry; no live web, no vision server.
"""

import asyncio

import pytest

from backend.crawler.capabilities import (
    CAPABILITIES,
    FetchOutcome,
    FetchCrawlCapability,
    register_capability,
)
from backend.crawler.crawler_engine import PageData
from backend.crawler.orchestrator import CrawlOrchestrator
from backend.crawler.usability import UsabilityReason, UsabilityVerdict


def _page(url="https://a.example/"):
    return PageData(
        url=url, title="T", markdown="quantum verification content here is real", html="", metadata={},
    )


def _usable(url):
    return FetchOutcome(
        url=url, capability="fetch.crawl", page=_page(url),
        verdict=UsabilityVerdict(usable=True, reason=UsabilityReason.OK),
        duration_ms=1,
    )


class _FakeCrawlCap:
    """fetch.crawl fake with configurable latency + outcome."""

    name = "fetch.crawl"

    def __init__(self, outcome_factory=_usable, delay=0.0):
        self._outcome_factory = outcome_factory
        self._delay = delay
        self.calls = []

    async def available(self):
        return True

    async def fetch_one(self, url, goal, job_id):
        self.calls.append((url, job_id))
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._outcome_factory(url)


class _FakeVisionCap:
    """fetch.vision fake; raced only when the domain has failure history."""

    name = "fetch.vision"

    def __init__(self, outcome_factory=_usable, delay=0.0):
        self._outcome_factory = outcome_factory
        self._delay = delay
        self.calls = []
        self.cancelled = False

    async def available(self):
        return True

    async def fetch_one(self, url, goal, job_id):
        self.calls.append((url, job_id))
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return self._outcome_factory(url)


@pytest.fixture(autouse=True)
def _clean_registry():
    CAPABILITIES.clear()
    yield
    CAPABILITIES.clear()


class _NoHistoryRegistry:
    """resolve() returns no sources -> no failure history."""

    async def resolve(self, query, quick=False):
        return {"hit": False, "sources": [], "coverage_score": 0.0, "topics": []}


class _HistoryRegistry:
    """resolve() returns a source with last_error -> failure history."""

    async def resolve(self, query, quick=False):
        return {
            "hit": True,
            "sources": [{"url": "https://a.example/", "domain": "a.example", "last_error": "challenge"}],
            "coverage_score": 1.0,
            "topics": ["q"],
        }


def _make_orch(registry):
    orch = CrawlOrchestrator()
    orch._backend_override = None  # force the dispatch path
    import types

    import backend.crawler.source_registry as sr_mod

    async def _fake_resolve(query, quick=False):
        return await registry.resolve(query, quick=quick)

    # SimpleNamespace (not a class) avoids descriptor binding: attribute access
    # returns the plain function, so resolve(query=..., quick=...) maps cleanly.
    sr_mod.get_source_registry = lambda: types.SimpleNamespace(resolve=_fake_resolve)
    return orch


# ── AC1: concurrent dispatch, bounded by concurrency_limit ─────────────────

def test_distinct_urls_fetched_concurrently():
    """All URLs are fetched (AC1); none dropped."""
    crawl = _FakeCrawlCap()
    register_capability(crawl)
    orch = _make_orch(_NoHistoryRegistry())

    result = asyncio.run(orch.dispatch_urls(
        ["https://a.example/", "https://b.example/", "https://c.example/"],
        query="q", job_id="j1", concurrency_limit=3,
    ))
    assert {u for u, _ in crawl.calls} == {
        "https://a.example/", "https://b.example/", "https://c.example/",
    }
    assert len(result.pages) == 3


def test_concurrency_limit_respected():
    """Semaphore bounds concurrent fetch.crawl calls (AC1)."""
    max_in_flight = 0
    current = 0

    class _CountingCap:
        name = "fetch.crawl"

        async def available(self):
            return True

        async def fetch_one(self, url, goal, job_id):
            nonlocal max_in_flight, current
            current += 1
            max_in_flight = max(max_in_flight, current)
            await asyncio.sleep(0.02)
            current -= 1
            return _usable(url)

    register_capability(_CountingCap())
    orch = _make_orch(_NoHistoryRegistry())
    asyncio.run(orch.dispatch_urls(
        ["https://a.example/", "https://b.example/", "https://c.example/", "https://d.example/"],
        query="q", job_id="j2", concurrency_limit=2,
    ))
    assert max_in_flight <= 2


# ── AC4: NO racing without failure history ─────────────────────────────────

def test_no_race_without_failure_history():
    """fetch.vision is NEVER called on a clean domain (AC4)."""
    crawl = _FakeCrawlCap()
    vision = _FakeVisionCap()
    register_capability(crawl)
    register_capability(vision)
    orch = _make_orch(_NoHistoryRegistry())

    asyncio.run(orch.dispatch_urls(
        ["https://a.example/"], query="q", job_id="j3", concurrency_limit=2,
    ))
    assert len(crawl.calls) == 1
    assert vision.calls == []  # no failure history -> never raced


# ── AC3: racing on failure history ─────────────────────────────────────────

def test_race_when_domain_has_failure_history():
    """Both capabilities run on a failed domain; first usable wins (AC3)."""
    crawl = _FakeCrawlCap(delay=0.05)
    vision = _FakeVisionCap(delay=0.01)  # vision faster
    register_capability(crawl)
    register_capability(vision)
    orch = _make_orch(_HistoryRegistry())

    result = asyncio.run(orch.dispatch_urls(
        ["https://a.example/"], query="q", job_id="j4", concurrency_limit=2,
    ))
    assert len(crawl.calls) == 1
    assert len(vision.calls) == 1
    assert result.pages[0].url == "https://a.example/"


# ── AC5: loser cancellation ────────────────────────────────────────────────

def test_loser_cancelled_after_first_usable():
    """The slower raced capability is cancelled once the winner lands (AC5)."""
    crawl = _FakeCrawlCap(delay=0.01)  # crawl wins
    vision = _FakeVisionCap(delay=0.30)  # vision loses (would exceed budget)
    register_capability(crawl)
    register_capability(vision)
    orch = _make_orch(_HistoryRegistry())

    t0 = asyncio.get_event_loop().time() if False else None
    import time

    start = time.monotonic()
    result = asyncio.run(orch.dispatch_urls(
        ["https://a.example/"], query="q", job_id="j5", concurrency_limit=2,
    ))
    elapsed = time.monotonic() - start
    assert elapsed < 0.25, f"loser not cancelled; took {elapsed:.2f}s"
    assert vision.cancelled is True
    assert result.pages[0].url == "https://a.example/"


# ── Edge: both usable -> crawl preferred ───────────────────────────────────

def test_both_usable_prefers_crawl():
    """Both raced outcomes usable -> crawl (cheaper) wins, race logged (edge)."""
    crawl = _FakeCrawlCap(delay=0.02)
    vision = _FakeVisionCap(delay=0.01)
    register_capability(crawl)
    register_capability(vision)
    orch = _make_orch(_HistoryRegistry())

    result = asyncio.run(orch.dispatch_urls(
        ["https://a.example/"], query="q", job_id="j6", concurrency_limit=2,
    ))
    assert result.pages[0].url == "https://a.example/"


# ── Degraded: failure history but no vision registered ─────────────────────

def test_history_without_vision_uses_crawl_only():
    """Failure history + vision unavailable -> fetch.crawl alone, no crash."""
    crawl = _FakeCrawlCap()
    register_capability(crawl)  # fetch.vision NOT registered
    orch = _make_orch(_HistoryRegistry())

    result = asyncio.run(orch.dispatch_urls(
        ["https://a.example/"], query="q", job_id="j7", concurrency_limit=2,
    ))
    assert len(crawl.calls) == 1
    assert result.pages[0].url == "https://a.example/"


# ── Unusable outcome recorded, not fatal ───────────────────────────────────

def test_unusable_outcome_does_not_raise():
    """A fetch that returns an unusable page is logged, run continues."""
    def _bad(url):
        return FetchOutcome(
            url=url, capability="fetch.crawl", page=None,
            verdict=UsabilityVerdict(usable=False, reason=UsabilityReason.TOO_SHORT),
            duration_ms=1,
        )

    crawl = _FakeCrawlCap(outcome_factory=_bad)
    register_capability(crawl)
    orch = _make_orch(_NoHistoryRegistry())

    result = asyncio.run(orch.dispatch_urls(
        ["https://a.example/"], query="q", job_id="j8", concurrency_limit=2,
    ))
    assert result.pages == []
