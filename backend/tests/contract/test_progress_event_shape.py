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


class _FakeOrchestratorPhaseOnly:
    """Emits ONE CRAWLER_PHASE signal and no page fetches at all.

    REQ-4 AC1 requires phase transitions to emit progress independently of
    fetched pages, so the phase-event shape needs its own pin: nothing else
    guaranteed `phase` / `phase_sequence` were present. Two consumers depend on
    them — `hooks/useTaskProgress.ts` advances the card from `d.phase`, and
    `test_crawler_task_progress.py` partitions a mixed event stream on the
    presence of the `phase` key. A rename would break both silently.
    """

    async def research(self, query, *, mode="agent", session_id="", on_progress=None, **kw):
        if on_progress:
            on_progress(
                orch_mod.CrawlProgress(
                    event="CRAWLER_PHASE",
                    payload={"phase": "searching", "phase_sequence": 1},
                )
            )
        raise RuntimeError("stop-early-for-test — only the phase event matters here")


def _capture_phase_event():
    reset_event_bus_for_testing()
    bus = get_event_bus()
    captured: list = []
    bus.subscribe(IRISStreamEvent.TASK_PROGRESS, lambda p: captured.append(p.data))

    with patch.object(orch_mod, "get_crawl_orchestrator",
                       return_value=_FakeOrchestratorPhaseOnly()), \
         patch("backend.agent.narration.may_narrate", return_value=False):
        bridge = AgentToolBridge()
        result = asyncio.run(
            bridge._execute_crawler_query({"query": "python 3.13 release notes"},
                                           "ct-i4-phase-session")
        )
    return captured, result


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

    def test_page_event_does_not_carry_a_phase_key(self):
        """The discriminator invariant, asserted from the page side.

        `test_crawler_task_progress.py` splits a mixed stream into page vs phase
        events on `"phase" in payload`. If a page event ever gained that key the
        split would silently misclassify it, so pin it here rather than leaving
        the invariant implicit in another file's filter.
        """
        captured, result = _capture_progress_event()
        assert captured, f"no TASK_PROGRESS event captured; tool returned {result!r}"
        payload = captured[-1]
        assert "phase" not in payload, (
            f"a page-fetch progress event gained a 'phase' key, which breaks the "
            f"page/phase partition in test_crawler_task_progress.py: {payload}"
        )

    def test_phase_transition_event_carries_phase_fields(self):
        """REQ-4 AC1: a phase transition emits its own structured event."""
        captured, result = _capture_phase_event()
        assert captured, (
            f"no TASK_PROGRESS event captured for a CRAWLER_PHASE callback — "
            f"REQ-4 AC1 requires phase transitions to emit independently of "
            f"fetched pages; tool returned {result!r}"
        )
        payload = captured[-1]
        # Assert the VALUES the orchestrator emitted arrive intact, not merely
        # that the keys exist. `_on_progress`'s CRAWLER_PHASE branch reads
        # `pl.get("phase_sequence", 0)`, so an upstream omission is silently
        # substituted with 0 — and a `is not None` check happily passes on that
        # default, pinning the fallback rather than the propagation. The fake
        # emits phase="searching", phase_sequence=1; both must survive the trip.
        assert payload.get("phase") == "searching", (
            f"'phase' did not propagate from the orchestrator payload: {payload}"
        )
        assert payload.get("phase_sequence") == 1, (
            f"'phase_sequence' did not propagate (got {payload.get('phase_sequence')!r}, "
            f"expected 1) — useTaskProgress.ts orders phase movement by it, and a "
            f"defaulted 0 would silently reorder every phase: {payload}"
        )
        assert payload.get("update_step") is True, f"'update_step' not True in {payload}"
        assert payload.get("description"), (
            f"'description' missing from a phase event: {payload}"
        )
        assert "detail_url" not in payload, (
            f"a phase event carries 'detail_url', implying a page was fetched "
            f"when none was: {payload}"
        )

    def test_description_is_retained_for_back_compat(self):
        captured, result = _capture_progress_event()
        assert captured, f"no TASK_PROGRESS event captured; tool returned {result!r}"
        payload = captured[-1]
        assert payload.get("description"), (
            f"'description' dropped from the progress payload — REQ-2 AC4 "
            f"requires it retained as the back-compat fallback for consumers "
            f"that predate the structured `detail` field: {payload}"
        )
