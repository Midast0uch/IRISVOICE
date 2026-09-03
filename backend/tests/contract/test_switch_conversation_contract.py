"""
Contract tests for cross-thread conversation switching (specs/session-conversation-switching).

CT-1 (REQ-4): conversation_switched ack carries the correct conversation_id + status.
CT-2 (REQ-1): switch_conversation is routed to _handle_chat (no "Unknown message type").
CT-3 (REQ-8): sync_state re-binds _active_conversation_id and acks current_conversation_id.

These drive the REAL IRISGateway.handle_message with a mocked ws_manager so the routing
decision and ack payload are exercised end-to-end at the interface boundary.
"""
import asyncio
import sys

from unittest.mock import AsyncMock  # noqa: F401  (kept for parity)

import pytest

# Ensure repo root is importable when run from backend/ or repo root.
try:
    from backend.iris_gateway import IRISGateway  # noqa: E402
except ImportError:
    sys.path.insert(0, "..")
    from backend.iris_gateway import IRISGateway  # noqa: E402


class _FakeWSManager:
    """Records messages sent to clients; no real network."""

    def __init__(self):
        self.sent = []
        self.broadcasts = []

    async def send_to_client(self, client_id, msg):
        self.sent.append((client_id, msg))

    async def broadcast_to_session(self, session_id, msg):
        self.broadcasts.append((session_id, msg))

    async def broadcast(self, msg):
        self.broadcasts.append((None, msg))


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


def test_ct1_switch_conversation_ack_payload(loop):
    """REQ-4: ack carries new_conv_id and a valid status (no undefined var)."""
    gw, ws = _make_gateway()
    msg = {
        "type": "switch_conversation",
        "payload": {
            "conversation_id": "thread_B",
            "old_conversation_id": "thread_A",
        },
    }
    loop.run_until_complete(gw.handle_message("iris", msg, session_id="session_iris"))

    acks = [m for (_, m) in ws.sent if m.get("type") == "conversation_switched"]
    assert acks, "expected a conversation_switched ack"
    ack = acks[0]["payload"]
    assert ack["conversation_id"] == "thread_B", "ack must carry the NEW conversation id"
    assert ack["status"] in ("context_saved", "switched"), "status must be a valid enum"
    assert ack["old_conversation_id"] == "thread_A"


def test_ct2_switch_conversation_routed_no_unknown_warning(loop, caplog):
    """REQ-1: switch_conversation reaches _handle_chat; no 'Unknown message type'."""
    import logging

    gw, ws = _make_gateway()
    caplog.set_level(logging.WARNING)
    msg = {
        "type": "switch_conversation",
        "payload": {"conversation_id": "thread_B", "old_conversation_id": "thread_A"},
    }
    loop.run_until_complete(gw.handle_message("iris", msg, session_id="session_iris"))

    unknown = [r for r in caplog.records if "Unknown message type" in r.getMessage()]
    assert not unknown, "switch_conversation must NOT log 'Unknown message type'"
    errors = [m for (_, m) in ws.sent if m.get("type") == "error"]
    assert not errors, "switch_conversation must NOT send an error response"
    # Binding updated to the new thread.
    assert gw._active_conversation_id.get("session_iris") == "thread_B"


def test_ct3_sync_state_rebinds_active_conversation(loop):
    """REQ-8: sync_state sets _active_conversation_id and acks current_conversation_id."""
    gw, ws = _make_gateway()
    # Pre-set a stale binding to simulate a prior thread.
    gw._active_conversation_id["session_iris"] = "thread_A"
    msg = {"type": "sync_state", "payload": {"conversation_id": "thread_B"}}
    loop.run_until_complete(gw.handle_message("iris", msg, session_id="session_iris"))

    assert gw._active_conversation_id.get("session_iris") == "thread_B"
    acks = [m for (_, m) in ws.sent if m.get("type") == "sync_state_ack"]
    assert acks, "expected a sync_state_ack"
    assert acks[0]["payload"]["current_conversation_id"] == "thread_B"


def test_ct4_switch_missing_conversation_id_is_noop(loop):
    """REQ-2 AC3 / REQ-4: missing conversation_id leaves binding unchanged, still acks."""
    gw, ws = _make_gateway()
    gw._active_conversation_id["session_iris"] = "thread_A"
    msg = {"type": "switch_conversation", "payload": {}}
    loop.run_until_complete(gw.handle_message("iris", msg, session_id="session_iris"))

    # Binding unchanged (no crash, no undefined var).
    assert gw._active_conversation_id.get("session_iris") == "thread_A"
    acks = [m for (_, m) in ws.sent if m.get("type") == "conversation_switched"]
    assert acks, "switch with empty id must still ack"
