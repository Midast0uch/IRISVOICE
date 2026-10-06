"""Contract: the composer's "Stop IRIS" button ends the running turn.

Boundary pinned: a WS frame {type: "stop", payload: {conversation_id}} must
  1. land in the steering inbox (the DER loop reads it at its next step
     boundary and winds down), AND
  2. cancel the text turn running in THAT conversation, so the gateway ends
     the turn with status "cancelled" now (iris_gateway turns CancelledError
     into turn.end "cancelled"; the UI renders "Stopped. IRIS kept what it
     finished."), AND
  3. leave every other task of the client alone: another conversation's turn
     and the unlocked terminal frames keep running.

Before this change the stop frame only reached the inbox. A turn that was not
inside a DER loop (or was blocked inside one step) never stopped.

The WS endpoint is driven for real with a scripted socket; only the gateway
handler is a stand-in, because what is pinned is the routing in main.py.
"""

import asyncio
import logging.handlers

import pytest
from fastapi import WebSocketDisconnect

# backend/core/logging_config.py imports ShareableRotatingFileHandler from
# backend.monitoring.structured_logger, and no committed file defines it, so
# `import backend.main` fails on a clean checkout (found 2026-10-06; every test
# that imports backend.main is affected). Bridge it here only when it is
# missing, so this contract can run; the repo defect is reported separately.
import backend.monitoring.structured_logger as _sl

if not hasattr(_sl, "ShareableRotatingFileHandler"):
    _sl.ShareableRotatingFileHandler = logging.handlers.RotatingFileHandler

import backend.main as main  # noqa: E402
from backend.agent.steering import get_steering_inbox

SESSION = "sess_stop_contract"
CLIENT = "client_stop_contract"


class _ScriptedSocket:
    """Delivers frames one by one; `after_frame[i]` runs after frame i was read."""

    def __init__(self, frames, probes):
        self._frames = list(frames)
        self._probes = probes  # {index: coroutine function} run before reading frame index
        self._i = 0

    async def receive_text(self):
        probe = self._probes.get(self._i)
        if probe is not None:
            await probe()
        if self._i >= len(self._frames):
            raise WebSocketDisconnect()
        frame = self._frames[self._i]
        self._i += 1
        return frame


class _FakeWsManager:
    def __init__(self):
        self.active_connections = {}

    async def connect(self, websocket, client_id, session_id):
        return SESSION

    def mark_liveness(self, client_id):
        pass

    def disconnect(self, client_id):
        pass


def _frame(kind, conversation_id=None, **extra):
    import json

    payload = dict(extra)
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    return json.dumps({"type": kind, "payload": payload})


@pytest.fixture(autouse=True)
def _clean_inbox():
    get_steering_inbox().clear()
    yield
    get_steering_inbox().clear()


def test_stop_cancels_the_turn_of_that_conversation_only(monkeypatch):
    events = {"started": [], "cancelled": [], "terminal": [], "terminal_cancelled": []}
    seen = {}

    async def fake_handle_message(client_id, session_id, message):
        kind = message["type"]
        conv = (message.get("payload") or {}).get("conversation_id")
        if kind == "terminal_input":
            events["terminal"].append("running")
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                events["terminal_cancelled"].append(True)
                raise
            return
        events["started"].append(conv)
        try:
            await asyncio.sleep(30)  # a turn that would run "forever"
        except asyncio.CancelledError:
            events["cancelled"].append(conv)
            raise

    class _Sessions:
        def get_session(self, _sid):
            return None

    monkeypatch.setattr(main, "get_websocket_manager", lambda: _FakeWsManager())
    monkeypatch.setattr(main, "get_session_manager", lambda: _Sessions())
    monkeypatch.setattr(main, "handle_message", fake_handle_message)

    async def settle():
        await asyncio.sleep(0.05)

    async def after_stop():
        # The stop frame was read; give the cancel a moment, then look BEFORE
        # the disconnect cleanup (which cancels everything) runs.
        await asyncio.sleep(0.1)
        seen["cancelled"] = list(events["cancelled"])
        seen["stop_in_inbox"] = get_steering_inbox().pending_channel(SESSION, "stop")
        seen["terminal_cancelled"] = list(events["terminal_cancelled"])

    frames = [
        _frame("terminal_input", None, line="echo hi"),
        _frame("text_message", "conv_a", text="long job"),
        _frame("stop", "conv_a", message_id="stop-1"),
    ]
    # probe index 1: before frame 1 is read (terminal frame dispatched);
    # index 2: before the stop frame is read, the turn must be running;
    # index 3 (= past the last frame): the stop frame was handled.
    probes = {1: settle, 2: settle, 3: after_stop}
    ws = _ScriptedSocket(frames, probes)

    asyncio.run(main.websocket_endpoint(ws, CLIENT, SESSION))

    assert events["started"] == ["conv_a"], "the turn must be running before the stop"
    assert seen["cancelled"] == ["conv_a"], "stop must cancel the running turn (gateway then ends it as cancelled)"
    assert events["terminal"] == ["running"], "the terminal frame must have been dispatched"
    assert seen["terminal_cancelled"] == [], "stop must not cancel unrelated frames of the client"


def test_stop_for_another_conversation_leaves_the_turn_running(monkeypatch):
    events = {"cancelled": []}
    seen = {}

    async def fake_handle_message(client_id, session_id, message):
        conv = (message.get("payload") or {}).get("conversation_id")
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            events["cancelled"].append(conv)
            raise

    class _Sessions:
        def get_session(self, _sid):
            return None

    monkeypatch.setattr(main, "get_websocket_manager", lambda: _FakeWsManager())
    monkeypatch.setattr(main, "get_session_manager", lambda: _Sessions())
    monkeypatch.setattr(main, "handle_message", fake_handle_message)

    async def settle():
        await asyncio.sleep(0.05)

    async def after_stop():
        await asyncio.sleep(0.1)
        seen["cancelled"] = list(events["cancelled"])
        seen["stop_in_inbox"] = get_steering_inbox().pending_channel(SESSION, "stop")

    frames = [
        _frame("text_message", "conv_a", text="long job"),
        _frame("stop", "conv_b", message_id="stop-2"),
    ]
    ws = _ScriptedSocket(frames, {1: settle, 2: after_stop})

    asyncio.run(main.websocket_endpoint(ws, CLIENT, SESSION))

    assert seen["cancelled"] == [], "a stop for conv_b must not cancel conv_a's turn"
    # The stop record still lands for the session (no DER loop is draining it here).
    assert seen["stop_in_inbox"], "stop must reach the steering inbox"


def test_cancel_turn_tasks_counts_only_matching_turn_tasks():
    async def run():
        async def forever():
            await asyncio.sleep(30)

        turn = asyncio.create_task(forever(), name=main._turn_task_name("conv_x"))
        other = asyncio.create_task(forever(), name="not-a-turn")
        main._client_tasks[CLIENT] = {turn, other}
        try:
            assert main.cancel_turn_tasks(CLIENT, "conv_x") == 1
            assert main.cancel_turn_tasks(CLIENT, "conv_y") == 0
            await asyncio.sleep(0)
            assert turn.cancelled()
            assert not other.cancelled()
        finally:
            other.cancel()
            main._client_tasks.pop(CLIENT, None)

    asyncio.run(run())
