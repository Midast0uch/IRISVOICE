"""BT (vision-goal-directed-search T29 / REQ-2 AC2.3): early schema
termination. When a batch runs with an output_schema, the orchestrator must
evaluate field completeness after EVERY completed page and cancel the
remaining queued/in-flight fetches the moment every required field is
satisfied — a crawl never burns a request proving what it already knows.

This test was RED when written (2026-09-07): the Wave-3 commit landed the
accumulator/query-synthesizer units but nothing in `dispatch_urls` consumed
the schema — batch crawls walked every URL even after the answer was on
page 1. AC2.3 is the fix this file exists to pin.
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from backend.crawler.capabilities import CAPABILITIES, FetchOutcome, register_capability
from backend.crawler.crawler_engine import PageData
from backend.crawler.orchestrator import CrawlOrchestrator
from backend.crawler.usability import UsabilityReason, UsabilityVerdict


class _FieldCap:
    """fetch.crawl carrying per-URL extracted payloads in page.metadata."""

    name = "fetch.crawl"

    def __init__(self, payload_by_url: dict, delay_s: float = 0.05):
        self.payload_by_url = payload_by_url
        self.delay = delay_s
        self.calls: list[str] = []
        self.cancelled: list[str] = []

    async def available(self):
        return True

    async def fetch_one(self, url, goal, job_id):
        self.calls.append(url)
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled.append(url)
            raise
        fields = self.payload_by_url[url]
        return FetchOutcome(
            url=url, capability="fetch.crawl",
            page=PageData(
                url=url, title="t", markdown="content long enough to read",
                html="", metadata=dict(fields),
            ),
            verdict=UsabilityVerdict(usable=True, reason=UsabilityReason.OK),
            duration_ms=int(self.delay * 1000),
        )


def _no_history():
    class _R:
        async def resolve(self, query, quick=False):
            return {"hit": False, "sources": [], "coverage_score": 0.0, "topics": []}

    import backend.crawler.source_registry as sr_mod

    sr_mod.get_source_registry = lambda: _R()


@pytest.fixture(autouse=True)
def _clean():
    CAPABILITIES.clear()
    yield
    CAPABILITIES.clear()


_SCHEMA = {
    "type": "object",
    "properties": {
        "price": {"type": "number"},
        "availability": {"type": "string"},
    },
    "required": ["price", "availability"],
}


def test_early_termination_cancels_remaining_urls_once_schema_is_satisfied():
    """AC2.3: price lands on URL1, availability on URL2 → URLs 3/4 cancelled
    or never started, and the result still carries the two satisfied pages."""
    cap = _FieldCap(
        {
            "https://s.example/1": {"price": 1999},
            "https://s.example/2": {"availability": "in_stock"},
            "https://s.example/3": {"price": 1999},
            "https://s.example/4": {"price": 1999},
        },
        delay_s=0.05,
    )
    register_capability(cap)
    orch = CrawlOrchestrator()
    orch._backend_override = None
    _no_history()

    urls = [f"https://s.example/{i}" for i in (1, 2, 3, 4)]
    result = asyncio.run(
        orch.dispatch_urls(
            urls, query="price and availability", job_id="j-early",
            concurrency_limit=2, max_pages=4,
            output_schema=_SCHEMA,
        )
    )

    # The satisfied pair landed; the remaining URLs were cancelled (preferred
    # for in-flight) or simply never dispatched (queued behind the semaphore).
    never_touched = [u for u in ("https://s.example/3", "https://s.example/4")
                     if u not in cap.calls]
    assert never_touched, (
        f"schema was satisfied after 2 pages but every URL was still fetched: "
        f"calls={cap.calls}"
    )
    got_fields = set()
    for p in result.pages:
        got_fields |= {k for k, v in p.metadata.items() if k in _SCHEMA["required"] and v is not None}
    assert set(_SCHEMA["required"]) <= got_fields


def test_no_early_termination_when_a_required_field_never_appears():
    """AC2.3 boundary: if the schema never satisfies, every URL IS fetched —
    the early-exit gate must not amputate a genuinely incomplete batch."""
    cap = _FieldCap(
        {u: {"price": 1999} for u in (f"https://m.example/{i}" for i in (1, 2, 3))},
        delay_s=0.02,
    )
    register_capability(cap)
    orch = CrawlOrchestrator()
    orch._backend_override = None
    _no_history()

    urls = [f"https://m.example/{i}" for i in (1, 2, 3)]
    result = asyncio.run(
        orch.dispatch_urls(
            urls, query="q", job_id="j-keep", concurrency_limit=2, max_pages=3,
            output_schema=_SCHEMA,  # availability never arrives
        )
    )

    assert sorted(cap.calls) == sorted(urls), (
        f"a missing required field must keep the batch alive; calls={cap.calls}"
    )
    assert len(result.pages) == 3


def test_no_schema_means_no_early_termination_logic():
    """REQ-16 AC7 / change-safety: without output_schema the dispatch is the
    pre-existing pipeline byte-for-byte — no gate, no projection cost."""
    cap = _FieldCap(
        {u: {"x": 1} for u in (f"https://n.example/{i}" for i in (1, 2))},
        delay_s=0.02,
    )
    register_capability(cap)
    orch = CrawlOrchestrator()
    orch._backend_override = None
    _no_history()

    urls = [f"https://n.example/{i}" for i in (1, 2)]
    result = asyncio.run(
        orch.dispatch_urls(urls, query="q", job_id="j-plain", concurrency_limit=2, max_pages=2)
    )
    assert sorted(cap.calls) == sorted(urls)
    assert len(result.pages) == 2
