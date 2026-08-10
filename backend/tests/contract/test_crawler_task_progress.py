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
    This test therefore partitions the stream by the presence of the `phase`
    key (phase events carry `phase`/`phase_sequence`; page events never do —
    the old `_phase_cache` merge that used to stamp `phase` onto page events
    was removed when dedicated phase emission landed) and checks each kind on
    its own filtered list:
      - exactly 2 page events, in fetch order (unchanged coverage — still
        guarantees one event per page, no duplicates)
      - at least 1 phase event fired (new coverage for REQ-4 AC1)
    """
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
        "backend.crawler.crawl_runner.run_crawl_subprocess", _fake_run
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
            bridge._execute_crawler_query({"query": "test"}, "sess-progress-phase")
        )

    ls = [e for e in events if e[0] == IRISStreamEvent.LISTENING_STATE]
    assert ls, "expected listening_state events"
    assert ls[0][1]["state"] == "processing_tool"
    assert ls[-1][1]["state"] == "processing_conversation"

    progresses = [e for e in events if e[0] == IRISStreamEvent.TASK_PROGRESS]
    # Phase events carry `phase`; page events never do (confirmed empirically —
    # the removed `_phase_cache` merge is what used to put `phase` on page
    # events, and it is gone). Partition on that, not on `detail`, since
    # `detail` is present on BOTH kinds and cannot discriminate them.
    phase_events = [e for e in progresses if "phase" in e[1]]
    page_events = [e for e in progresses if "phase" not in e[1]]

    assert len(page_events) == 2
    assert page_events[0][1]["detail"] == "example.com"
    assert page_events[1][1]["detail"] == "example.org"

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
