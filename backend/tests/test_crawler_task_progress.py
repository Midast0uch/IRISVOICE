"""
CDD test: crawler_query emits live task:progress + listening_state events.

Verifies the multi-step tool-call visualization fix (plan §12):
  - _execute_crawler_query flips listening_state -> processing_tool during the
    crawl and back to processing_conversation afterwards.
  - It emits a task:progress per fetched page (update_step=True) so the plan
    card + ContextPill show the site being read live.
  - _tool_action_label is generic across ALL tools (not crawler-specific), so a
    task that starts as a simple widget action and evolves into a web search
    still shows a live action.

Run: python -m pytest backend/tests/test_crawler_task_progress.py -v
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from backend.agent.event_bus import get_event_bus, IRISStreamEvent
from backend.agent.tool_bridge import AgentToolBridge
from backend.crawler.crawler_engine import CrawlResult


def test_tool_action_label_is_generic():
    """Live action label must cover every tool, not just the crawler."""
    bridge = AgentToolBridge.__new__(AgentToolBridge)
    assert "Searching the web" in bridge._tool_action_label(
        "crawler_query", {"query": "latest news"}
    )
    assert bridge._tool_action_label("write_file", {"path": "/a/b/app.tsx"}) == "Editing app.tsx"
    assert bridge._tool_action_label("read_file", {"path": "/a/b/x.txt"}) == "Reading x.txt"
    assert "Running:" in bridge._tool_action_label("run_command", {"command": "ls -la"})
    assert bridge._tool_action_label("unknown_tool", {}) == "Using unknown_tool"


def test_crawler_query_emits_progress_and_listening_state():
    bus = get_event_bus()
    events = []

    def _collect(p):
        events.append((p.event, dict(p.data or {})))

    sub_call = bus.subscribe(IRISStreamEvent.TASK_PROGRESS, _collect)
    sub_ls = bus.subscribe(IRISStreamEvent.LISTENING_STATE, _collect)

    class _Plan:
        urls = ["https://example.com/a", "https://example.org/b"]
        instructions = "extract"
        result_type = "summary"
        title = "Test"

    # The crawl now runs in an isolated subprocess (crawl_runner). We mock the
    # runner's entry point the same way the old test mocked CrawlerEngine: it
    # reports per-page progress via on_page_done, then returns a CrawlResult.
    async def _fake_run(query, urls, instructions, on_page_done=None,
                        max_pages=5, delay_ms=1000, timeout_s=90.0):
        if on_page_done:
            on_page_done("https://example.com/a", 1, 2)
            on_page_done("https://example.org/b", 2, 2)
        return CrawlResult(
            query=query, pages=[], duration_ms=10,
            crawled_at="2026-01-01T00:00:00+00:00",
        )

    with patch("backend.crawler.crawl_planner.get_crawl_planner") as gp, patch(
        "backend.crawler.crawl_runner.run_crawl_subprocess", _fake_run
    ), patch("backend.crawler.data_extractor.get_data_extractor") as gde, patch(
        "backend.agent.tools.speak_tool.get_speak_tool"
    ) as gst:
        gp.return_value.plan = AsyncMock(return_value=_Plan())
        gde.return_value.extract = AsyncMock(
            return_value={"pages": [], "summary": "s", "title": "t"}
        )
        gst.return_value.speak = MagicMock()
        bridge = AgentToolBridge.__new__(AgentToolBridge)
        result = asyncio.run(
            bridge._execute_crawler_query({"query": "test"}, "sess-1")
        )

    bus.unsubscribe(IRISStreamEvent.TASK_PROGRESS, sub_call)
    bus.unsubscribe(IRISStreamEvent.LISTENING_STATE, sub_ls)

    assert result.get("success") is True, result

    # ── listening_state: processing_tool during crawl, processing_conversation after ──
    ls = [e for e in events if e[0] == IRISStreamEvent.LISTENING_STATE]
    assert ls, "expected listening_state events"
    assert ls[0][1]["state"] == "processing_tool"
    assert ls[-1][1]["state"] == "processing_conversation"

    # ── task:progress: one per page, update_step=True, with the host ──
    progresses = [e for e in events if e[0] == IRISStreamEvent.TASK_PROGRESS]
    assert len(progresses) == 2, progresses
    assert progresses[0][1]["update_step"] is True
    assert "Reading example.com" in progresses[0][1]["description"]
    assert "Reading example.org" in progresses[1][1]["description"]


def test_execute_tool_emits_generic_progress_for_any_tool():
    """execute_tool must emit a live task:progress for ALL tools (generic)."""
    bus = get_event_bus()
    events = []

    def _collect(p):
        events.append((p.event, dict(p.data or {})))

    sub = bus.subscribe(IRISStreamEvent.TASK_PROGRESS, _collect)

    class _FakeBridge(AgentToolBridge):
        async def _execute_web_search(self, params, session_id):
            return {"success": True, "content": "x", "summary": "s"}

    with patch("backend.agent.tools.speak_tool.get_speak_tool") as gst, patch(
        "backend.capabilities.CapabilitySet.is_tool_allowed",
        return_value=True,
    ), patch(
        "backend.agent.agent_kernel.get_global_internet_access",
        return_value=True,
    ):
        gst.return_value.speak = MagicMock()
        bridge = _FakeBridge.__new__(_FakeBridge)
        asyncio.run(
            bridge.execute_tool("search", {"query": "news"}, "sess-2")
        )

    bus.unsubscribe(IRISStreamEvent.TASK_PROGRESS, sub)

    progresses = [e for e in events if e[0] == IRISStreamEvent.TASK_PROGRESS]
    assert progresses, "expected a generic task:progress from execute_tool"
    assert "Searching the web" in progresses[0][1]["description"]
