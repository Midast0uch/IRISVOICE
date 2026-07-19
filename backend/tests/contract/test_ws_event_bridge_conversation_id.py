"""
Contract test CT-3 (REQ-6 AC3/AC5): WSEventBridge injects conversation_id into the
bridged event payload so the frontend can drop stale events from a cancelled thread.

The bridge keeps session-scoped routing (single-session widget) but surfaces
conversation_id on the wire from the EventPayload.
"""
import asyncio
import sys

from types import SimpleNamespace

import pytest

try:
    from backend.agent.ws_event_bridge import WSEventBridge, IRISStreamEvent  # noqa: E402
except ImportError:
    sys.path.insert(0, "..")
    from backend.agent.ws_event_bridge import WSEventBridge, IRISStreamEvent  # noqa: E402


class _CaptureWS:
    def __init__(self):
        self.broadcasts = []

    async def broadcast_to_session(self, session_id, msg):
        self.broadcasts.append((session_id, msg))

    async def broadcast(self, msg):
        self.broadcasts.append((None, msg))


def test_ct3_bridge_injects_conversation_id():
    """A TOOL_RESULT payload without conversation_id gets it from the EventPayload."""
    import asyncio as _asyncio

    ws = _CaptureWS()
    bridge = WSEventBridge(ws)
    loop = _asyncio.new_event_loop()
    bridge.set_main_loop(loop)

    # EventPayload-like object: session_id + conversation_id, data without conv id.
    payload = SimpleNamespace(
        session_id="session_iris",
        conversation_id="thread_A",
        data={"tool_name": "web_search", "result": "ok"},
        turn_id="t1",
    )
    handler = bridge._make_handler(IRISStreamEvent.TOOL_RESULT)
    handler(payload)

    # Give the scheduled coroutine a moment to run on the captured loop.
    loop.run_until_complete(_asyncio.sleep(0.01))
    loop.close()

    assert ws.broadcasts, "expected a broadcast"
    _, msg = ws.broadcasts[0]
    assert msg["type"] == "tool:result"
    assert msg["payload"]["conversation_id"] == "thread_A", (
        "bridge must surface conversation_id so the frontend can drop stale events"
    )
    assert msg["payload"]["tool_name"] == "web_search"
