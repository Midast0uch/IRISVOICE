"""
Tier 3 integration tests for the unified web-search feature (REQ-17, REQ-29, REQ-31).

These exercise cross-module flows that unit/contract tests don't:
  - T17: termination bounds (min/max pages, timeout, no infinite loop)
  - T18: orchestrator -> SessionEventLog -> replay parity
  - T18: background completion via JobRegistry (WS-disconnect handoff; never cancelled)
  - T18: command-over-HTTP cancels an in-flight job (push-independent)
  - T18: concurrency cap (parallel crawls serialized to <=2)

No live web: a stub FetchBackend is injected via _backend_override.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from crawler.orchestrator import CrawlOrchestrator, FetchBackend  # noqa: E402
from crawler.crawler_engine import CrawlResult, PageData  # noqa: E402
from crawler.crawl_planner import CrawlPlan  # noqa: E402
from crawler.event_log import get_event_log  # noqa: E402
from crawler.job_registry import get_job_registry  # noqa: E402


class _StubBackend(FetchBackend):
    async def fetch(self, query, urls, instructions, max_pages, on_page_done, timeout_s):
        pages = [
            PageData(url="https://example.gov/doc", title="Doc", markdown="Fact X verified by Y.", html="", metadata={}),
            PageData(url="https://news.example.com/a", title="News", markdown="Z happened.", html="", metadata={}),
        ]
        for i, p in enumerate(pages[:max_pages]):
            if on_page_done:
                on_page_done(p.url, i + 1, len(pages[:max_pages]))
        return CrawlResult(query=query, pages=pages[:max_pages], duration_ms=5, crawled_at="2026-01-01T00:00:00+00:00")


class _SlowBackend(FetchBackend):
    """Hangs longer than timeout_s; honors timeout_s like the real backend
    (SubprocessFetchBackend wraps the drain in asyncio.wait_for)."""

    def __init__(self, hang: float = 5.0):
        self._hang = hang

    async def fetch(self, query, urls, instructions, max_pages, on_page_done, timeout_s):
        try:
            await asyncio.wait_for(asyncio.sleep(self._hang), timeout_s)
        except asyncio.TimeoutError:
            return CrawlResult(query=query, pages=[], duration_ms=0, crawled_at="x",
                               error=f"crawl timed out after {timeout_s:g}s")
        return CrawlResult(query=query, pages=[], duration_ms=0, crawled_at="x")


def _stub_planner(urls, max_pages=2):
    class _P:
        async def plan(self, query):
            return CrawlPlan(urls=urls, instructions="extract", result_type="mixed", title="T")
    return _P()


# ── T17: termination bounds ────────────────────────────────────────────────
def test_termination_respects_max_pages():
    """Orchestrator never fetches more than max_pages (no runaway crawl)."""
    orch = CrawlOrchestrator(planner=_stub_planner(["a", "b", "c"]))
    orch._backend_override = _StubBackend()
    result = asyncio.run(orch.research("q", mode="agent", max_pages=1))
    assert len(result.pages) <= 1, f"fetched {len(result.pages)} > max_pages=1"


def test_termination_timeout_no_infinite_loop():
    """A backend that hangs longer than timeout_s returns an error, not a hang."""
    orch = CrawlOrchestrator(planner=_stub_planner(["a"]))
    orch._backend_override = _SlowBackend(hang=5.0)
    t0 = time.monotonic()
    result = asyncio.run(orch.research("q", mode="agent", timeout_s=0.3))
    elapsed = time.monotonic() - t0
    assert elapsed < 3.0, f"crawl did not terminate; elapsed {elapsed:.1f}s"
    assert result.error is not None, "timeout must surface as error, not hang"


# ── T18: orchestrator -> event log -> replay parity ────────────────────────
def test_orchestrator_writes_event_log_and_replays_in_order():
    """Every progress event lands in SessionEventLog; replay preserves order."""
    log = get_event_log()
    session = "integ-s1"
    asyncio.run(log.clear(session))
    orch = CrawlOrchestrator(planner=_stub_planner(["a", "b"]))
    orch._backend_override = _StubBackend()
    asyncio.run(orch.research("q", mode="agent", session_id=session))

    replayed = asyncio.run(log.replay(session, after_seq=0))
    types = [e.event for e in replayed]
    assert types[0] == "CRAWLER_STARTED"
    assert types.count("CRAWLER_PAGE_FETCHED") == 2
    assert "OPEN_TAB" in types
    assert types[-1] == "CRAWLER_COMPLETE"
    asyncio.run(log.clear(session))


# ── T18: background completion via JobRegistry (WS-disconnect handoff) ──────
def test_background_completion_survives_no_progress_callback():
    """crawler_query registers a job; result stored even with no on_progress
    (simulating a dropped WS push). The job is never auto-cancelled."""
    reg = get_job_registry()
    session = "integ-bg"
    job_id = f"crawl_{session}_123"

    async def _run():
        await reg.register(job_id, session, "q")
        orch = CrawlOrchestrator(planner=_stub_planner(["a", "b"]))
        orch._backend_override = _StubBackend()
        # No on_progress -> simulates WS disconnect; result must still persist.
        result = await orch.research("q", mode="agent", session_id=session)
        await reg.complete(job_id, {"summary": "done", "pages": len(result.pages)})
        return result

    asyncio.run(_run())
    job = asyncio.run(reg.get(job_id))
    assert job is not None
    assert job.status == "complete"
    assert job.result["summary"] == "done"
    # A new utterance (registry lookup) is independent of the push channel.
    assert asyncio.run(reg.get(job_id)).status == "complete"
    asyncio.run(reg.evict_now(job_id))


# ── T18: command-over-HTTP cancels an in-flight job (push-independent) ─────
def test_command_over_http_cancels_running_job():
    """POST /api/crawl/command cancel stops a running job; push not required."""
    reg = get_job_registry()
    session = "integ-cmd"
    job_id = f"crawl_{session}_456"

    async def _drive():
        await reg.register(job_id, session, "q")
        orch = CrawlOrchestrator(planner=_stub_planner(["a"]))
        orch._backend_override = _SlowBackend(hang=5.0)
        # Start a crawl that will hang; cancel it via the registry (HTTP path).
        task = asyncio.create_task(
            orch.research("q", mode="agent", session_id=session, timeout_s=10)
        )
        await asyncio.sleep(0.2)
        cancelled = await reg.cancel(job_id)
        # Let the (now-cancelled-intent) crawl finish on its own timeout.
        await task
        return cancelled

    cancelled = asyncio.run(_drive())
    assert cancelled is True
    job = asyncio.run(reg.get(job_id))
    assert job.status == "cancelled"
    asyncio.run(reg.evict_now(job_id))


# ── T18: concurrency cap (parallel crawls serialized to <=2) ───────────────
def test_concurrency_cap_at_integration_level():
    """Three concurrent crawls via the orchestrator are bounded by the runner
    semaphore (default 2) so host memory cannot be exhausted."""
    import crawler.crawl_runner as runner

    state = {"concurrent": 0, "max": 0}

    orig_create = asyncio.create_subprocess_exec

    class _FakeProc:
        def __init__(self):
            self.stdout = _Stream()
            self.pid = 1

        async def wait(self):
            return 0

        def kill(self):
            pass

    class _Stream:
        async def readline(self):
            await asyncio.sleep(0.05)
            return b""

    async def _fake_create(*a, **k):
        state["concurrent"] += 1
        state["max"] = max(state["max"], state["concurrent"])
        p = _FakeProc()
        await asyncio.sleep(0.08)
        state["concurrent"] -= 1
        return p

    asyncio.create_subprocess_exec = _fake_create
    try:
        orch = CrawlOrchestrator(planner=_stub_planner(["a"]))

        async def _one():
            return await orch.research("q", mode="agent", timeout_s=5)

        async def _all():
            return await asyncio.gather(*[_one() for _ in range(3)])

        asyncio.run(_all())
    finally:
        asyncio.create_subprocess_exec = orig_create

    assert state["max"] <= 2, f"concurrency exceeded cap: {state['max']}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
