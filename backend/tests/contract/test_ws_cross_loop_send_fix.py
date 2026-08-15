"""Anti-drift contract for the cross-loop WS send fix (pin_8b41f386d397).

Live failure 2026-08-12: a websearch turn froze at "Loading 0/2" forever
because three defects chained:

  1. `tool_decision._run_async` runs crawler_query on a WORKER event loop
     (`run_coroutine_threadsafe(coro, asyncio.new_event_loop())`).
  2. `tool_bridge._crawl_ui_emitter._send` used `ensure_future` — scheduling
     the WS broadcast on that worker loop — so `send_to_client` did
     `async with _send_locks[client]` on a lock bound to the MAIN loop and
     raised "bound to a different event loop"; `send_to_client` then
     DISCONNECTED the live client.
  3. The turn's final chat_message send failed (no client) and
     `buffer_message` DID NOT EXIST on WebSocketManager -> AttributeError ->
     the answer was never delivered.

These tests pin the three fixes so the chain cannot silently return:
  A. the crawler UI emitter marshals onto the gateway's MAIN loop
     (run_coroutine_threadsafe), never `ensure_future` on the current loop;
  B. per-client send locks are keyed by (client_id, event loop) so a send
     from a worker loop can never be cross-loop-blocked (and never evicts
     the client on a lock error);
  C. buffer_message buffers and flush_pending replays a message that could
     not be delivered (so the final chat_message survives a mid-turn
     disconnect).
"""

from __future__ import annotations

import asyncio
import threading
from collections import deque

import pytest

from backend.ws_manager import WebSocketManager


class _FakeSocket:
    """Minimal websocket stand-in recording send_json calls."""

    def __init__(self):
        self.sent: list = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


class _FakeSessionManager:
    def __init__(self):
        self._clients: dict = {}

    def dissociate_client(self, client_id):
        self._clients.pop(client_id, None)

    def get_session(self, session_id):
        return object()  # any truthy object — session "exists"


@pytest.fixture
def loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _make_manager(loop) -> WebSocketManager:
    m = WebSocketManager.__new__(WebSocketManager)
    m.active_connections = {}
    m._send_locks = {}
    m._pending = {}
    m._heartbeat_tasks = {}
    m._last_pong = {}
    m._last_activity = {}
    m._session_manager = _FakeSessionManager()
    return m


class TestCrawlUiEmitterUsesMainLoop:
    def test_emitter_send_marshals_to_main_loop_not_current_loop(self, loop, monkeypatch):
        """The crawl UI emitter must schedule the broadcast on the gateway's
        MAIN loop via run_coroutine_threadsafe — never ensure_future on the
        loop running in the calling (possibly worker) thread."""
        import backend.agent.tool_bridge as tb

        calls = {"threadsafe": 0, "ensure_future": 0}

        # Instrument the two scheduling primitives the emitter could use.
        real_threadsafe = asyncio.run_coroutine_threadsafe

        def _fake_threadsafe(coro, target_loop):
            calls["threadsafe"] += 1
            assert target_loop is loop, (
                "crawl UI events must be marshalled to the MAIN loop, got "
                f"{target_loop!r}"
            )
            return real_threadsafe(coro, target_loop)

        def _fake_ensure_future(coro, *a, **k):
            calls["ensure_future"] += 1
            raise AssertionError(
                "ensure_future must NOT be used for crawl UI sends — it binds "
                "to the current thread's loop, which is the worker loop during "
                "a crawl (pin_8b41f386d397)"
            )

        monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", _fake_threadsafe)
        monkeypatch.setattr(asyncio, "ensure_future", _fake_ensure_future)

        # The main loop must be running for run_coroutine_threadsafe to work.
        async def _drive():
            # Build the emitter and grab its _send via a fake progress event.
            session_id = "session_iris"
            emit = tb._crawl_ui_emitter(session_id)

            # A real gateway with a live main loop is heavy; patch get_iris_gateway.
            class _FakeGW:
                _main_loop = loop

            monkeypatch.setattr(
                "backend.iris_gateway.get_iris_gateway", lambda: _FakeGW()
            )

            # The ws manager must report the session as having a client, else
            # the emitter returns before scheduling anything.
            class _FakeWS:
                def get_clients_for_session(self, sid):
                    return ["iris"]

                async def broadcast_to_session(self, sid, msg):
                    pass  # runs on the main loop — nothing to assert here

            monkeypatch.setattr(
                "backend.ws_manager.get_websocket_manager", lambda: _FakeWS()
            )

            class _P:
                event = "CRAWLER_PAGE_FETCHED"
                payload = {"url": "https://x", "page_number": 1, "total": 1}

            emit(_P())
            # Give the threadsafe-scheduled coroutine a chance to run.
            await asyncio.sleep(0.1)

        loop.run_until_complete(_drive())
        assert calls["threadsafe"] >= 1, "emitter must marshal via run_coroutine_threadsafe"
        assert calls["ensure_future"] == 0, "emitter must never use ensure_future"


class TestSendLocksAreLoopKeyed:
    def test_send_lock_is_per_client_per_loop(self):
        """Two loops sending to the same client must each get their own lock,
        so a worker-loop send can never hit 'bound to a different event loop'."""
        m = _make_manager(None)

        async def _get(loop_id_holder: dict):
            lock = m._get_send_lock("iris")
            loop_id_holder["loop_id"] = id(asyncio.get_running_loop())
            return lock

        loop_a = asyncio.new_event_loop()
        loop_b = asyncio.new_event_loop()
        try:
            hold_a = {}
            lock_a = loop_a.run_until_complete(_get(hold_a))
            hold_b = {}
            lock_b = loop_b.run_until_complete(_get(hold_b))
            assert lock_a is not lock_b, (
                "different loops must get different locks for the same client"
            )
            assert hold_a["loop_id"] != hold_b["loop_id"]
            # Same loop again -> same lock (serialisation preserved per loop).
            lock_a2 = loop_a.run_until_complete(_get({}))
            assert lock_a2 is lock_a
            assert len(m._send_locks) == 2
        finally:
            loop_a.close()
            loop_b.close()

    def test_send_to_client_does_not_evict_on_cross_loop_lock(self, loop):
        """A send that fails with a cross-loop lock error must NOT disconnect
        the client. Previously send_to_client caught the lock RuntimeError and
        called self.disconnect(), evicting the live client mid-turn."""
        m = _make_manager(loop)
        sock = _FakeSocket()
        m.active_connections["iris"] = sock
        # Prime a lock for 'iris' on ANOTHER loop so the main-loop acquire fails
        # IF the lock were shared. Keys are loop-scoped, so the main loop gets
        # its OWN lock and the send succeeds.
        other = asyncio.new_event_loop()

        async def _prime():
            return m._get_send_lock("iris")

        try:
            # Run _get_send_lock on the other loop (sync method needing a
            # running loop to read id(get_running_loop())).
            other.run_until_complete(_prime())
            sent = loop.run_until_complete(
                m.send_to_client("iris", {"type": "ping", "payload": {}})
            )
            assert sent is True, "loop-scoped lock must allow the send"
            assert sock.sent, "message must reach the socket"
            assert "iris" in m.active_connections, "client must NOT be evicted"
        finally:
            other.close()


class TestBufferAndFlushPending:
    def test_buffer_message_then_flush_pending_replays(self, loop):
        """A message buffered when the client was disconnected must be replayed
        on the next connect via flush_pending (the final chat_message survives
        a mid-turn disconnect)."""
        m = _make_manager(loop)
        sock = _FakeSocket()

        # Client not connected when the message is produced -> buffer it.
        assert "iris" not in m.active_connections
        m.buffer_message("session_iris", {"type": "chat_message", "payload": {"content": "final"}})
        assert "session_iris" in m._pending

        # Client connects -> flush replays.
        m.active_connections["iris"] = sock
        loop.run_until_complete(m.flush_pending("session_iris", "iris"))
        assert sock.sent == [{"type": "chat_message", "payload": {"content": "final"}}]
        assert "session_iris" not in m._pending, "queue must be drained after replay"

    def test_pending_queue_is_bounded(self):
        """buffer_message must bound the queue per session (memory footprint
        bounded — CLAUDE.md quality check), not grow without limit."""
        m = _make_manager(None)
        for i in range(500):
            m.buffer_message("session_iris", {"type": "t", "i": i})
        assert len(m._pending["session_iris"]) <= 200, (
            f"pending queue must be bounded, got {len(m._pending['session_iris'])}"
        )

    def test_disconnect_cleans_up_all_loop_keyed_locks(self, loop):
        """disconnect must remove every (client_id, loop) lock, not just one
        key — else _send_locks leaks a tuple key per loop across reconnects."""
        m = _make_manager(loop)
        m.active_connections["iris"] = _FakeSocket()
        # Simulate locks from two loops.
        m._send_locks[("iris", 1)] = asyncio.Lock()
        m._send_locks[("iris", 2)] = asyncio.Lock()
        m.disconnect("iris")
        assert all(k[0] != "iris" for k in m._send_locks), (
            f"all iris locks must be cleaned up, got {m._send_locks}"
        )
