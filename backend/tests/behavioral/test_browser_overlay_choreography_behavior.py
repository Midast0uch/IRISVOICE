"""BT-1 (vision-goal-directed-search T24, REQ-3): browser overlay
choreography over the REAL event stream — the per-page events the
`loading -> dispersing -> crawling -> complete` machine consumes must arrive
in order, cover every URL's slot exactly once, and all arrive before the
run returns (zero buffer: nothing lands after the result leaves).

The choreography's worst live failure (2026-08-11, "3/1" reset bug) came
from the INNER single-URL run re-emitting lifecycle events; the outer run
now owns lifecycle and only page events, renumbered. This test pins both
halves: ordered per-page coverage AND no inner lifecycle leak.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from backend.crawler.capabilities import CAPABILITIES, FetchOutcome, register_capability
from backend.crawler.crawler_engine import PageData
from backend.crawler.orchestrator import CrawlOrchestrator, CrawlProgress
from backend.crawler.usability import UsabilityReason, UsabilityVerdict


class _PagingCap:
    """fetch.crawl that emits its own per-URL CRAWLER_PAGE_FETCHED (like the
    real capability) so the outer dispatch's numbering filter is exercised."""

    name = "fetch.crawl"

    def __init__(self):
        self.calls: list[str] = []

    async def available(self):
        return True

    async def fetch_one(self, url, goal, job_id, on_progress=None, page_offset=0):
        self.calls.append(url)
        if on_progress is not None:
            on_progress(CrawlProgress("CRAWLER_PAGE_FETCHED", {
                "url": url, "page_number": 1, "total": 1,
                "job_id": job_id, "title": "t",
            }))
        # The real capability would EMIT ITS OWN lifecycle too; we deliberately
        # simulate one URL also forwarding an inner CRAWLER_STARTED/COMPLETE so
        # the outer filter (which strips them, per the 2026-08-11 reset bug)
        # is load-bearing in this test.
        if on_progress is not None and url.endswith("/inner-lifecycle"):
            on_progress(CrawlProgress("CRAWLER_STARTED", {"job_id": job_id, "url_count": 1}))
            on_progress(CrawlProgress("CRAWLER_COMPLETE", {"job_id": job_id, "page_count": 1}))
        return FetchOutcome(
            url=url, capability="fetch.crawl",
            page=PageData(url=url, title="t", markdown="real content long enough", html="", metadata={}),
            verdict=UsabilityVerdict(usable=True, reason=UsabilityReason.OK),
            duration_ms=1,
        )


@pytest.fixture(autouse=True)
def _clean():
    CAPABILITIES.clear()
    yield
    CAPABILITIES.clear()


def _no_history():
    class _R:
        async def resolve(self, query, quick=False):
            return {"hit": False, "sources": [], "coverage_score": 0.0, "topics": []}
    import backend.crawler.source_registry as sr_mod
    sr_mod.get_source_registry = lambda: _R()


def test_choreography_delivers_ordered_page_events_covering_each_slot():
    cap = _PagingCap()
    register_capability(cap)
    orch = CrawlOrchestrator()
    orch._backend_override = None
    _no_history()

    urls = ["https://ch.example/1", "https://ch.example/2", "https://ch.example/3"]
    events: list = []

    t0 = time.monotonic()
    result = asyncio.run(
        orch.dispatch_urls(
            urls, query="q", job_id="j-choreo",
            concurrency_limit=3, max_pages=3,
            on_progress=lambda p: events.append((time.monotonic(), p.event, dict(p.payload))),
        )
    )
    t_end = time.monotonic()

    pages = [e for e in events if e[1] == "CRAWLER_PAGE_FETCHED"]
    assert {p[2]["url"] for p in pages} == set(urls), (
        f"some URL's page event never reached the stream: {pages}"
    )
    # Outer run renumbered the slots: 1..3 distinct, sharing the run total.
    pns = sorted(p[2]["page_number"] for p in pages)
    assert pns == [1, 2, 3], f"page slots not renumbered by the outer run: {pns}"
    assert all(p[2]["total"] == 3 for p in pages)

    # Zero-lag: the last page event INSIDE the run window, not after the
    # result is already in hand. (Structural: callbacks run on dispatch's own
    # event loop; a queue-backed emitter would violate this.)
    assert pages, "no page events at all"
    assert all(t <= t_end for t, _, _ in events), "an event arrived after the run returned"
    assert t_end - t0 < 5.0

    # No inner lifecycle frames reached the outer stream — the overlay's
    # loading/dispersing dance belongs to the outer run alone (the 3/1 bug).
    leak = [e for e in events if e[1] in ("CRAWLER_STARTED", "CRAWLER_COMPLETE")]
    assert leak == [], (
        f"inner lifecycle events leaked through dispatch: {leak}"
    )


def test_inner_lifecycle_never_resets_the_outer_overlay():
    """The pinned 2026-08-11 failure mode: one URL emitting an inner
    STARTED/COMPLETE pair must not reset the outer run's animation."""
    cap = _PagingCap()
    register_capability(cap)
    orch = CrawlOrchestrator()
    orch._backend_override = None
    _no_history()

    events: list = []

    asyncio.run(
        orch.dispatch_urls(
            ["https://ch.example/normal", "https://ch.example/inner-lifecycle"],
            query="q", job_id="j-noreset",
            concurrency_limit=2, max_pages=4,
            on_progress=lambda p: events.append((p.event, dict(p.payload))),
        )
    )

    kinds = [k for k, _ in events]
    assert "CRAWLER_STARTED" not in kinds and "CRAWLER_COMPLETE" not in kinds, (
        f"inner restart events reached the outer stream: {kinds}"
    )
    urls_seen = {p.get("url") for k, p in events if k == "CRAWLER_PAGE_FETCHED"}
    assert urls_seen == {"https://ch.example/normal", "https://ch.example/inner-lifecycle"}
