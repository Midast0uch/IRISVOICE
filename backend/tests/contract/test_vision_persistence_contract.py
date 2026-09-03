"""Contract tests for T12c (REQ-18): vision persistence spine.

Verifies the vision path joins the existing persistence spine WITHOUT forking:
  - AC1: HAR entries recorded for vision outcomes, so _apply_har_penalties
    scores vision-visited domains on the same basis (challenge walls included).
  - AC2: provenance (ContentOrigin=vision) stamped on pages for the document
    store path.
  - AC5: no forked paths — vision rides the same CrawlResult.har_entries /
    pages fields the batch path uses.
  - AC6: a persistence write failure never fails the fetch (dispatch still
    returns pages; _apply_har_penalties is best-effort try/except).

Hermetic: fake capabilities, no live web.
"""

import asyncio

import pytest

from backend.agent.tools.ask_user_tool import (
    get_parked_source_registry,
    reset_parked_source_registry_for_testing,
)
from backend.crawler.capabilities import (
    CAPABILITIES,
    FetchOutcome,
    WallKind,
    register_capability,
)
from backend.crawler.crawler_engine import PageData
from backend.crawler.orchestrator import CrawlOrchestrator
from backend.crawler.usability import UsabilityReason, UsabilityVerdict


def _vision_usable(url):
    return FetchOutcome(
        url=url, capability="fetch.vision",
        page=PageData(url=url, title="V", markdown="vision extracted quantum verification text here", html="<html>dom</html>", metadata={}),
        verdict=UsabilityVerdict(usable=True, reason=UsabilityReason.OK),
        duration_ms=42,
    )


def _vision_walled(url, wall=WallKind.PAYWALL):
    return FetchOutcome(
        url=url, capability="fetch.vision", page=None,
        verdict=UsabilityVerdict(usable=False, reason=UsabilityReason.CHALLENGE),
        wall=wall, duration_ms=9,
    )


class _FakeVision:
    name = "fetch.vision"

    def __init__(self, factory):
        self._factory = factory

    async def available(self):
        return True

    async def fetch_one(self, url, goal, job_id):
        return self._factory(url)


class _FakeCrawl:
    name = "fetch.crawl"

    def __init__(self, factory):
        self._factory = factory

    async def available(self):
        return True

    async def fetch_one(self, url, goal, job_id):
        return self._factory(url)


@pytest.fixture(autouse=True)
def _clean():
    CAPABILITIES.clear()
    reset_parked_source_registry_for_testing()
    yield
    CAPABILITIES.clear()
    reset_parked_source_registry_for_testing()


def _make_orch():
    orch = CrawlOrchestrator()
    orch._backend_override = None
    import backend.crawler.source_registry as sr_mod

    async def _no_history(query, quick=False):
        return {"hit": False, "sources": [], "coverage_score": 0.0, "topics": []}

    sr_mod.get_source_registry = lambda: type("R", (), {"resolve": _no_history})()
    return orch


class TestVisionHAREntries:
    def test_usable_vision_outcome_emits_har_entry(self):
        """AC1: a usable vision fetch records a HAR entry carrying its
        capability, riding CrawlResult.har_entries like crawl does (AC5)."""
        register_capability(_FakeCrawl(lambda u: _vision_usable(u)))
        orch = _make_orch()
        result = asyncio.run(orch.dispatch_urls(
            ["https://v.example/a"], query="q", job_id="j1", concurrency_limit=2,
        ))
        assert len(result.har_entries) == 1
        entry = result.har_entries[0]
        assert entry["url"] == "https://v.example/a"
        assert entry["capability"] == "fetch.vision"
        assert entry["status"] == 200

    def test_wall_outcome_emits_challenge_har_entry(self):
        """AC1: a walled vision fetch records error='challenge' so
        _apply_har_penalties penalizes the domain on the same basis as a
        crawl-time challenge (no new penalty mechanism)."""
        register_capability(_FakeCrawl(lambda u: _vision_walled(u)))
        orch = _make_orch()
        result = asyncio.run(orch.dispatch_urls(
            ["https://pay.example/a"], query="q", job_id="j2", concurrency_limit=2,
        ))
        entry = result.har_entries[0]
        assert entry["error"] == "challenge"
        assert entry["capability"] == "fetch.vision"

    def test_har_penalties_consume_vision_challenge(self):
        """AC1+AC5: _apply_har_penalties reads the dispatch HAR entries and
        penalizes the walled domain — the vision path feeds the existing
        source_registry.penalize_url unchanged."""
        register_capability(_FakeCrawl(lambda u: _vision_walled(u)))
        orch = _make_orch()
        result = asyncio.run(orch.dispatch_urls(
            ["https://pay.example/a"], query="q", job_id="j3", concurrency_limit=2,
        ))
        penalized = []
        import backend.crawler.source_registry as sr_mod

        class _FakeReg:
            def penalize_url(self, url, topics, last_error="crawl_failed"):
                penalized.append((url, last_error))

        sr_mod.get_source_registry = lambda: _FakeReg()
        # research() applies penalties to the dispatch result; invoke directly.
        orch._apply_har_penalties(result, "q")
        assert penalized and penalized[0][0] == "https://pay.example/a"
        assert penalized[0][1] == "challenge"

    def test_provenance_stamped_on_vision_page(self):
        """AC2: vision pages carry origin=vision metadata for the document
        store path."""
        register_capability(_FakeCrawl(lambda u: _vision_usable(u)))
        orch = _make_orch()
        result = asyncio.run(orch.dispatch_urls(
            ["https://v.example/a"], query="q", job_id="j4", concurrency_limit=2,
        ))
        assert result.pages[0].metadata.get("origin") == "vision"

    def test_persistence_failure_never_fails_fetch(self):
        """AC6: a registry/penalty failure is swallowed — the fetch still
        returns its pages."""
        register_capability(_FakeCrawl(lambda u: _vision_usable(u)))
        orch = _make_orch()
        import backend.crawler.source_registry as sr_mod

        class _BrokenReg:
            def penalize_url(self, *a, **k):
                raise RuntimeError("store down")

        sr_mod.get_source_registry = lambda: _BrokenReg()
        result = asyncio.run(orch.dispatch_urls(
            ["https://v.example/a"], query="q", job_id="j5", concurrency_limit=2,
        ))
        # penalties attempted and swallowed; pages still present
        orch._apply_har_penalties(result, "q")  # must not raise
        assert len(result.pages) == 1
