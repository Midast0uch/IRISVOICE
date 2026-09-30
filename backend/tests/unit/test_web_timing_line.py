"""Spec A7 (websearch-vision-browser, REQ-7): ONE structured timing line per web tool call.

Every `search` / `crawler_query` call logs exactly one
``[web_timing] ... search_ms= crawl_ms= pages_usable= pages_cancelled= extract_ms=
browser_actions= cursor_events=`` line, every key always present (0 when the path did not
measure it), so a slow turn is answerable from the log without a stack dump.

Hermetic: fake provider / fake orchestrator; real dispatch (`execute_tool`).
"""
from __future__ import annotations

import asyncio
import logging
import re

import pytest

import backend.agent.tool_bridge as tb
import backend.agent.tool_registry as tr
from backend.agent.tool_bridge import AgentToolBridge
from backend.crawler.search_providers.base import SearchResult, SearchResultItem

_KEYS = (
    "search_ms", "crawl_ms", "pages_usable", "pages_cancelled", "extract_ms",
    "browser_actions", "cursor_events",
)


@pytest.fixture(autouse=True)
def _gate_env(monkeypatch):
    monkeypatch.setattr(tr, "_internet_provider", lambda: True)
    monkeypatch.setattr(tr, "_desktop_provider", lambda: True)
    import backend.capabilities as caps
    monkeypatch.setattr(caps.CapabilitySet, "is_tool_allowed", staticmethod(lambda name: True))
    # the card/panel emitters are not under test
    monkeypatch.setattr(tb, "_crawl_ui_emitter", lambda session_id: (lambda progress: None))


def _timing_lines(caplog):
    return [r.getMessage() for r in caplog.records if "[web_timing]" in r.getMessage()]


def _fields(line: str) -> dict:
    return dict(re.findall(r"(\w+)=(\S+)", line))


class _FakeProvider:
    def __init__(self, items):
        self._items = items

    async def search(self, query, max_results=10):
        await asyncio.sleep(0.05)
        return SearchResult(query=query, results=self._items[:max_results], provider="exa")


def test_search_call_logs_one_timing_line_with_every_key(monkeypatch, caplog):
    from backend.crawler import search_providers as sp_mod

    items = [
        SearchResultItem(url=f"https://e.com/{i}", title=f"T{i}", content=f"body {i}")
        for i in (1, 2)
    ]
    monkeypatch.setattr(sp_mod, "get_search_provider", lambda: _FakeProvider(items))

    with caplog.at_level(logging.INFO, logger="backend.agent.tool_bridge"):
        result = asyncio.run(
            AgentToolBridge().execute_tool("search", {"query": "python creator"}, session_id="s-a7")
        )

    assert result.get("success") is True
    lines = _timing_lines(caplog)
    assert len(lines) == 1, lines
    f = _fields(lines[0])
    for key in _KEYS:
        assert key in f, f"{key} missing from {lines[0]!r}"
    assert f["tool"] == "search" and f["session"] == "s-a7" and f["ok"] == "True"
    assert int(f["search_ms"]) >= 40, "the provider call's wall time was not measured"
    assert f["pages_usable"] == "2"
    assert f["crawl_ms"] == "0" and f["extract_ms"] == "0"
    assert f["browser_actions"] == "0" and f["cursor_events"] == "0"


def test_crawler_query_call_logs_one_line_with_the_crawl_phases_and_cursor_events(
    monkeypatch, caplog
):
    from backend.crawler.crawler_engine import CrawlResult, PageData
    from backend.crawler.orchestrator import CrawlProgress

    class _Orch:
        async def research(self, query, on_progress=None, **kw):
            # a vision-fallback read: one approach event + one done event for ONE action
            on_progress(CrawlProgress("CRAWLER_VISION_ACTION", {"kind": "click", "phase": "approach"}))
            on_progress(CrawlProgress("CRAWLER_VISION_ACTION", {"kind": "click", "phase": "done", "ok": True}))
            res = CrawlResult(
                query=query, duration_ms=10, crawled_at="2026-09-30T00:00:00+00:00",
                pages=[PageData(
                    url="https://example.com/a", title="A", html="",
                    markdown="# A\n\nBody A with enough prose to satisfy the usability predicate.",
                    metadata={},
                )],
            )
            res.web_timing = {
                "search_ms": 120, "crawl_ms": 3400, "extract_ms": 55,
                "pages_usable": 1, "pages_cancelled": 2,
            }
            return res

    monkeypatch.setattr(
        "backend.crawler.orchestrator.get_crawl_orchestrator", lambda: _Orch()
    )

    with caplog.at_level(logging.INFO, logger="backend.agent.tool_bridge"):
        result = asyncio.run(
            AgentToolBridge().execute_tool("crawler_query", {"query": "deep topic"}, session_id="s-a7b")
        )

    assert result.get("success") is True, result
    lines = _timing_lines(caplog)
    assert len(lines) == 1, lines
    f = _fields(lines[0])
    for key in _KEYS:
        assert key in f, f"{key} missing from {lines[0]!r}"
    assert f["tool"] == "crawler_query"
    assert (f["search_ms"], f["crawl_ms"], f["extract_ms"]) == ("120", "3400", "55")
    assert (f["pages_usable"], f["pages_cancelled"]) == ("1", "2")
    assert f["cursor_events"] == "2"
    assert f["browser_actions"] == "1", "approach+done is ONE action"


def test_a_failed_call_still_logs_its_line(monkeypatch, caplog):
    class _Boom:
        async def search(self, query, max_results=10):
            raise RuntimeError("provider down")

    from backend.crawler import search_providers as sp_mod
    monkeypatch.setattr(sp_mod, "get_search_provider", lambda: _Boom())
    import backend.crawler.orchestrator as orch_mod

    class _Orch:
        async def research(self, **kw):
            raise RuntimeError("deep path down too")

    monkeypatch.setattr(orch_mod, "CrawlOrchestrator", lambda: _Orch())

    with caplog.at_level(logging.INFO, logger="backend.agent.tool_bridge"):
        asyncio.run(AgentToolBridge().execute_tool("search", {"query": "x y"}, session_id="s-a7c"))

    lines = _timing_lines(caplog)
    assert len(lines) == 1, lines
    f = _fields(lines[0])
    assert all(k in f for k in _KEYS) and f["ok"] == "False"


def test_no_line_outside_a_web_call_and_no_leak_between_calls():
    # the helpers are inert with no call in flight, and a finished call leaves no dict behind
    tb._web_timing_add("search_ms", 5)
    assert tb._WEB_TIMING.get() is None
