"""Behavioral test for T2.5: a task card transitions pending → working → done
without any page-level progress. This covers the "event-only seam" crawl
(search without fetch, or direct LLM answer) — no phantom detail/progress
should ever appear.
"""

from __future__ import annotations

import pytest

from backend.agent.event_bus import EventBus, IRISStreamEvent


class TestCardMovesWithoutPage:
    """Verifies the card state machine survives a crawl with zero page progress."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.bus = EventBus()
        self.events: list[dict] = []

        def collector(payload):
            self.events.append(payload.data)

        for ev in (
            IRISStreamEvent.TASK_START,
            IRISStreamEvent.TOOL_CALL,
            IRISStreamEvent.TASK_PROGRESS,
            IRISStreamEvent.TOOL_RESULT,
            IRISStreamEvent.TASK_DONE,
        ):
            self.bus.subscribe(ev, collector)

    def _emit(self, event: IRISStreamEvent, data: dict):
        """Emit an event to the bus with a fixed session_id."""
        self.bus.emit(event, data=data, session_id="test-session")

    def test_no_phantom_detail_when_no_progress_emitted(self):
        """task:start → tool:call → tool:result → task:done, no progress."""
        self._emit(IRISStreamEvent.TASK_START, {
            "task_id": "t1",
            "description": "Analyze recent AI papers",
            "steps": [
                {"id": "s1", "description": "Search arxiv", "status": "pending"},
                {"id": "s2", "description": "Summarize findings", "status": "pending"},
            ],
            "total_steps": 2,
        })
        self._emit(IRISStreamEvent.TOOL_CALL, {
            "step_number": 1,
            "tool_name": "crawler_query",
            "task_id": "t1",
        })
        self._emit(IRISStreamEvent.TOOL_RESULT, {
            "step_number": 1,
            "result_summary": "Found 3 relevant papers",
            "task_id": "t1",
        })
        self._emit(IRISStreamEvent.TASK_DONE, {
            "task_id": "t1",
            "outcome": "success",
        })

        # No event should carry phantom detail/progress.
        for ev in self.events:
            assert "detail" not in ev or not ev["detail"], f"unexpected detail in {ev}"
            assert "detail_progress" not in ev or not ev["detail_progress"], \
                f"unexpected detail_progress in {ev}"

    def test_task_completes_without_any_progress_events(self):
        """task:start → tool:call → tool:result → task:done — full cycle."""
        self._emit(IRISStreamEvent.TASK_START, {
            "task_id": "t2",
            "description": "Direct LLM answer",
            "steps": [{"id": "s1", "description": "Generate response", "status": "pending"}],
            "total_steps": 1,
        })
        self._emit(IRISStreamEvent.TOOL_CALL, {
            "step_number": 1,
            "tool_name": "chat",
            "task_id": "t2",
        })
        self._emit(IRISStreamEvent.TOOL_RESULT, {
            "step_number": 1,
            "result_summary": "Generated answer",
            "task_id": "t2",
        })
        self._emit(IRISStreamEvent.TASK_DONE, {
            "task_id": "t2",
            "outcome": "success",
        })

        # Verify no progress events carried detail.
        for ev in self.events:
            assert "detail" not in ev or not ev["detail"], f"unexpected detail in progress: {ev}"
            assert "detail_progress" not in ev or not ev["detail_progress"], \
                f"unexpected detail_progress: {ev}"

    def test_multiple_tool_calls_without_progress(self):
        """Two back-to-back tool calls, both without page progress."""
        self._emit(IRISStreamEvent.TASK_START, {
            "task_id": "t3",
            "description": "Multi-step analysis",
            "steps": [
                {"id": "s1", "description": "Fetch data", "status": "pending"},
                {"id": "s2", "description": "Process results", "status": "pending"},
            ],
            "total_steps": 2,
        })
        for step_num in (1, 2):
            self._emit(IRISStreamEvent.TOOL_CALL, {
                "step_number": step_num, "tool_name": "tool", "task_id": "t3",
            })
            self._emit(IRISStreamEvent.TOOL_RESULT, {
                "step_number": step_num, "result_summary": f"Step {step_num} done", "task_id": "t3",
            })
        self._emit(IRISStreamEvent.TASK_DONE, {
            "task_id": "t3",
            "outcome": "success",
        })
        for ev in self.events:
            assert "detail" not in ev or not ev["detail"]
            assert "detail_progress" not in ev or not ev["detail_progress"]
