"""Behavioral tests: quick-search tier latency + REQ-16 frames.

REQ-8 AC8.2 (T11): the provider quick search completes fast and preserves the
REQ-16 progress/card event frames (``TASK_PROGRESS`` + the browser-panel
vocabulary) that CT-DEI-4 locks.

The frames are asserted against the SHARED emitter (``_crawl_ui_emitter``) and
the SHARED event bus — the same two seams the orchestrator path speaks through
— so a reroute that silently stopped animating the card fails here.
"""

from __future__ import annotations

import asyncio
import time

from backend.agent import tool_bridge as tb
from backend.agent.tool_bridge import AgentToolBridge
from backend.crawler.search_providers.base import SearchResult, SearchResultItem


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeProvider:
    def __init__(self, items):
        self._items = list(items)
        self.calls = 0

    async def search(self, query, max_results=10):
        self.calls += 1
        return SearchResult(query=query, results=self._items[:max_results],
                            provider="exa")


class _BusRecorder:
    """Stands in for the event bus — records TASK_PROGRESS frames."""

    def __init__(self):
        self.frames: list = []

    def emit(self, kind, data=None, session_id=None, conversation_id=None):
        self.frames.append({"kind": kind, "data": data or {}})


class _UiRecorder:
    """Records the browser-panel vocabulary the overlay listens for."""

    def __init__(self):
        self.events: list = []

    def __call__(self, progress):
        self.events.append(getattr(progress, "event", ""))


def _install_frames(monkeypatch, bus: _BusRecorder, ui: _UiRecorder):
    import backend.agent.event_bus as eb

    monkeypatch.setattr(eb, "get_event_bus", lambda: bus)
    monkeypatch.setattr(tb, "_crawl_ui_emitter", lambda session_id: ui)


def test_provider_latency_and_frames(monkeypatch):
    """AC8.2: one provider call answers the step, quickly, and BOTH frame
    vocabularies are emitted (TASK_PROGRESS + browser-panel)."""
    from backend.crawler import search_providers as sp_mod
    import backend.crawler.orchestrator as orch_mod

    items = [
        SearchResultItem(url=f"https://e.com/{i}", title=f"T{i}",
                         content=f"body {i}")
        for i in range(1, 4)
    ]
    fake = _FakeProvider(items)
    monkeypatch.setattr(sp_mod, "get_search_provider", lambda: fake)

    def _no_subprocess(*a, **kw):
        raise AssertionError("subprocess path taken on the quick tier")

    monkeypatch.setattr(orch_mod, "CrawlOrchestrator", _no_subprocess)

    bus, ui = _BusRecorder(), _UiRecorder()
    _install_frames(monkeypatch, bus, ui)

    started = time.perf_counter()
    out = _run(AgentToolBridge()._execute_web_search(
        {"query": "what is the rtx 5090 price"}, "s-lat"))
    elapsed = time.perf_counter() - started

    # ── latency: ONE provider round-trip, no subprocess, no LLM planning ──
    assert fake.calls == 1
    assert elapsed < 0.5, (
        f"quick search took {elapsed:.3f}s with a stubbed provider — that is "
        "not a single provider round-trip"
    )

    # ── the envelope the tool contract expects ──
    assert out["success"] is True
    assert out["sources"] == [i.url for i in items]
    assert out["meta"]["quick_search"] is True

    # ── browser-panel vocabulary (CT-DEI-4): started + one per page + complete ──
    assert ui.events[0] == "CRAWLER_STARTED"
    assert ui.events.count("CRAWLER_PAGE_FETCHED") == len(items)
    assert ui.events[-1] == "CRAWLER_COMPLETE"

    # ── TASK_PROGRESS frames (the CHAT CARD vocabulary) ──
    task = [f for f in bus.frames if f["data"].get("update_step")]
    assert task, "no TASK_PROGRESS frames — the chat card would stay inert"
    detail_urls = [f["data"].get("detail_url") for f in task if f["data"].get("detail_url")]
    assert detail_urls == [i.url for i in items], (
        "per-source detail_url frames are missing — the card cannot render "
        "which pages were read"
    )
