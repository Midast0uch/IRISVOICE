"""
Behavioral tests for cross-thread cancellation (specs/session-conversation-switching).

BT-3 (REQ-6): switching mid-work sets the OLD thread's _cancel_requested flag.
BT-4 (REQ-8): sync_state re-bind to a different thread cancels the previously-active one.
BT-5 (REQ-8 AC5): ws_manager reconnect-replacement cancels the active thread's in-flight work.

These drive the REAL gateway cancel logic (no full DER run needed — the flag is the
contract; the DER loop polls it at step boundaries, verified separately in agent_kernel).
"""
import asyncio
import sys

import pytest

try:
    from backend.iris_gateway import IRISGateway  # noqa: E402
    from backend.agent.agent_kernel import get_agent_kernel  # noqa: E402
except ImportError:
    sys.path.insert(0, "..")
    from backend.iris_gateway import IRISGateway  # noqa: E402
    from backend.agent.agent_kernel import get_agent_kernel  # noqa: E402


class _FakeWSManager:
    def __init__(self):
        self.sent = []

    async def send_to_client(self, client_id, msg):
        self.sent.append((client_id, msg))

    async def broadcast_to_session(self, session_id, msg):
        pass

    async def broadcast(self, msg):
        pass


def _make_gateway():
    ws = _FakeWSManager()
    gw = IRISGateway(ws_manager=ws)
    gw._main_loop = asyncio.new_event_loop()
    return gw, ws


@pytest.fixture
def loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def test_bt3_switch_sets_old_thread_cancel_flag(loop):
    """REQ-6 AC1/AC2: switching A->B sets A's _cancel_requested, not B's."""
    gw, ws = _make_gateway()
    sid = "session_iris"
    # Materialize both kernels so the flag exists; clear (singletons across tests).
    kA = get_agent_kernel("thread_A", sid)
    kB = get_agent_kernel("thread_B", sid)
    kA._cancel_requested.clear()
    kB._cancel_requested.clear()
    gw._active_conversation_id[sid] = "thread_A"

    msg = {
        "type": "switch_conversation",
        "payload": {"conversation_id": "thread_B", "old_conversation_id": "thread_A"},
    }
    loop.run_until_complete(gw.handle_message("iris", msg, session_id=sid))

    assert kA._cancel_requested.is_set(), "old thread A must be cancelled"
    assert not kB._cancel_requested.is_set(), "new thread B must NOT be cancelled"
    assert gw._active_conversation_id[sid] == "thread_B"


def test_bt4_sync_state_rebind_cancels_old_thread(loop):
    """REQ-8 AC3: sync_state re-bind A->B cancels A's in-flight work."""
    gw, ws = _make_gateway()
    sid = "session_iris"
    kA = get_agent_kernel("thread_A", sid)
    kA._cancel_requested.clear()
    gw._active_conversation_id[sid] = "thread_A"

    msg = {"type": "sync_state", "payload": {"conversation_id": "thread_B"}}
    loop.run_until_complete(gw.handle_message("iris", msg, session_id=sid))

    assert gw._active_conversation_id[sid] == "thread_B"
    assert kA._cancel_requested.is_set(), "previously-active A must be cancelled on re-bind"


def test_bt5_client_replace_cancels_active_thread(loop):
    """REQ-8 AC5: ws_manager reconnect-replacement cancels the active thread's loop."""
    gw, ws = _make_gateway()
    sid = "session_iris"
    kA = get_agent_kernel("thread_A", sid)
    kA._cancel_requested.clear()
    gw._active_conversation_id[sid] = "thread_A"

    # Simulate the ws_manager hook firing on reconnect-replacement.
    gw._on_client_replace("iris")

    assert kA._cancel_requested.is_set(), "active thread must be cancelled on client replace"


def test_bt6_switch_same_thread_no_cancel(loop):
    """REQ-6 AC3: switching to the SAME thread does not cancel it."""
    gw, ws = _make_gateway()
    sid = "session_iris"
    # Unique id + reset flag (kernels are singletons across tests).
    kA = get_agent_kernel("thread_same_1", sid)
    kA._cancel_requested.clear()
    gw._active_conversation_id[sid] = "thread_same_1"

    msg = {
        "type": "switch_conversation",
        "payload": {
            "conversation_id": "thread_same_1",
            "old_conversation_id": "thread_same_1",
        },
    }
    loop.run_until_complete(gw.handle_message("iris", msg, session_id=sid))

    assert not kA._cancel_requested.is_set(), "same-thread switch must NOT cancel"
