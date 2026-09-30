"""Contract tests for spec A3 (websearch-vision-browser, REQ-2 AC2.4, RC2): quorum return.

``dispatch_urls`` used to ``gather`` every URL, so one dead URL held the whole crawl
(measured 2026-09-30: 3 pages in ~6 s, then ~30 s more waiting for two URLs that could
not succeed). Now, when ``min_pages`` usable pages are in, the rest get a short grace,
are CANCELLED, and are reported as ``cancelled_enough`` - never parked, never a wall.

Hermetic: stub capability, no live web.
"""
from __future__ import annotations

import asyncio
import time
import types

import pytest

from backend.crawler import orchestrator as orch_mod
from backend.crawler.capabilities import CAPABILITIES, FetchOutcome, register_capability
from backend.crawler.crawler_engine import PageData
from backend.crawler.orchestrator import CrawlOrchestrator
from backend.crawler.usability import UsabilityReason, UsabilityVerdict

_FAST = [f"https://fast{i}.example/" for i in range(3)]
_DEAD = [f"https://dead{i}.example/" for i in range(2)]


class _StubCrawlCap:
    """3 URLs answer at once; the `dead*` URLs never finish."""

    name = "fetch.crawl"

    def __init__(self, slow_s: float = 0.0):
        self.cancelled: list[str] = []
        self._slow_s = slow_s

    async def available(self):
        return True

    async def fetch_one(self, url, goal, job_id):
        if "dead" in url:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                self.cancelled.append(url)
                raise
        if "slow" in url:
            await asyncio.sleep(self._slow_s)
        return FetchOutcome(
            url=url, capability="fetch.crawl",
            page=PageData(url=url, title="T", markdown="quantum verification content here is real",
                          html="", metadata={}),
            verdict=UsabilityVerdict(usable=True, reason=UsabilityReason.OK),
            duration_ms=1,
        )


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    CAPABILITIES.clear()
    import backend.crawler.source_registry as sr_mod

    async def _resolve(query, quick=False):
        return {"hit": False, "sources": [], "coverage_score": 0.0, "topics": []}

    monkeypatch.setattr(sr_mod, "get_source_registry",
                        lambda: types.SimpleNamespace(resolve=_resolve))
    from backend.agent.tool_errors import reset_wall_ledger_for_testing
    reset_wall_ledger_for_testing()
    yield
    CAPABILITIES.clear()
    reset_wall_ledger_for_testing()


def _orch():
    orch = CrawlOrchestrator()
    orch._backend_override = None  # force the dispatch path
    return orch


def test_quorum_returns_at_min_pages_plus_grace_and_cancels_the_rest():
    cap = _StubCrawlCap()
    register_capability(cap)
    orch = _orch()

    t0 = time.monotonic()
    result = asyncio.run(orch.dispatch_urls(
        _FAST + _DEAD, query="q", job_id="j-quorum", concurrency_limit=5, min_pages=3,
    ))
    elapsed = time.monotonic() - t0

    assert elapsed < orch_mod._QUORUM_GRACE_S + 1.0, f"waited for dead URLs ({elapsed:.1f}s)"
    assert len(result.pages) == 3
    assert {p.url for p in result.pages} == set(_FAST)
    assert sorted(result.cancelled_enough) == sorted(_DEAD)
    assert sorted(cap.cancelled) == sorted(_DEAD), "the dead fetches were not actually cancelled"
    # cancelled is not parked, not a wall, not dead
    assert not orch._parks_by_job.get("j-quorum"), orch._parks_by_job
    from backend.agent.tool_errors import is_walled
    assert not any(is_walled(u.split("//")[1].strip("/")) for u in _DEAD)
    assert not (set(result.dead_urls) & set(_DEAD))


def test_below_quorum_waits_for_every_url():
    """2 usable + 1 slow-but-finishing URL with min_pages=3: nothing is cut early."""
    register_capability(_StubCrawlCap(slow_s=0.6))
    orch = _orch()

    result = asyncio.run(orch.dispatch_urls(
        _FAST[:2] + ["https://slow.example/"], query="q", job_id="j-below",
        concurrency_limit=5, min_pages=3,
    ))

    assert len(result.pages) == 3
    assert result.cancelled_enough == []


def test_min_pages_is_read_from_the_caller():
    """``min_pages`` was accepted upstream and never read: a lower quorum cuts earlier."""
    register_capability(_StubCrawlCap())
    orch = _orch()

    result = asyncio.run(orch.dispatch_urls(
        _FAST[:2] + _DEAD, query="q", job_id="j-min2", concurrency_limit=5, min_pages=2,
    ))

    assert len(result.pages) == 2
    assert sorted(result.cancelled_enough) == sorted(_DEAD)
