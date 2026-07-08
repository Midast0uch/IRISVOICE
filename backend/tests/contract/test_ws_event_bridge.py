"""Contract tests for WSEventBridge.

Verifies the bus->WS bridge forwards the right events with the right shape,
routes by session_id, and never double-forwards MODE_CHANGED (delivered
directly by main.py) or breaks on handler errors.
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from backend.agent.event_bus import get_event_bus, IRISStreamEvent
from backend.agent.ws_event_bridge import WSEventBridge


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


def test_task_start_forwarded_to_session(bus):
    bridge, ws, captured = _make_bridge()
    try:
        bus.emit(
            IRISStreamEvent.TASK_START,
            data={"task_id": "t1", "description": "do thing", "mode": "agentic"},
            turn_id="turn-1",
            conversation_id="c1",
            session_id="s1",
        )
        _drain(captured)
        assert ws.broadcast_to_session.called
        msg = ws.broadcast_to_session.call_args[0][1]
        assert msg["type"] == "task:start"
        assert msg["payload"]["task_id"] == "t1"
        assert ws.broadcast_to_session.call_args[0][0] == "s1"
    finally:
        bridge.stop()


def test_tool_result_forwarded(bus):
    bridge, ws, captured = _make_bridge()
    try:
        bus.emit(
            IRISStreamEvent.TOOL_RESULT,
            data={"task_id": "t1", "tool_name": "web_search", "step_number": 2},
            turn_id="turn-1",
            conversation_id="c1",
            session_id="s1",
        )
        _drain(captured)
        assert ws.broadcast_to_session.called
        msg = ws.broadcast_to_session.call_args[0][1]
        assert msg["type"] == "tool:result"
    finally:
        bridge.stop()


def test_mode_changed_not_forwarded(bus):
    bridge, ws, captured = _make_bridge()
    try:
        bus.emit(
            IRISStreamEvent.MODE_CHANGED,
            data={"mode": "agentic"},
            turn_id="turn-1",
            conversation_id="c1",
            session_id="s1",
        )
        _drain(captured)
        # No broadcast call should carry a mode:changed message.
        for call in ws.broadcast_to_session.call_args_list:
            assert call[0][1]["type"] != "mode:changed"
        assert ws.broadcast_to_session.call_count == 0
    finally:
        bridge.stop()


def test_handler_exception_is_swallowed(bus):
    bridge, ws, captured = _make_bridge()
    ws.broadcast_to_session.side_effect = RuntimeError("boom")
    try:
        # Must not raise out of emit().
        bus.emit(
            IRISStreamEvent.TASK_START,
            data={"task_id": "t1"},
            turn_id="turn-1",
            conversation_id="c1",
            session_id="s1",
        )
        _drain(captured)  # draining the coroutine re-raises inside, but the
        # handler already swallowed it at schedule time; drain just runs the
        # (failing) coroutine which is isolated by run_coroutine_threadsafe.
    except Exception as e:
        pytest.fail(f"emit() leaked an exception: {e}")
    finally:
        bridge.stop()


def test_no_session_broadcasts_to_all(bus):
    bridge, ws, captured = _make_bridge()
    try:
        bus.emit(
            IRISStreamEvent.QUESTION_ASK,
            data={"question_id": "q1", "text": "which?"},
            turn_id="turn-1",
            conversation_id="c1",
            session_id="default",
        )
        _drain(captured)
        assert ws.broadcast.called
        assert not ws.broadcast_to_session.called
    finally:
        bridge.stop()
