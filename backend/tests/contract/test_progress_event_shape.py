"""Contract test CT-I4: progress event shape.

REQ-2 AC4 / design.md: `detail` / `detail_progress` / `update_step` present
and structured on every crawl progress emission; `description` retained for
back-compat (older consumers, and the fallback when `detail` is absent).

Drives the REAL `AgentToolBridge._execute_crawler_query` progress path (a
fake orchestrator stands in for the network-bound crawl; the progress-event
construction and emission is the real production closure, not a
reimplementation) and asserts the EFFECT: the actual `TASK_PROGRESS` event
captured off the real EventBus carries the structured fields.
"""

from __future__ import annotations

import asyncio

import backend.crawler.orchestrator as orch_mod
from backend.agent.event_bus import (
    IRISStreamEvent,
    get_event_bus,
    reset_event_bus_for_testing,
)
from backend.agent.tool_bridge import AgentToolBridge
from unittest.mock import patch


class _FakeOrchestratorOnePage:
    """Stands in for the network-bound crawl orchestrator. Calls the REAL
    on_progress callback with one CRAWLER_PAGE_FETCHED event (the only
    signal shape `_on_page_done` needs), then bails out — we only care
    about the progress event `_on_page_done` builds and emits, not the
    final crawl result.
    """

    async def research(self, query, *, mode="agent", session_id="", on_progress=None, **kw):
        if on_progress:
            on_progress(
                orch_mod.CrawlProgress(
                    event="CRAWLER_PAGE_FETCHED",
                    payload={
                        "url": "https://example.com/article",
                        "page_number": 1,
                        "total": 3,
                        "title": "Example Article",
                    },
                )
            )
        raise RuntimeError("stop-early-for-test — only the progress event matters here")


def _capture_progress_event():
    reset_event_bus_for_testing()
    bus = get_event_bus()
    captured: list = []
    bus.subscribe(IRISStreamEvent.TASK_PROGRESS, lambda p: captured.append(p.data))

    with patch.object(orch_mod, "get_crawl_orchestrator",
                       return_value=_FakeOrchestratorOnePage()), \
         patch("backend.agent.narration.may_narrate", return_value=False):
        bridge = AgentToolBridge()
        result = asyncio.run(
            bridge._execute_crawler_query({"query": "python 3.13 release notes"},
                                           "ct-i4-session")
        )
    return captured, result


class TestProgressEventShape:
    def test_a_page_fetch_produces_a_structured_progress_event(self):
        captured, result = _capture_progress_event()
        assert len(captured) >= 1, (
            f"no TASK_PROGRESS event was captured for a page-fetch progress "
            f"callback — tool returned {result!r}"
        )

    def test_progress_event_carries_structured_detail_fields(self):
        captured, result = _capture_progress_event()
        assert captured, f"no TASK_PROGRESS event captured; tool returned {result!r}"
        payload = captured[-1]
        assert payload.get("detail"), f"'detail' missing/empty in {payload}"
        assert payload.get("detail_progress"), f"'detail_progress' missing/empty in {payload}"
        assert payload.get("update_step") is True, f"'update_step' not True in {payload}"

    def test_description_is_retained_for_back_compat(self):
        captured, result = _capture_progress_event()
        assert captured, f"no TASK_PROGRESS event captured; tool returned {result!r}"
        payload = captured[-1]
        assert payload.get("description"), (
            f"'description' dropped from the progress payload — REQ-2 AC4 "
            f"requires it retained as the back-compat fallback for consumers "
            f"that predate the structured `detail` field: {payload}"
        )
