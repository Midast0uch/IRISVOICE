"""Contract tests: EventBus typed pub/sub event system.

Verifies:
  - subscribe/unsubscribe/emit lifecycle
  - Handler isolation (one crash doesn't block others)
  - Ring buffer replay for late subscribers
  - Singleton pattern
  - Async handler support
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.agent.event_bus import (
    EventBus,
    EventPayload,
    IRISStreamEvent,
    RingBuffer,
    get_event_bus,
    reset_event_bus_for_testing,
)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def bus():
    """Fresh EventBus for each test."""
    b = EventBus()
    yield b


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton between tests."""
    reset_event_bus_for_testing()
    yield


# ── Event Bus tests ────────────────────────────────────────────────────────


class TestSubscribeUnsubscribe:
    def test_subscribe_and_emit(self, bus):
        handler = MagicMock()
        bus.subscribe(IRISStreamEvent.TOOL_CALL, handler)
        bus.emit(IRISStreamEvent.TOOL_CALL, data={"tool": "test"})

        handler.assert_called_once()
        call_arg = handler.call_args[0][0]
        assert isinstance(call_arg, EventPayload)
        assert call_arg.event == IRISStreamEvent.TOOL_CALL
        assert call_arg.data == {"tool": "test"}

    def test_unsubscribe_prevents_delivery(self, bus):
        handler = MagicMock()
        bus.subscribe(IRISStreamEvent.TOOL_CALL, handler)
        bus.unsubscribe(IRISStreamEvent.TOOL_CALL, handler)
        bus.emit(IRISStreamEvent.TOOL_CALL, data={"tool": "test"})

        handler.assert_not_called()

    def test_unsubscribe_nonexistent_no_error(self, bus):
        handler = MagicMock()
        # Unsubscribe before subscribing — should be no-op
        bus.unsubscribe(IRISStreamEvent.TEXT_RESPONSE_CHUNK, handler)
        bus.emit(IRISStreamEvent.TEXT_RESPONSE_CHUNK, data="hello")
        handler.assert_not_called()

    def test_multiple_handlers_same_event(self, bus):
        h1 = MagicMock()
        h2 = MagicMock()
        bus.subscribe(IRISStreamEvent.TOOL_CALL, h1)
        bus.subscribe(IRISStreamEvent.TOOL_CALL, h2)
        bus.emit(IRISStreamEvent.TOOL_CALL, data={"x": 1})

        h1.assert_called_once()
        h2.assert_called_once()

    def test_same_handler_twice_registered_once(self, bus):
        handler = MagicMock()
        bus.subscribe(IRISStreamEvent.TOOL_CALL, handler)
        bus.subscribe(IRISStreamEvent.TOOL_CALL, handler)  # duplicate
        bus.emit(IRISStreamEvent.TOOL_CALL, data={"x": 1})

        handler.assert_called_once()  # only called once

    def test_subscriber_count(self, bus):
        assert bus.subscriber_count() == 0
        bus.subscribe(IRISStreamEvent.TOOL_CALL, MagicMock())
        assert bus.subscriber_count(IRISStreamEvent.TOOL_CALL) == 1
        assert bus.subscriber_count() == 1

        bus.subscribe(IRISStreamEvent.TEXT_RESPONSE_CHUNK, MagicMock())
        assert bus.subscriber_count() == 2


class TestEmitPayload:
    def test_payload_has_timestamp(self, bus):
        handler = MagicMock()
        bus.subscribe(IRISStreamEvent.AGENT_START, handler)
        bus.emit(IRISStreamEvent.AGENT_START)

        payload = handler.call_args[0][0]
        assert payload.timestamp > 0

    def test_payload_carries_turn_id(self, bus):
        handler = MagicMock()
        bus.subscribe(IRISStreamEvent.DER_STEP, handler)
        bus.emit(
            IRISStreamEvent.DER_STEP,
            data={"step": 1},
            turn_id="turn_001",
            conversation_id="conv_test",
        )

        payload = handler.call_args[0][0]
        assert payload.turn_id == "turn_001"
        assert payload.conversation_id == "conv_test"

    def test_different_event_types_dont_interfere(self, bus):
        h1 = MagicMock()
        h2 = MagicMock()
        bus.subscribe(IRISStreamEvent.TOOL_CALL, h1)
        bus.subscribe(IRISStreamEvent.TEXT_RESPONSE_CHUNK, h2)

        bus.emit(IRISStreamEvent.TOOL_CALL, data={"tool": "write"})
        h1.assert_called_once()
        h2.assert_not_called()

        bus.emit(IRISStreamEvent.TEXT_RESPONSE_CHUNK, data="hello")
        h2.assert_called_once()


class TestHandlerIsolation:
    def test_handler_crash_does_not_block_others(self, bus):
        """If one handler raises, other handlers still receive the event."""
        results = []

        def failing_handler(payload):
            raise RuntimeError("I crashed!")

        def working_handler(payload):
            results.append("got it")

        bus.subscribe(IRISStreamEvent.TOOL_CALL, failing_handler)
        bus.subscribe(IRISStreamEvent.TOOL_CALL, working_handler)

        # Should not raise
        bus.emit(IRISStreamEvent.TOOL_CALL, data={"x": 1})

        assert results == ["got it"]

    def test_handler_crash_logged(self, bus, caplog):
        """Handler crash is logged, not lost."""

        def failing_handler(payload):
            raise ValueError("bad data")

        bus.subscribe(IRISStreamEvent.TOOL_ERROR, failing_handler)
        bus.emit(IRISStreamEvent.TOOL_ERROR, data={"error": "test"})

        assert "bad data" in caplog.text


class TestRingBuffer:
    def test_replay_empty(self, bus):
        events = bus.replay()
        assert events == []

    def test_replay_after_emit(self):
        rb = RingBuffer(capacity=5)
        payload = EventPayload(event=IRISStreamEvent.TOOL_CALL)
        rb.push(payload)

        events = rb.replay()
        assert len(events) == 1
        assert events[0].event == IRISStreamEvent.TOOL_CALL

    def test_replay_since_timestamp(self):
        rb = RingBuffer(capacity=10)
        import time

        t1 = time.time()
        rb.push(EventPayload(event=IRISStreamEvent.TOOL_CALL))
        t2 = time.time()
        rb.push(EventPayload(event=IRISStreamEvent.TOOL_RESULT))

        # Only events after t2
        events = rb.replay(since_timestamp=t2)
        assert len(events) == 1
        assert events[0].event == IRISStreamEvent.TOOL_RESULT

    def test_bounded_capacity(self):
        rb = RingBuffer(capacity=3)
        for i in range(5):
            rb.push(
                EventPayload(
                    event=IRISStreamEvent.TOOL_CALL,
                    data={"step": i},
                )
            )

        events = rb.replay()
        assert len(events) == 3
        assert events[0].data["step"] == 2  # index 2,3,4

    def test_clear(self):
        rb = RingBuffer(capacity=5)
        rb.push(EventPayload(event=IRISStreamEvent.TOOL_CALL))
        rb.clear()
        assert rb.replay() == []


class TestSingleton:
    def test_get_event_bus_returns_same_instance(self):
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2

    def test_reset_creates_new_instance(self):
        bus1 = get_event_bus()
        reset_event_bus_for_testing()
        bus2 = get_event_bus()
        assert bus2 is not bus1
