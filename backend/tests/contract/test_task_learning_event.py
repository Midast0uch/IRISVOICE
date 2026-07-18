"""Contract tests: REQ-8 task:learning event shape (backend -> frontend).

Asserts the DER loop emits a `task:learning` event with the real learning
signal (avoided / retried / crystallized) and the honest step state, and
that the event bus carries it to a subscriber. This pins the boundary BEFORE
the frontend consumes it — a contract break is caught at the interface.

Spec: specs/der-loop-integrity-display/requirements.md REQ-8.
"""

from __future__ import annotations

import types

from backend.agent.event_bus import EventBus, IRISStreamEvent


class _Capture:
    def __init__(self):
        self.events = []

    def on_event(self, payload):
        # EventBus delivers an EventPayload; the detail dict is .data.
        self.events.append(payload.data)


class TestTaskLearningEventContract:
    def test_event_enum_value(self):
        assert IRISStreamEvent.TASK_LEARNING.value == "task:learning"

    def test_emit_carries_signal_and_state(self):
        bus = EventBus()
        cap = _Capture()
        bus.subscribe(IRISStreamEvent.TASK_LEARNING, cap.on_event)
        detail = {
            "session_id": "s1",
            "step_id": "step-3",
            "step_number": 3,
            "signal": "avoided",
            "verified_label": "FAILED",
            "description": "risky thing",
            "is_subloop": False,
        }
        bus.emit(IRISStreamEvent.TASK_LEARNING, detail)
        assert len(cap.events) == 1
        got = cap.events[0]
        # Real state, never narration.
        assert got["signal"] == "avoided"
        assert got["verified_label"] == "FAILED"
        assert got["step_number"] == 3

    def test_three_signals_valid(self):
        bus = EventBus()
        cap = _Capture()
        bus.subscribe(IRISStreamEvent.TASK_LEARNING, cap.on_event)
        for sig in ("avoided", "retried", "crystallized"):
            bus.emit(
                IRISStreamEvent.TASK_LEARNING,
                {"session_id": "s", "step_id": "x", "signal": sig},
            )
        assert len(cap.events) == 3
        _sigs = {e["signal"] for e in cap.events}
        assert _sigs == {"avoided", "retried", "crystallized"}
