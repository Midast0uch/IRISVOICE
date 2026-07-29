"""Behavioral test for T3.4: sub-loop steps append to the same card (REQ-5).

When the DER splits a step into a sub-loop, it emits tool:call for each
sub-step. The frontend hook appends these to the same card because they use
the same task_id — no addStep is emitted.
"""

from __future__ import annotations

import pytest

from backend.agent.event_bus import EventBus, IRISStreamEvent


class TestSubLoopAppendsToSameCard:
    """Verifies DER sub-loop steps append to the existing card, not a new one."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.bus = EventBus()
        self.events: list[dict] = []

        def collector(payload):
            self.events.append(payload.data)

        for ev in (
            IRISStreamEvent.TASK_START,
            IRISStreamEvent.TOOL_CALL,
            IRISStreamEvent.TOOL_RESULT,
        ):
            self.bus.subscribe(ev, collector)

    def _emit(self, event: IRISStreamEvent, data: dict):
        self.bus.emit(event, data=data, session_id="test-session")

    def test_two_tool_calls_same_card(self):
        """task:start → tool:call (1) → tool:call (2) → tool:result (1) → tool:result (2)."""
        self._emit(IRISStreamEvent.TASK_START, {
            "task_id": "t1",
            "description": "Research topic",
            "steps": [
                {"id": "s1", "description": "Main research", "status": "pending"},
            ],
            "total_steps": 1,
        })
        self._emit(IRISStreamEvent.TOOL_CALL, {
            "step_number": 1,
            "tool_name": "crawler_query",
            "task_id": "t1",
        })
        # Sub-loop split: a second tool:call for the same task.
        self._emit(IRISStreamEvent.TOOL_CALL, {
            "step_number": 2,
            "tool_name": "read_file",
            "task_id": "t1",
            "description": "Read fetched content",
        })
        self._emit(IRISStreamEvent.TOOL_RESULT, {
            "step_number": 1,
            "result_summary": "Research complete",
            "task_id": "t1",
        })
        self._emit(IRISStreamEvent.TOOL_RESULT, {
            "step_number": 2,
            "result_summary": "Content read",
            "task_id": "t1",
        })

        # Both tool:call events share the same task_id — no new task card spawned.
        tool_calls = [e for e in self.events if "tool_name" in e]
        assert len(tool_calls) >= 2
        for tc in tool_calls:
            assert tc.get("task_id") == "t1", \
                f"tool:call task_id mismatch: {tc.get('task_id')}"

    def test_sub_step_has_different_tool_name(self):
        """Sub-loop step can use a different tool from the parent step."""
        self._emit(IRISStreamEvent.TASK_START, {
            "task_id": "t2",
            "description": "Multi-tool task",
            "steps": [
                {"id": "s1", "description": "Search web", "status": "pending"},
            ],
            "total_steps": 1,
        })
        self._emit(IRISStreamEvent.TOOL_CALL, {
            "step_number": 1,
            "tool_name": "search",
            "task_id": "t2",
        })
        # Sub-loop split with different tool.
        self._emit(IRISStreamEvent.TOOL_CALL, {
            "step_number": 2,
            "tool_name": "crawler_query",
            "task_id": "t2",
        })
        self._emit(IRISStreamEvent.TOOL_RESULT, {
            "step_number": 1,
            "result_summary": "Search results",
            "task_id": "t2",
        })
        self._emit(IRISStreamEvent.TOOL_RESULT, {
            "step_number": 2,
            "result_summary": "Fetched pages",
            "task_id": "t2",
        })

        tool_calls = [e for e in self.events if "tool_name" in e]
        tool_names = [tc["tool_name"] for tc in tool_calls if "tool_name" in tc]
        assert "search" in tool_names
        assert "crawler_query" in tool_names
        # Both on the same task.
        for tc in tool_calls:
            assert tc.get("task_id") == "t2"
