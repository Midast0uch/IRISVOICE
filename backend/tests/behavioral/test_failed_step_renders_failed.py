"""Behavioral test for T3.4: a failed step renders as "fail" (REQ-1 AC5).

When tool:error is emitted for a step, the frontend derives the step status
as "fail" and renders it with the fail visual style (red dot). This test
verifies the event chain produces the correct fail signal.
"""

from __future__ import annotations

import pytest

from backend.agent.event_bus import EventBus, IRISStreamEvent


class TestFailedStepRendersFailed:
    """Verifies a step that receives tool:error is marked as fail."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.bus = EventBus()
        self.events: list[dict] = []

        def collector(payload):
            self.events.append(payload.data)

        for ev in (
            IRISStreamEvent.TASK_START,
            IRISStreamEvent.TOOL_CALL,
            IRISStreamEvent.TOOL_ERROR,
            IRISStreamEvent.TOOL_RESULT,
            IRISStreamEvent.TASK_PROGRESS,
        ):
            self.bus.subscribe(ev, collector)

    def _emit(self, event: IRISStreamEvent, data: dict):
        self.bus.emit(event, data=data, session_id="test")

    def test_tool_error_produces_fail_status(self):
        """task:start → tool:call → tool:error — step renders as fail."""
        self._emit(IRISStreamEvent.TASK_START, {
            "task_id": "t1",
            "description": "Try to fetch",
            "steps": [
                {"id": "s1", "description": "Fetch URL", "status": "pending"},
            ],
            "total_steps": 1,
        })
        self._emit(IRISStreamEvent.TOOL_CALL, {
            "step_number": 1,
            "tool_name": "crawler_query",
            "task_id": "t1",
        })
        self._emit(IRISStreamEvent.TOOL_ERROR, {
            "step_number": 1,
            "error": "Connection timeout",
            "task_id": "t1",
        })

        # The tool:error event must carry the step_number so the frontend can
        # match it to the step and set status to fail.
        tool_errors = [e for e in self.events if "error" in e]
        assert len(tool_errors) >= 1
        assert tool_errors[0].get("step_number") == 1
        assert "error" in tool_errors[0]

    def test_tool_error_with_step_done_progress(self):
        """task:progress with step_done and success=false also indicates failure."""
        self._emit(IRISStreamEvent.TASK_START, {
            "task_id": "t2",
            "description": "Process data",
            "steps": [
                {"id": "der-1", "description": "Analyze", "status": "pending"},
            ],
            "total_steps": 1,
        })
        self._emit(IRISStreamEvent.TOOL_CALL, {
            "step_number": 1,
            "tool_name": "process",
            "task_id": "t2",
        })
        self._emit(IRISStreamEvent.TASK_PROGRESS, {
            "step_done": True,
            "step_number": 1,
            "success": False,
            "task_id": "t2",
        })

        # The task:progress event carries the failure signal.
        step_done_events = [
            e for e in self.events
            if e.get("step_done") and e.get("success") is False
        ]
        assert len(step_done_events) >= 1

    def test_tool_error_does_not_affect_other_steps(self):
        """A failure in step 1 does not propagate to step 2."""
        self._emit(IRISStreamEvent.TASK_START, {
            "task_id": "t3",
            "description": "Two-step job",
            "steps": [
                {"id": "s1", "description": "Step one", "status": "pending"},
                {"id": "s2", "description": "Step two", "status": "pending"},
            ],
            "total_steps": 2,
        })
        self._emit(IRISStreamEvent.TOOL_CALL, {
            "step_number": 1,
            "tool_name": "tool_a",
            "task_id": "t3",
        })
        self._emit(IRISStreamEvent.TOOL_ERROR, {
            "step_number": 1,
            "error": "Failed",
            "task_id": "t3",
        })
        # Step 2 still works normally.
        self._emit(IRISStreamEvent.TOOL_CALL, {
            "step_number": 2,
            "tool_name": "tool_b",
            "task_id": "t3",
        })
        self._emit(IRISStreamEvent.TOOL_RESULT, {
            "step_number": 2,
            "result_summary": "Step two done",
            "task_id": "t3",
        })

        tool_errors = [e for e in self.events if "error" in e]
        assert len(tool_errors) == 1
        assert tool_errors[0].get("step_number") == 1
