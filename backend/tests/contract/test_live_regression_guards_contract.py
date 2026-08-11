"""Guards for three defects found in the 2026-08-11 09:18 live run.

All three passed every existing test before they were fixed, because nothing
asserted the behaviour at all. That is this codebase's dominant failure mode, so
each fix gets a test that would have caught it:

  1. Per-URL dispatch leaked the INNER single-URL run's lifecycle events to the
     UI. `fetch_url` emits its own CRAWLER_STARTED with url_count=1, so every
     escalated URL restarted the outer run in the panel: pagesDone reset to 0,
     pagesTotal became 1 (rendering as "3/1"), the overlay dropped back to
     `loading` — which killed the shutter animation and wiped the cursor.
  2. `provider.suggest_action` ran ON the event loop. It is synchronous and
     reaches a readiness loop that sleeps up to 30s, so it froze the entire
     backend when the vision server was cold.
  3. A live BrowserSession could lose its pool lease mid-run and have the shared
     browser closed under it ("Target page, context or browser has been closed"
     immediately after "shared browser stopped").
"""
from __future__ import annotations

import ast
import asyncio
import time
from pathlib import Path

from backend.crawler.crawl_planner import CrawlPlan
from backend.crawler.crawler_engine import CrawlResult, PageData
from backend.crawler.orchestrator import CrawlOrchestrator

_REPO = Path(__file__).resolve().parents[3]


def _page(url: str, markdown: str) -> PageData:
    return PageData(
        url=url, title="t", markdown=markdown, html="<html></html>",
        metadata={}, error=None, html_bytes=len(markdown),
    )


# ══════════════════════════════════════════════════════════════════════════
# 1 — the "3/1" counter regression
# ══════════════════════════════════════════════════════════════════════════
#
# SEAM NOTE: these drive `dispatch_urls` DIRECTLY with registered capabilities.
# Setting `_backend_override` and calling research() does NOT work — research()
# only takes the dispatch path when the override is None and fetch.crawl is
# registered, so an override-based test silently exercises the batch path and
# the forwarding filter is never reached. (An earlier revision of this file did
# exactly that and passed with the filter removed.)


class _InnerLifecycleCap:
    """A capability that emits what the real fetch_url emits: its OWN
    CRAWLER_STARTED with url_count=1, then a page event numbered 1/1 because a
    single-URL fetch can only ever see one page."""

    name = "fetch.crawl"

    def __init__(self):
        self.calls: list[str] = []

    async def available(self):
        return True

    async def fetch_one(self, url, goal, job_id, on_progress=None):
        from backend.crawler.capabilities import FetchOutcome
        from backend.crawler.orchestrator import CrawlProgress
        from backend.crawler.usability import UsabilityReason, UsabilityVerdict

        self.calls.append(url)
        if on_progress is not None:
            on_progress(CrawlProgress("CRAWLER_STARTED", {
                "query": url, "url_count": 1, "session_id": job_id,
            }))
            on_progress(CrawlProgress("CRAWLER_PAGE_FETCHED", {
                "url": url, "page_number": 1, "total": 1, "job_id": job_id,
            }))
        return FetchOutcome(
            url=url, capability=self.name,
            page=_page(url, "real retrieved content for this url"),
            verdict=UsabilityVerdict(True, UsabilityReason.OK, ""),
        )


class _NoHistory:
    async def resolve(self, *a, **k):
        return None


def _dispatch(urls, emit_sink):
    from backend.crawler.capabilities import register_capability

    cap = _InnerLifecycleCap()
    register_capability(cap)
    orch = CrawlOrchestrator()
    orch._backend_override = None
    asyncio.run(orch.dispatch_urls(
        urls, query="party builds", job_id="job-1",
        on_progress=lambda p: emit_sink.append((p.event, p.payload)),
        concurrency_limit=3,
    ))
    return cap


def test_per_url_fetch_does_not_leak_inner_lifecycle_events():
    """The OUTER run owns CRAWLER_STARTED. A per-URL fetch re-emitting it made
    the panel treat every escalated URL as a brand new crawl — resetting
    pagesDone to 0 and forcing pagesTotal to 1 (the live "3/1")."""
    events: list[tuple[str, dict]] = []
    _dispatch(["https://a.example.com/", "https://b.example.com/"], events)

    starts = [e for e, _ in events if e == "CRAWLER_STARTED"]
    assert not starts, (
        f"{len(starts)} inner CRAWLER_STARTED event(s) leaked to the outer run "
        f"— each per-URL fetch restarts the crawl in the UI, resetting the "
        f"counter and knocking the overlay back to `loading` (which kills the "
        f"shutter animation and wipes the cursor)"
    )


def test_page_events_carry_the_outer_runs_numbering():
    """Each per-URL fetch reports 1/1. Forwarded unchanged that yields
    page_number climbing past total — the "3/1" the header chip rendered."""
    events: list[tuple[str, dict]] = []
    _dispatch(
        ["https://a.example.com/", "https://b.example.com/", "https://c.example.com/"],
        events,
    )

    pages = [pl for e, pl in events if e == "CRAWLER_PAGE_FETCHED"]
    assert pages, "no page events reached the outer run at all"
    for pl in pages:
        num, total = pl.get("page_number"), pl.get("total")
        assert total == 3, (
            f"total={total} — the inner fetch's 1/1 was forwarded unchanged, so "
            f"the chip reads 'N/1' however many URLs the run actually has"
        )
        assert num is not None and 1 <= num <= total, (
            f"page_number={num} outside 1..{total}"
        )


# ══════════════════════════════════════════════════════════════════════════
# 2 — the event-loop freeze
# ══════════════════════════════════════════════════════════════════════════

def test_suggest_action_call_site_uses_to_thread():
    """The provider call must stay OFF the event loop.

    This is a structural pin rather than a timing test on purpose. A timing
    version was written first — drive a slow synchronous provider and assert a
    concurrent ticker keeps running — and it PASSED with the fix reverted, twice,
    with bytecode caches cleared. A guard that cannot fail is worse than no
    guard: it manufactures confidence. It was deleted rather than tuned, because
    the thing that actually distinguishes the defect is whether the call is
    dispatched off the loop, and that is exactly what this asserts. Verified to
    FAIL when the to_thread dispatch is removed.
    """
    src = (_REPO / "backend" / "vision" / "fetch_vision.py").read_text(
        encoding="utf-8", errors="replace",
    )
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_suggest_action":
            found = "to_thread" in ast.unparse(node)
    assert found, (
        "_suggest_action no longer dispatches the provider via asyncio.to_thread "
        "— a synchronous provider call there blocks the entire backend"
    )


# ══════════════════════════════════════════════════════════════════════════
# 3 — the browser closed under a live session
# ══════════════════════════════════════════════════════════════════════════

def test_active_session_renews_its_lease_and_defers_idle_stop():
    """A session that outlives its initial lease window must keep the shared
    browser alive; an ABANDONED one must still expire (the leak guard)."""
    from backend.vision import browser_pool

    lease = browser_pool.BrowserLease("lease-x", time.monotonic() + 0.05)
    with browser_pool._LEASE_LOCK:
        browser_pool._BROWSER_LEASES["lease-x"] = lease.deadline

    # Renewal keeps it alive past the original deadline.
    time.sleep(0.08)
    lease.renew(5_000)
    assert lease.active, "renew() did not extend a live lease"
    assert browser_pool.has_active_browser_lease(), (
        "a renewed lease is not visible to the pool, so the idle watchdog can "
        "still close the browser under a live session"
    )

    # Abandoned (never renewed) leases still expire — leak guard intact.
    lease2 = browser_pool.BrowserLease("lease-y", time.monotonic() + 0.02)
    with browser_pool._LEASE_LOCK:
        browser_pool._BROWSER_LEASES["lease-y"] = lease2.deadline
    lease.release()
    time.sleep(0.05)
    assert not lease2.active, "an abandoned lease never expired — it would pin the browser forever"

    lease2.release()
