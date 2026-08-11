"""
Tests for Issue E — Web Mode Relay Unification (internet-access gate).

Validates:
  - set_web_mode flips the app-wide global internet-access flag
  - get_available_tools() omits web tools when the flag is OFF, includes them ON
  - execute_tool() rejects web tools when the flag is OFF (defense-in-depth)
  - _execute_crawler_query returns the full extracted `content` (rich markdown),
    not just the short summary

Run: python -m pytest backend/tests/test_web_mode_gate.py -v
"""

import asyncio
import pytest

from backend.agent.agent_kernel import (
    set_global_internet_access,
    get_global_internet_access,
)
from backend.agent.tool_bridge import AgentToolBridge


@pytest.fixture(autouse=True)
def _reset_internet_flag():
    """Ensure the global flag is OFF before/after each test (default state)."""
    set_global_internet_access(False)
    yield
    set_global_internet_access(False)


def _tool_names():
    return {t["name"] for t in AgentToolBridge().get_available_tools()}


def test_set_web_mode_flips_global_flag():
    assert get_global_internet_access() is False
    set_global_internet_access(True)
    assert get_global_internet_access() is True
    set_global_internet_access(False)
    assert get_global_internet_access() is False


def test_web_mode_off_removes_tools():
    set_global_internet_access(False)
    names = _tool_names()
    assert "search" not in names
    assert "crawler_query" not in names


def test_web_mode_on_grants_tools():
    set_global_internet_access(True)
    names = _tool_names()
    assert "search" in names
    assert "crawler_query" in names


def test_execute_tool_rejects_when_off():
    set_global_internet_access(False)
    result = asyncio.run(
        AgentToolBridge().execute_tool("search", {"query": "latest news"}, "test-session")
    )
    assert result.get("success") is False
    assert "internet" in result.get("error", "").lower()


def test_crawler_query_returns_content():
    """_execute_crawler_query must surface the full extracted markdown in `content`."""
    set_global_internet_access(True)

    class _FakePage:
        def __init__(self, url, markdown, error=None, html=None):
            self.url = url
            self.markdown = markdown
            self.error = error
            self.html = html

    class _FakeCrawlResult:
        query = "test topic"
        duration_ms = 100
        error = None
        pages = [
            # REQ-1 AC1 (2026-08-10): the tool-boundary content collector now
            # judges pages with `page_is_usable`, which reads .error/.html/
            # .markdown and requires >= MIN_CONTENT_CHARS (20) stripped text.
            # The fixture carries `.html` and longer markdown so the collector
            # accepts it; assertions are unchanged.
            _FakePage(
                "https://example.com/a",
                "# Heading A\n\nBody A with enough prose to satisfy the "
                "content-usability predicate.",
            ),
            _FakePage(
                "https://example.com/b",
                "# Heading B\n\nBody B with enough prose to satisfy the "
                "content-usability predicate.",
            ),
        ]
        dashboard_data = {
            "title": "Test Topic",
            "summary": "Short summary of the crawl.",
            "pages": [
                {"url": "https://example.com/a", "title": "A"},
                {"url": "https://example.com/b", "title": "B"},
            ],
        }
        cited_markdown = "# Test Topic\n\nCited."

    class _FakeOrchestrator:
        async def research(self, query, **kwargs):
            return _FakeCrawlResult()

    # NOTE (2026-08-09, input update called out loud): this test's mock
    # seam encoded the OLD crawl pipeline (CrawlerEngine + crawl_planner +
    # data_extractor). _execute_crawler_query now routes through
    # CrawlOrchestrator.research() (REQ-15 unified funnel), so the old
    # patches no longer intercepted and the REAL crawler fetched
    # example.com over the network. The seam moved to
    # get_crawl_orchestrator(); the assertions below are unchanged — the
    # requirement (full rich markdown in `content`, not just the summary)
    # is identical.
    from unittest.mock import patch

    with patch("backend.crawler.orchestrator.get_crawl_orchestrator", return_value=_FakeOrchestrator()):
        result = asyncio.run(
            AgentToolBridge()._execute_crawler_query({"query": "test topic"}, "test-session")
        )

    assert result.get("success") is True
    assert "content" in result
    content = result["content"]
    assert "Heading A" in content
    assert "Heading B" in content
    assert "https://example.com/a" in content
    # summary is still present (agent puts it in `speak`)
    assert result.get("summary")


class TestIsWebSearchRequest:
    """Tests for AgentKernel._is_web_search_request heuristics."""

    def test_web_search_phrases_match(self):
        """Explicit web-search phrases should return True."""
        from backend.agent.agent_kernel import AgentKernel
        agent = AgentKernel.__new__(AgentKernel)
        assert agent._is_web_search_request("web search")
        assert agent._is_web_search_request("do a web search for me")
        assert agent._is_web_search_request("search the web for Python")
        assert agent._is_web_search_request("look up online how to code")
        assert agent._is_web_search_request("find on the internet")
        assert agent._is_web_search_request("browse the web")

    def test_non_search_phrases_dont_match(self):
        """General conversation should not trigger web-search detection."""
        from backend.agent.agent_kernel import AgentKernel
        agent = AgentKernel.__new__(AgentKernel)
        assert not agent._is_web_search_request("hello")
        assert not agent._is_web_search_request("what is the weather like")
        assert not agent._is_web_search_request("tell me a joke")
        assert not agent._is_web_search_request("I searched for my keys")
        assert not agent._is_web_search_request("")
        assert not agent._is_web_search_request("How do you write Python code?")
        assert not agent._is_web_search_request("search (but offline)")
