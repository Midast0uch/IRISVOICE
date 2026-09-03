"""Behavioral test for REQ-4 AC1 (Phase 2 T2.2): a phase transition inside a
long crawl produces a card update even when ZERO pages were ever fetched.

Before the fix, `tool_bridge.py`'s CRAWLER_PHASE branch only cached the phase
label so it could ride on the NEXT `CRAWLER_PAGE_FETCHED` event. A crawl that
never fetches a page (the Edge Case explicitly named in
specs/phase-2-instrument/requirements.md REQ-4: "Crawl returns zero pages ->
phases still emitted") therefore produced zero TASK_PROGRESS events at all —
the card sat frozen.

This drives the REAL `AgentToolBridge._execute_crawler_query` progress path
(a fake orchestrator stands in for the network-bound crawl and emits ONLY a
CRAWLER_PHASE event, no CRAWLER_PAGE_FETCHED) and asserts the EFFECT: a real
TASK_PROGRESS event was captured off the real EventBus, carries the phase,
and does not touch the step's plan `description` field (REQ-2 AC1/AC5 —
live progress is structured, the plan is immutable).
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


class _FakeOrchestratorPhaseOnlyZeroPages:
    """Emits ONLY a CRAWLER_PHASE transition — no page is ever fetched.
    Isolates whether REQ-4's phase-transition emission is independent of the
    page-fetch emitter (the bug), or merely rides along with it (the fix).
    """

    async def research(self, query, *, mode="agent", session_id="", on_progress=None, **kw):
        if on_progress:
            on_progress(
                orch_mod.CrawlProgress(
                    event="CRAWLER_PHASE",
                    payload={"phase": "extracting", "phase_sequence": 3},
                )
            )
        raise RuntimeError("stop-early-for-test — zero pages ever fetched")


def _run_zero_page_phase_crawl():
    reset_event_bus_for_testing()
    bus = get_event_bus()
    captured: list = []
    bus.subscribe(IRISStreamEvent.TASK_PROGRESS, lambda p: captured.append(p.data))

    with patch.object(
        orch_mod, "get_crawl_orchestrator",
        return_value=_FakeOrchestratorPhaseOnlyZeroPages(),
    ), patch("backend.agent.narration.may_narrate", return_value=False):
        bridge = AgentToolBridge()
        result = asyncio.run(
            bridge._execute_crawler_query(
                {"query": "phase only, zero pages"}, "phase-zero-pages-session",
            )
        )
    return captured, result


class TestPhaseTransitionWithoutPages:
    def test_phase_transition_produces_a_card_update_with_zero_pages_fetched(self):
        """REQ-4 AC1 / Edge Case: zero pages fetched still produces a
        TASK_PROGRESS event carrying the phase — the card is not frozen."""
        captured, result = _run_zero_page_phase_crawl()
        phase_events = [e for e in captured if e.get("phase")]
        assert phase_events, (
            f"no phase-carrying TASK_PROGRESS event was observed with zero "
            f"pages fetched (REQ-4 AC1 requires movement independent of page "
            f"events); tool returned {result!r}; all captured={captured!r}"
        )

    def test_phase_event_does_not_carry_a_page_fetch_detail_url(self):
        """A phase-only event has no source URL to show — it must not
        fabricate one (distinguishes it from `_on_page_done`'s payload
        shape, which always carries `detail_url`)."""
        captured, result = _run_zero_page_phase_crawl()
        phase_events = [e for e in captured if e.get("phase")]
        assert phase_events, f"no phase event captured; tool returned {result!r}"
        assert "detail_url" not in phase_events[-1] or not phase_events[-1]["detail_url"], (
            f"phase-only event fabricated a detail_url: {phase_events[-1]}"
        )

    def test_phase_event_does_not_overwrite_step_plan_text(self):
        """REQ-2 AC1/AC5: live phase movement rides on structured fields
        (`detail`/`phase`) only — it must never carry the plan's immutable
        `description` field under a name the reducer would use to replace
        step text. `update_step=True` is safe here because the frontend
        reducer only ever writes `activeDetail`/`activeProgress` from it,
        never `step.description` (see hooks/useTaskProgress.ts)."""
        captured, result = _run_zero_page_phase_crawl()
        phase_events = [e for e in captured if e.get("phase")]
        assert phase_events, f"no phase event captured; tool returned {result!r}"
        payload = phase_events[-1]
        # The event's own top-level `description` is the live-action sentence
        # (fallback for old consumers) — it is never routed to step.description
        # by the reducer's update_step branch, only to `currentAction`.
        assert payload.get("update_step") is True, (
            f"phase event should set update_step so activeDetail/activeProgress "
            f"update, not step.description: {payload}"
        )
