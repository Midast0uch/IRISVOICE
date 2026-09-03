"""BT-11 (REQ-19) — planner yields zero URLs, vision discovery runs, discovered
URLs are fetched through the normal funnel, honest outcome when unusable.

Reference dead end (2026-08-10, live): `[CrawlPlanner] LLM planning produced
no URLs for '...'; no search-engine fallback (DuckDuckGo removed). Crawl will
report 'no candidate urls'.` Every existing recovery rung (REQ-2's
broaden-and-retry) assumes the PLANNER produced URLs; when the planner itself
is the failure, re-planning re-fails identically. This test drives the real
orchestrator end to end with the planner stubbed empty and vision discovery
faked, and asserts the EMERGENT behaviour: discovery ran, its URLs reached
the real fetch path, and the run is still honest when they turn out unusable.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.crawler.crawl_planner import CrawlPlan
from backend.crawler.crawler_engine import CrawlResult, PageData
from backend.crawler.orchestrator import CrawlOrchestrator
from backend.vision.search_discovery import DiscoveryResult


def _page(url: str, markdown: str, error=None) -> PageData:
    return PageData(
        url=url, title="t", markdown=markdown, html=None,
        metadata={}, error=error, html_bytes=len(markdown or ""),
    )


@pytest.fixture(autouse=True)
def _clean_registries():
    """Parked sources / ask-tool state are process-wide singletons; a leaked
    park from one test would satisfy the next test's assertions for free."""
    from backend.agent.tools.ask_user_tool import (
        get_parked_source_registry,
        reset_ask_user_tool_for_testing,
    )

    reset_ask_user_tool_for_testing()
    get_parked_source_registry().clear()
    yield
    reset_ask_user_tool_for_testing()
    get_parked_source_registry().clear()


# ══════════════════════════════════════════════════════════════════════════
# BT-11 — zero-URL planner -> discovery -> normal fetch -> honest outcome
# ══════════════════════════════════════════════════════════════════════════

def test_zero_planned_urls_triggers_discovery_then_honest_failure_when_unusable(monkeypatch):
    """The core BT-11 trajectory: planner empty -> discovery finds URLs ->
    those URLs are fetched through the SAME backend planned URLs would use ->
    every discovered page turns out unusable -> REQ-15 honest failure, not a
    silent 'no candidate urls' dead end."""
    fetch_calls: list[list[str]] = []

    class _UnusableBackend:
        async def fetch(self, *, query, urls, instructions, max_pages,
                        on_page_done=None, timeout_s=None, job_id=""):
            fetch_calls.append(list(urls))
            return CrawlResult(
                query=query,
                pages=[_page(u, "") for u in urls],  # empty markdown -> unusable
                duration_ms=1, crawled_at="", error=None,
            )

    orch = CrawlOrchestrator()
    orch._backend_override = _UnusableBackend()  # forces the batch-fetch path

    async def _empty_plan(q):
        return CrawlPlan(urls=[], instructions="", result_type="mixed", title="t")

    monkeypatch.setattr(orch, "_plan", _empty_plan)

    discovery_calls: list[str] = []

    async def _fake_discover(query, job_id, _emit=None, **kw):
        discovery_calls.append(query)
        return DiscoveryResult(urls=[
            "https://found-a.example/page", "https://found-b.example/page",
        ])

    import backend.vision.search_discovery as sd_mod
    monkeypatch.setattr(sd_mod, "discover_urls_via_vision", _fake_discover)

    result = asyncio.run(orch.research("a query the planner cannot resolve", mode="agent"))

    assert len(discovery_calls) == 1, "discovery never ran on a zero-URL plan"
    assert fetch_calls, "discovered URLs never reached the normal fetch backend"
    assert set(fetch_calls[0]) == {
        "https://found-a.example/page", "https://found-b.example/page",
    }, "the fetch call did not receive the discovered URLs"
    assert result.error, (
        "every discovered URL was unusable — the run must fail HONESTLY "
        "(REQ-15), not silently succeed or dead-end as 'no candidate urls'"
    )
    assert result.error != "no candidate urls", (
        "discovery ran and found URLs, so the failure reason must reflect "
        "that they were fetched-and-unusable, not that none were found"
    )
    # REQ-19 AC6: discovered pages carry distinguishable provenance even on
    # the failure path (they were still fetched and judged).
    assert all(
        p.metadata.get("url_origin") == "vision_discovered" for p in result.pages
    )


def test_discovery_not_attempted_when_planner_already_has_urls(monkeypatch):
    """Discovery must be a LAST resort, not a parallel default path — a
    planner that already produced URLs must never trigger it."""
    class _UsableBackend:
        async def fetch(self, *, query, urls, instructions, max_pages,
                        on_page_done=None, timeout_s=None, job_id=""):
            return CrawlResult(
                query=query,
                pages=[_page(u, "quantum verification real content " * 5) for u in urls],
                duration_ms=1, crawled_at="", error=None,
            )

    orch = CrawlOrchestrator()
    orch._backend_override = _UsableBackend()

    async def _plan(q):
        return CrawlPlan(urls=["https://planned.example/a"], instructions="",
                         result_type="mixed", title="t")

    monkeypatch.setattr(orch, "_plan", _plan)

    discovery_calls: list[str] = []

    async def _fake_discover(query, job_id, _emit=None, **kw):
        discovery_calls.append(query)
        return DiscoveryResult(urls=["https://should-not-be-used.example/"])

    import backend.vision.search_discovery as sd_mod
    monkeypatch.setattr(sd_mod, "discover_urls_via_vision", _fake_discover)

    asyncio.run(orch.research("a normal query", mode="agent"))

    assert discovery_calls == [], "discovery ran even though the planner already had URLs"


def test_discovery_wall_parks_and_falls_through_to_honest_failure(monkeypatch):
    """REQ-19 AC5: a CAPTCHA on the search engine is parked and reported —
    the run still ends in the same honest 'no candidate urls' outcome a
    genuinely empty discovery would produce, never a fabricated success."""
    from backend.agent.tools.ask_user_tool import get_parked_source_registry

    orch = CrawlOrchestrator()
    orch._backend_override = object()  # must never be called

    async def _empty_plan(q):
        return CrawlPlan(urls=[], instructions="", result_type="mixed", title="t")

    monkeypatch.setattr(orch, "_plan", _empty_plan)

    async def _fake_discover(query, job_id, _emit=None, **kw):
        return DiscoveryResult(wall="captcha", engine_url="https://www.bing.com/")

    import backend.vision.search_discovery as sd_mod
    monkeypatch.setattr(sd_mod, "discover_urls_via_vision", _fake_discover)

    result = asyncio.run(orch.research("a walled query", mode="agent", job_id="run-wall"))

    assert result.error == "no candidate urls"
    parked = get_parked_source_registry().pending("run-wall")
    assert len(parked) == 1 and parked[0].wall_kind == "captcha"
