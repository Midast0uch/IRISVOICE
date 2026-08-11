"""Contract tests: the four Phase 4.1 plan:* events are bridged to the WS.

Each event emitted on the EventBus must arrive at the WebSocket with the
correct `type` string and payload, so the frontend (useIRISWebSocket ->
iris:plan_event -> chat-view system message) can surface it.
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from backend.agent.event_bus import get_event_bus, IRISStreamEvent
from backend.agent.ws_event_bridge import WSEventBridge, _BRIDGED_EVENTS


@pytest.fixture
def bus():
    return get_event_bus()


def _make_bridge():
    ws = MagicMock()
    bridge = WSEventBridge(ws)
    captured = []

    def fake_run(coro, loop):
        captured.append(coro)
        return MagicMock()

    with patch(
        "backend.agent.ws_event_bridge.asyncio.run_coroutine_threadsafe", fake_run
    ):
        bridge.set_main_loop(asyncio.new_event_loop())
        bridge.start()
    return bridge, ws, captured


def _drain(captured):
    for coro in captured:
        asyncio.run(coro)


def test_all_four_plan_events_are_bridged():
    expected = {
        IRISStreamEvent.BUDGET_EXHAUSTED,
        IRISStreamEvent.VALIDATION_FAILED,
        IRISStreamEvent.RECOVERY_START,
        IRISStreamEvent.TOPOLOGY_RECOVERY,
    }
    assert expected.issubset(set(_BRIDGED_EVENTS))


@pytest.mark.parametrize(
    "event,ws_type",
    [
        (IRISStreamEvent.VALIDATION_FAILED, "plan:validation_failed"),
        (IRISStreamEvent.RECOVERY_START, "plan:recovery_start"),
        (IRISStreamEvent.TOPOLOGY_RECOVERY, "plan:topology_recovery"),
        (IRISStreamEvent.BUDGET_EXHAUSTED, "plan:budget_exhausted"),
    ],
)
def test_plan_event_forwarded_to_session(bus, event, ws_type):
    bridge, ws, captured = _make_bridge()
    try:
        bus.emit(
            event,
            data={"detail": "x"},
            turn_id="turn-1",
            conversation_id="c1",
            session_id="s1",
        )
        _drain(captured)
        assert ws.broadcast_to_session.called
        msg = ws.broadcast_to_session.call_args[0][1]
        assert msg["type"] == ws_type
        # CT-3 (REQ-6 AC3/AC5): the bridge injects conversation_id into the
        # bridged payload (so the frontend can drop stale events from a
        # cancelled thread). Original detail is preserved alongside it.
        assert msg["payload"]["detail"] == "x"
        assert msg["payload"].get("conversation_id") == "c1"
        assert ws.broadcast_to_session.call_args[0][0] == "s1"
    finally:
        bridge.stop()
