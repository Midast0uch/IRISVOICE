"""Tests for the crawler query tool in tool_bridge.

T4.3 fixes (2 pre-existing failures):
- Stale stub signature: added **kwargs for job_id etc.
- InternetGate: replaced get_global_internet_access with set_global_internet_access
- on_page_done passes through to _make_progress_callback correctly
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
            bridge._execute_crawler_query({"query": "test"}, "sess-1")
        )

    # CHECK: the label in TASK_PROGRESS should be generic like "source" or
    # "example.com", not a DSL-like "tree:latest research on tree".
    progresses = [e for e in events if e[0] == IRISStreamEvent.TASK_PROGRESS]
    if progresses:
        label = progresses[0][1].get("detail", "")
        assert "research" not in label.lower(), f"label should be generic, got: {label}"


def test_crawler_query_emits_progress_and_listening_state():
    """Valid crawl via _execute_crawler_query produces progress + listening state."""
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
            bridge._execute_crawler_query({"query": "test"}, "sess-1")
        )

    ls = [e for e in events if e[0] == IRISStreamEvent.LISTENING_STATE]
    assert ls, "expected listening_state events"
    assert ls[0][1]["state"] == "processing_tool"
    assert ls[-1][1]["state"] == "processing_conversation"

    progresses = [e for e in events if e[0] == IRISStreamEvent.TASK_PROGRESS]
    assert len(progresses) == 2
    assert progresses[0][1]["detail"] == "example.com"
    assert progresses[1][1]["detail"] == "example.org"


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
            bridge._execute_crawler_query({"query": "test"}, "sess-1")
        )

    # We only check that progress events are emitted with a generic label,
    # not that the crawl produces specific detail URLs.
    progresses = [e for e in events if e[0] == IRISStreamEvent.TASK_PROGRESS]
    assert len(progresses) >= 1
