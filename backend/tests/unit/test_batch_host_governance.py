"""T12 (REQ-7 AC1/AC2, REQ-18 AC1): per-host concurrency + 429/503 circuit breaking.

- Global batch concurrency limit: 10 in flight across URLs (existing semaphore,
  not something to layer twice).
- Per-host limit: 2 concurrent fetches against the same netloc — three same-
  domain URLs dispatch with the third waiting; the third is NOT dropped, just
  held.
- Per-host 429 circuit: two 429/503 responses in a row open a breaker for that
  host — remaining same-host URLs mark `status="rate_limited"`, no fetch call,
  and the rest of the batch continues.
- Resume-after-cooldown is left to the caller (orchestrator-level retry);
  the breaker here is a pure run-scoped gate, never process state.

Mock capacity objects: a controller object with a finish() method; asyncio's
Event enough, but we exercise it for real concurrency observability (PROVES
the limiting actually happens in the scheduler, not just per-call).
"""
from __future__ import annotations

import asyncio
import time

import pytest

from backend.crawler.capabilities import CAPABILITIES, FetchOutcome, register_capability
from backend.crawler.crawler_engine import PageData
from backend.crawler.orchestrator import CrawlOrchestrator
from backend.crawler.usability import UsabilityReason, UsabilityVerdict


def _usable_page(url: str) -> PageData:
    return PageData(url=url, title="t", markdown="content", html=None, metadata={}, error=None)


def _outcome(url: str, status: int = 200) -> FetchOutcome:
    verdict = UsabilityVerdict(usable=True, reason=UsabilityReason.OK)
    page = PageData(url=url, title="t", markdown="content", html=None, metadata={})
    return FetchOutcome(
        url=url, capability="fetch.crawl", page=page if status == 200 else None,
        verdict=verdict if status == 200 else UsabilityVerdict(usable=False, reason=UsabilityReason.TRANSPORT_ERROR),
        duration_ms=1, har_entries=[],
    )


class _FakeCrawlCap:
    """Counts concurrent same-host entries; hosts A and B get independent
    concurrency gates only — no shared queue."""

    name = "fetch.crawl"

    def __init__(self):
        self.active_by_host: dict[str, int] = {}
        self.peak_by_host: dict[str, int] = {}
        self.calls: list[str] = []

    async def available(self):
        return True

    async def fetch_one(self, url, goal, job_id, on_progress=None, page_offset=0):
        from urllib.parse import urlparse
        host = (urlparse(url).netloc or url).lower()
        self.calls.append(url)
        self.active_by_host[host] = self.active_by_host.get(host, 0) + 1
        self.peak_by_host[host] = max(self.peak_by_host.get(host, 0), self.active_by_host[host])
        # Simulate work long enough that concurrency is observable.
        await asyncio.sleep(0.05)
        self.active_by_host[host] -= 1
        return _outcome(url)


@pytest.fixture(autouse=True)
def _clean_capabilities():
    CAPABILITIES.clear()
    yield
    CAPABILITIES.clear()


def test_per_host_concurrency_limits_to_2():
    """Three URLs on one host must not run 3-wide — one waits for a slot."""
    cap = _FakeCrawlCap()
    register_capability(cap)
    orch = CrawlOrchestrator()
    orch._backend_override = None

    result = asyncio.run(CrawlOrchestrator().dispatch_urls(
        ["https://limit.example/a", "https://limit.example/b", "https://limit.example/c"],
        query="q", job_id="j-per-host", concurrency_limit=10,
    ))

    assert cap.peak_by_host["limit.example"] == 2, (
        f"peak was {cap.peak_by_host} — the per-host semaphore let 3 run"
    )


def test_different_hosts_run_simultaneously():
    """Two different hosts each run two deep — no cross-host blocking."""
    cap = _FakeCrawlCap()
    register_capability(cap)
    orch = CrawlOrchestrator()

    asyncio.run(orch.dispatch_urls(
        ["https://a.example/one", "https://a.example/two", "https://b.example/one", "https://b.example/two"],
        query="q", job_id="j-two-hosts", concurrency_limit=10,
    ))
    assert cap.peak_by_host['a.example'] == 2
    assert cap.peak_by_host['b.example'] == 2


def test_429_twice_opens_circuit_and_embeds_rate_limited():
    """Second consecutive 429 on a host opens the breaker; later same-host
    URLs never reach the capability (marked rate_limited), but other hosts
    keep running normally."""
    calls: list[str] = []

    class _RateLimitedCap:
        name = "fetch.crawl"

        def __init__(self):
            self.calls: list[str] = []

        async def available(self):
            return True

        async def fetch_one(self, url, goal, job_id, on_progress=None, page_offset=0):
            self.calls.append(url)
            host = url.split("/")[2]
            status = 429 if "429-flood" in url else 200
            return FetchOutcome(
                url=url, capability="fetch.crawl",
                page=PageData(url=url, title="t", markdown="c", html=None, metadata={}) if status == 200 else None,
                verdict=UsabilityVerdict(usable=status == 200, reason=(UsabilityReason.OK if status == 200 else UsabilityReason.TRANSPORT_ERROR)),
                duration_ms=1,
                har_entries=[{"url": url, "status": status, "capability": "fetch.crawl"}],
            )

    cap = _RateLimitedCap()
    register_capability(cap)
    orch = CrawlOrchestrator()
    result = asyncio.run(orch.dispatch_urls(
        [
            # Three items on the same host — host A. First two 429s open the
            # breaker; the third should be skipped without a fetch call.
            "https://429-flood.example/a",
            "https://429-flood.example/b",
            "https://429-flood.example/c",
            # A second host with no breaker — must still be fetched.
            "https://fine.example/x",
        ],
        query="q", job_id="j-circuit", concurrency_limit=10,
    ))

    # First two calls hit the flood, third skipped once the breaker trips,
    # other host still ran.
    assert sum(1 for u in cap.calls if "429-flood" in u) == 2, (
        f"calls: {cap.calls} — expected the first two"
    )
    assert any("fine.example" in u for u in cap.calls), (
        "other host was starved by the 429 breaker"
    )
    # The broken-out URL came back as rate_limited.
    broken = [p for p in result.pages if p.url == "https://429-flood.example/c"]
    assert broken and any(getattr(p, "metadata", {}).get("rate_limited") for p in broken), (
        f"third URL should be marked rate_limited, got {[(p.url, p.metadata) for p in result.pages]}"
    )
    # The broken-out URL has an explicit error label, never silently dropped.
    broken_page = broken[0]
    assert "rate_limited" in getattr(broken_page, "error", "") or "rate_limited" in str(getattr(broken_page, "metadata", {})), (
        f"absent error marking: {broken_page}"
    )
