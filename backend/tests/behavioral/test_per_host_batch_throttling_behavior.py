"""BT-per-host (vision-goal-directed-search T29, REQ-7): batch dispatch must
NEVER let >2 requests fly at the same host, and a host that answers 429/503
twice in a row stops receiving traffic for the rest of the run.

Both behaviors run against the real `CrawlOrchestrator.dispatch_urls` with
fake capabilities — no network.
"""
from __future__ import annotations

import asyncio
import threading
import time

from backend.crawler.capabilities import CAPABILITIES, FetchOutcome, register_capability
from backend.crawler.crawler_engine import PageData
from backend.crawler.orchestrator import CrawlOrchestrator
from backend.crawler.usability import UsabilityReason, UsabilityVerdict


class _SpyCap:
    """fetch.crawl that tracks its in-flight count per host and sleeps
    briefly so concurrent dispatch actually overlaps."""

    name = "fetch.crawl"

    def __init__(self, delay_s: float = 0.05):
        self.delay = delay_s
        self.calls: list[str] = []
        self._inflight: dict[str, int] = {}
        self._max_inflight: dict[str, int] = {}
        self._lock = threading.Lock()

    async def available(self):
        return True

    def _host(self, url: str) -> str:
        from urllib.parse import urlparse

        return urlparse(url).netloc.lower()

    async def fetch_one(self, url, goal, job_id):
        h = self._host(url)
        with self._lock:
            self.calls.append(url)
            cur = self._inflight.get(h, 0) + 1
            self._inflight[h] = cur
            self._max_inflight[h] = max(self._max_inflight.get(h, 0), cur)
        await asyncio.sleep(self.delay)
        with self._lock:
            self._inflight[h] -= 1
        return FetchOutcome(
            url=url, capability="fetch.crawl",
            page=PageData(url=url, title="t", markdown="real content long enough", html="", metadata={}),
            verdict=UsabilityVerdict(usable=True, reason=UsabilityReason.OK),
            duration_ms=int(self.delay * 1000),
        )

    def max_inflight(self, host: str) -> int:
        return self._max_inflight.get(host, 0)


def _no_history():
    class _R:
        async def resolve(self, query, quick=False):
            return {"hit": False, "sources": [], "coverage_score": 0.0, "topics": []}

    import backend.crawler.source_registry as sr_mod

    sr_mod.get_source_registry = lambda: _R()


import pytest


@pytest.fixture(autouse=True)
def _clean():
    CAPABILITIES.clear()
    yield
    CAPABILITIES.clear()


def test_per_host_concurrency_is_bounded_to_two():
    """AC7.1: with a GLOBAL limit allowing 5, 4 same-host URLs still never
    exceed 2 in flight against that host; a second host runs in parallel
    with the first in the same batch."""
    cap = _SpyCap(delay_s=0.08)
    register_capability(cap)
    orch = CrawlOrchestrator()
    orch._backend_override = None
    _no_history()

    urls = [
        "https://a.example/1",
        "https://a.example/2",
        "https://a.example/3",
        "https://a.example/4",
        "https://b.example/1",
        "https://b.example/2",
    ]
    result = asyncio.run(
        orch.dispatch_urls(
            urls, query="q", job_id="j-host", concurrency_limit=5,
            # Default max_pages is 5 (CRAWL4AI_MAX_PAGES) — the batch here is
            # 6, so pass the larger cap explicitly or the 6th URL is truncated
            # before dispatch by design.
            max_pages=len(urls),
        )
    )

    assert len(result.pages) == 6, f"pages dropped: {len(result.pages)}"
    assert cap.max_inflight("a.example") <= 2, (
        f"host a.example saw {cap.max_inflight('a.example')} concurrent "
        f"requests — the per-host 2-semaphore did not hold"
    )
    assert cap.max_inflight("b.example") <= 2


class _RateLimitingCap(_SpyCap):
    """429s for the target host; normal usable outcome everywhere else."""

    LIMITED_HOST = "rl.example"

    async def fetch_one(self, url, goal, job_id):
        self.calls.append(url)
        if self._host(url) != self.LIMITED_HOST:
            return FetchOutcome(
                url=url, capability="fetch.crawl",
                page=PageData(url=url, title="t", markdown="healthy content long enough", html="", metadata={}),
                verdict=UsabilityVerdict(usable=True, reason=UsabilityReason.OK),
                duration_ms=1,
            )
        return FetchOutcome(
            url=url, capability="fetch.crawl",
            page=PageData(url=url, title="", markdown="", html=None, metadata={}),
            verdict=UsabilityVerdict(usable=False, reason=UsabilityReason.TRANSPORT_ERROR,
                                     detail="http 429"),
            duration_ms=1,
            har_entries=[{"url": url, "status": 429}],
        )


def test_host_circuit_opens_after_two_consecutive_429s():
    """AC7.2: after 2 consecutive 429/503 from one host, remaining URLs for
    THAT host are marked rate_limited WITHOUT being fetched; other hosts are
    unaffected."""
    cap = _RateLimitingCap(delay_s=0.0)
    register_capability(cap)
    orch = CrawlOrchestrator()
    orch._backend_override = None
    _no_history()

    urls = [
        "https://rl.example/1",
        "https://rl.example/2",
        "https://rl.example/3",  # breaker should be open by now
        "https://rl.example/4",
        "https://ok.example/1",
    ]
    t0 = time.monotonic()
    result = asyncio.run(
        orch.dispatch_urls(urls, query="q", job_id="j-circuit", concurrency_limit=2)
    )
    _ = time.monotonic() - t0

    rl_calls = [c for c in cap.calls if c.startswith("https://rl.example/")]
    assert rl_calls == ["https://rl.example/1", "https://rl.example/2"], (
        f"circuit should stop fetching after 2 consecutive 429s; attempted: {rl_calls}"
    )
    by_url = {p.url: p for p in result.pages}
    # The remaining same-host URLs sit in the result as rate_limited rows —
    # visible, never silently dropped (REQ-15: an unread source is reported).
    for u in ("https://rl.example/3", "https://rl.example/4"):
        page = by_url.get(u)
        assert page is not None, f"{u} vanished from the result entirely"
        assert page.metadata.get("rate_limited") is True and page.metadata.get("host"), (
            f"{u} should be a rate_limited row, got metadata={page.metadata}"
        )
    # The healthy host fetched normally.
    assert "https://ok.example/1" in by_url
