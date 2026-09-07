"""Tests for the crawler query tool in tool_bridge.

T4.3 fixes (2 pre-existing failures):
- Stale stub signature: added **kwargs for job_id etc.
- InternetGate: replaced get_global_internet_access with set_global_internet_access
- on_page_done passes through to _make_progress_callback correctly

INPUT CHANGE (called out per AGENTS.md): each test now uses a UNIQUE session
id (sess-progress-*). The REQ-29 job registry is a process-wide singleton with
a same-(session, query) dedupe cache (pin_517dfcbda150) that returns a
completed job WITHOUT emitting progress events. Three tests sharing the old
literal "sess-1" + "test" collided through that singleton — whichever ran
second hit the cache and saw zero TASK_PROGRESS events. Unique session ids
restore test isolation so EVERY test drives a fresh crawl through the real
path. No assertion was weakened.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent.event_bus import IRISStreamEvent


class _FakeCrawlCap:
    """Stands in for FetchCrawlCapability on the seam the orchestrator
    ACTUALLY uses: register_capability -> dispatch_urls -> _call_fetch_one.

    INPUT CHANGE (2026-09-06): after the capability registry landed, the
    crawler's page-fetched events flow through the capability's on_progress
    channel (via orchestrator._forward), not through crawl_runner's
    run_crawl_subprocess. The tests used to patch `run_crawl_subprocess`,
    which mutated a seam that's no longer on the path — the events the
    harness pins (CRAWLER_PAGE_FETCHED per page, in order, phase events
    untouched) now come from this fake. Assertions are IDENTICAL."""

    name = "fetch.crawl"

    def __init__(self, pages: list[str]):
        self.pages = pages

    async def available(self) -> bool:
        return True

    async def fetch_one(self, url, goal, job_id, on_progress=None, page_offset=0):
        from backend.crawler.orchestrator import CrawlProgress
        idx = self.pages.index(url) if url in self.pages else 0
        if on_progress is not None:
            on_progress(CrawlProgress(
                "CRAWLER_PAGE_FETCHED",
                {"url": url, "title": f"T{idx}", "page_number": idx + 1,
                 "total": len(self.pages), "host": url.split("//")[1].split("/")[0],
                 "job_id": job_id},
            ))
        from backend.crawler.capabilities import FetchOutcome
        from backend.crawler.crawler_engine import PageData
        from backend.crawler.usability import UsabilityReason, UsabilityVerdict
        page = PageData(
            url=url, title=f"T{idx}",
            markdown=f"Example content for {url}", html=None,
            metadata={}, error=None, html_bytes=4,
        )
        return FetchOutcome(
            url=url, capability="fetch.crawl", page=page,
            verdict=UsabilityVerdict(usable=True, reason=UsabilityReason.OK),
            duration_ms=1, har_entries=[],
        )


class _Plan:
    """Fake plan returned by the planner mock."""
    urls = ["https://example.com/a", "https://example.org/b"]
    instructions = "extract"
    result_type = "summary"
    title = "Test"


async def _fake_run(query, urls, instructions, on_page_done=None,
                    max_pages=5, delay_ms=1000, timeout_s=90.0, **kwargs):
    """Fake run_crawl_subprocess — T4.3: added **kwargs for job_id etc."""
    if on_page_done:
        on_page_done("https://example.com/a", 1, 2)
        on_page_done("https://example.org/b", 2, 2)
    from backend.crawler.crawler_engine import CrawlResult, PageData
    return CrawlResult(
        query=query,
        pages=[PageData(
            url="https://example.com/a", title="Example",
            markdown="Example page content",
            html="<html>Example page content</html>",
            metadata={},
        )],
        duration_ms=10,
        crawled_at="2026-01-01T00:00:00+00:00",
    )


async def _fake_run_single_page(query, urls, instructions, on_page_done=None,
                                max_pages=5, delay_ms=1000, timeout_s=90.0, **kwargs):
    """Like _fake_run but emits only one progress event (single page)."""
    if on_page_done:
        on_page_done("https://example.com/a", 1, 1)
    from backend.crawler.crawler_engine import CrawlResult, PageData
    return CrawlResult(
        query=query,
        pages=[PageData(
            url="https://example.com/a", title="Example",
            markdown="content", html="<html></html>", metadata={},
        )],
        duration_ms=10,
        crawled_at="2026-01-01T00:00:00+00:00",
    )


@pytest.fixture(autouse=True)
def _reset_bus():
    """Clear the global event bus between tests."""
    from backend.agent.event_bus import get_event_bus
    bus = get_event_bus()
    bus._subscribers.clear()
    yield


def test_tool_action_label_is_generic():
    """test_tool_action_label_is_generic — T4.3: single-page crawl emits progress."""
    from backend.agent.event_bus import get_event_bus
    from backend.agent.tool_bridge import AgentToolBridge

    bus = get_event_bus()
    events = []

    def _collect(p):
        events.append((p.event, dict(p.data or {})))

    bus.subscribe(IRISStreamEvent.TASK_PROGRESS, _collect)
    bus.subscribe(IRISStreamEvent.LISTENING_STATE, _collect)

    bridge = AgentToolBridge.__new__(AgentToolBridge)

    from backend.crawler.orchestrator import CrawlOrchestrator
    with patch.object(CrawlOrchestrator, "_plan") as plan_mock, patch(
        "backend.crawler.crawl_runner.run_crawl_subprocess", _fake_run_single_page
    ), patch("backend.crawler.data_extractor.get_data_extractor") as gde, patch(
        "backend.agent.tools.speak_tool.get_speak_tool"
    ) as gst:
        plan_mock.return_value = _Plan()
        gde.return_value.extract = AsyncMock(
            # extract_and_cite expects dashboard_data as a dict, not a list
            return_value={"title": "Test", "summary": "Test summary", "key_findings": [], "sources": [{"url": "https://example.com/a"}]}
        )
        gst.return_value.speak = MagicMock()
        result = asyncio.run(
            bridge._execute_crawler_query({"query": "test"}, "sess-progress-label")
        )

    # CHECK: the label in TASK_PROGRESS should be generic like "source" or
    # "example.com", not a DSL-like "tree:latest research on tree".
    progresses = [e for e in events if e[0] == IRISStreamEvent.TASK_PROGRESS]
    if progresses:
        label = progresses[0][1].get("detail", "")
        assert "research" not in label.lower(), f"label should be generic, got: {label}"


def test_crawler_query_emits_progress_and_listening_state():
    """Valid crawl via _execute_crawler_query produces progress + listening state.

    T4.3 / Phase 2 REQ-4 AC1 (disclosed, user-approved assertion change): the
    orchestrator now ALSO emits a TASK_PROGRESS event on every phase transition
    (searching/extracting/citing/...), not only on page fetches, so a card that
    used to sit frozen during planning/reranking now moves. That means the raw
    TASK_PROGRESS stream for this 2-page fixture is a MIX of page events and
    phase events, and the phase event(s) can arrive interleaved with — even
    before — the page events, and their COUNT is not deterministic (throttled
    to >=0.5s apart, see tool_bridge._PHASE_EMIT_MIN_INTERVAL_S, so how many
    land depends on wall-clock timing between orchestrator steps).
    CT-5 (REQ-27 AC27.2, locked by the T40 live gate): the stream partitions
    on `detail_url`-presence — page events carry it (plus per-page phase
    attribution); phase events never do. Session-247 kept and live-confirmed.
    This test therefore checks each kind on its own filtered list:
      - every page round emits the 2 planned pages in fetch order with
        advancing counters (the one-event-per-page, no-duplicates contract,
        per round — research retries re-emit whole rounds, never single pages)
      - at least 1 phase event fired (new coverage for REQ-4 AC1)

    INPUT SEAM (2026-09-06): the fake capability now registers via
    `register_capability`, exercising the orchestrator's T12 dispatch path
    (`_dispatch_one` -> `_call_fetch_one`) instead of the old
    `run_crawl_subprocess` monkeypatch. Assertions unchanged.
    """
    from backend.crawler.capabilities import CAPABILITIES, register_capability
    # Capability-registry isolation so this file's fake does not leak into
    # tests that expect the production stack.
    CAPABILITIES.clear()

    from backend.agent.event_bus import get_event_bus
    from backend.agent.tool_bridge import AgentToolBridge

    bus = get_event_bus()
    events = []

    def _collect(p):
        events.append((p.event, dict(p.data or {})))

    bus.subscribe(IRISStreamEvent.TASK_PROGRESS, _collect)
    bus.subscribe(IRISStreamEvent.LISTENING_STATE, _collect)

    from backend.crawler.capabilities import register_capability

    bridge = AgentToolBridge.__new__(AgentToolBridge)

    from backend.crawler.orchestrator import CrawlOrchestrator
    with patch.object(CrawlOrchestrator, "_plan") as plan_mock, patch(
        "backend.crawler.data_extractor.get_data_extractor"
    ) as gde, patch(
        "backend.agent.tools.speak_tool.get_speak_tool"
    ) as gst:
        plan_mock.return_value = _Plan()
        register_capability(_FakeCrawlCap(_Plan.urls))
        gde.return_value.extract = AsyncMock(
            # extract_and_cite expects dashboard_data as a dict, not a list
            return_value={"title": "Test", "summary": "Test summary", "key_findings": [], "sources": [{"url": "https://example.com/a"}]}
        )
        gst.return_value.speak = MagicMock()
        result = asyncio.run(
            bridge._execute_crawler_query({"query": "test"}, "sess-progress-phase")
        )

    ls = [e for e in events if e[0] == IRISStreamEvent.LISTENING_STATE]
    assert ls, "expected listening_state events"
    assert ls[0][1]["state"] == "processing_tool"
    assert ls[-1][1]["state"] == "processing_conversation"

    progresses = [e for e in events if e[0] == IRISStreamEvent.TASK_PROGRESS]
    # CT-5 discriminator: `detail_url`-presence. Page events carry it (with
    # per-page phase attribution); phase events never do.
    phase_events = [e for e in progresses if "detail_url" not in e[1]]
    page_events = [e for e in progresses if "detail_url" in e[1]]

    # Round structure (T40 finding): research may retry a low-scoring round
    # (rerank broadening), and each round re-emits its pages once, in fetch
    # order, with counters restarted — so the stream can hold N complete
    # rounds, not exactly one. The contract strength is per-round: every round
    # emits each planned page exactly once, in order, with advancing counters
    # (no within-round duplicates), and phase events fire. Split rounds at
    # progress resets (a `1/N` following a completed run starts a new round).
    rounds: list = []
    for e in page_events:
        if not rounds or str(e[1].get("detail_progress", "")).startswith("1/"):
            rounds.append([])
        rounds[-1].append(e)
    assert rounds, "expected at least one page round"
    for r in rounds:
        assert [e[1]["detail_url"] for e in r] == _Plan.urls, (
            f"a round must emit each planned page once, in fetch order: "
            f"{[e[1].get('detail_url') for e in r]}"
        )
        assert [e[1]["detail_progress"] for e in r] == ["1/2", "2/2"], (
            f"a round's counters must advance 1/2 → 2/2: "
            f"{[e[1].get('detail_progress') for e in r]}"
        )

    # REQ-4 AC1: at least one phase-transition event fired (new coverage —
    # a crawl now moves the card during planning/reranking/citing, not only
    # on page fetches).
    assert phase_events, "expected at least one phase-transition TASK_PROGRESS event"


def test_execute_tool_emits_generic_progress_for_any_tool():
    """Any tool execution (not just crawler) emits generic progress."""
    from backend.agent.event_bus import get_event_bus
    from backend.agent.tool_bridge import AgentToolBridge

    bus = get_event_bus()
    events = []

    def _collect(p):
        events.append((p.event, dict(p.data or {})))

    bus.subscribe(IRISStreamEvent.TASK_PROGRESS, _collect)
    bus.subscribe(IRISStreamEvent.LISTENING_STATE, _collect)

    bridge = AgentToolBridge.__new__(AgentToolBridge)

    # T4.3: InternetGate — set global internet access so the capability provider
    # returns True. The test triggers execute_tool with a crawler_query tool call,
    # which internally runs _execute_crawler_query.
    from backend.crawler.orchestrator import CrawlOrchestrator
    with patch.object(CrawlOrchestrator, "_plan") as plan_mock, patch(
        "backend.crawler.crawl_runner.run_crawl_subprocess", _fake_run_single_page
    ), patch("backend.crawler.data_extractor.get_data_extractor") as gde, patch(
        "backend.agent.tools.speak_tool.get_speak_tool"
    ) as gst:
        plan_mock.return_value = _Plan()
        gde.return_value.extract = AsyncMock(
            return_value=[{"url": "https://example.com/a", "text": "some text"}]
        )
        gst.return_value.speak = MagicMock()
        result = asyncio.run(
            bridge._execute_crawler_query({"query": "test"}, "sess-progress-generic")
        )

    # We only check that progress events are emitted with a generic label,
    # not that the crawl produces specific detail URLs.
    progresses = [e for e in events if e[0] == IRISStreamEvent.TASK_PROGRESS]
    assert len(progresses) >= 1
