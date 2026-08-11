"""Contract tests for T14 (REQ-13): park-and-continue wiring.

A wall in a fetch outcome (CAPTCHA/login/paywall from fetch.vision) parks the
source in the shared registry — one question per domain per run (AC6) — and the
run continues with the remaining URLs (AC2). Synthesis lists parked sources
(AC4) instead of blocking. Hermetic: fake capabilities, no live web.
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


def _usable(url):
    return FetchOutcome(
        url=url, capability="fetch.crawl",
        page=PageData(url=url, title="T", markdown="quantum verification content here", html="", metadata={}),
        verdict=UsabilityVerdict(usable=True, reason=UsabilityReason.OK),
        duration_ms=1,
    )


def _walled(url, wall=WallKind.CAPTCHA):
    return FetchOutcome(
        url=url, capability="fetch.vision", page=None,
        verdict=UsabilityVerdict(usable=False, reason=UsabilityReason.CHALLENGE),
        wall=wall, duration_ms=1,
    )


class _FakeCrawl:
    name = "fetch.crawl"

    def __init__(self, factory):
        self._factory = factory
        self.calls = []

    async def available(self):
        return True

    async def fetch_one(self, url, goal, job_id):
        self.calls.append(url)
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


class TestParkAndContinue:
    def test_wall_parks_source_and_continues(self):
        """A walled URL is parked; the run continues with other URLs (AC2)."""
        crawl = _FakeCrawl(lambda u: _walled(u) if "blocked" in u else _usable(u))
        register_capability(crawl)
        orch = _make_orch()
        events = []

        result = asyncio.run(orch.dispatch_urls(
            ["https://captcha.example/blocked", "https://ok.example/a"],
            query="q", job_id="run_1", concurrency_limit=2,
            on_progress=lambda ev: events.append(ev),
        ))
        # continue: the OK URL still fetched
        assert len(result.pages) == 1
        assert result.pages[0].url == "https://ok.example/a"
        # parked: registry has the walled source
        registry = get_parked_source_registry()
        parked = registry.pending("run_1")
        assert len(parked) == 1
        assert parked[0].domain == "captcha.example"
        assert parked[0].wall_kind == "captcha"
        # event emitted for frontend listing (AC4)
        assert any(ev.event == "CRAWLER_SOURCE_PARKED" for ev in events)

    def test_one_question_per_domain_per_run(self):
        """Two walled URLs on the SAME domain -> one parked source (AC6)."""
        crawl = _FakeCrawl(lambda u: _walled(u))
        register_capability(crawl)
        orch = _make_orch()

        asyncio.run(orch.dispatch_urls(
            ["https://paywall.example/a", "https://paywall.example/b"],
            query="q", job_id="run_2", concurrency_limit=2,
        ))
        registry = get_parked_source_registry()
        assert len(registry.pending("run_2")) == 1

    def test_wall_kinds_mapped(self):
        """login/paywall walls also park."""
        for kind, domain in ((WallKind.LOGIN, "login.example"), (WallKind.PAYWALL, "pay.example")):
            CAPABILITIES.clear()
            reset_parked_source_registry_for_testing()
            crawl = _FakeCrawl(lambda u, k=kind: _walled(u, k))
            register_capability(crawl)
            orch = _make_orch()
            asyncio.run(orch.dispatch_urls([f"https://{domain}/x"], query="q", job_id="r", concurrency_limit=2))
            parked = get_parked_source_registry().pending("r")
            assert parked and parked[0].wall_kind == kind.value

    def test_no_wall_no_park(self):
        """A normal unusable outcome (no wall) is NOT parked."""
        crawl = _FakeCrawl(lambda u: FetchOutcome(
            url=u, capability="fetch.crawl", page=None,
            verdict=UsabilityVerdict(usable=False, reason=UsabilityReason.TOO_SHORT),
            duration_ms=1,
        ))
        register_capability(crawl)
        orch = _make_orch()

        asyncio.run(orch.dispatch_urls(["https://empty.example/x"], query="q", job_id="run_3", concurrency_limit=2))
        assert get_parked_source_registry().pending("run_3") == []
