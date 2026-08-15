"""
IRIS WebSocket Connection Manager (Session-Aware)
Handles client connections, session association, and message routing.
"""
import json
import logging
import asyncio
from collections import deque
from typing import Dict, List, Set, Optional
from fastapi import WebSocket
from datetime import datetime
import time

logger = logging.getLogger(__name__)

from .sessions import get_session_manager, SessionManager
from .state_manager import get_state_manager, StateManager

# Bounded pending-delivery queue per session (see buffer_message / flush_pending).
_PENDING_MAX = 200


class WebSocketManager:
    """
    Manages WebSocket connections and associates them with IRIS sessions.
    Includes ping/pong heartbeat mechanism to maintain connections.
    """
    
    PING_INTERVAL = 30  # seconds between pings
    PONG_TIMEOUT = 30   # seconds to wait for pong after sending ping
    # PONG_TIMEOUT was previously 5 s, which caused spurious disconnects.
    # During LLM inference + TTS synthesis the asyncio event loop can be
    # backlogged for several seconds, preventing the pong message from being
    # processed before the 5 s window expired.  30 s gives plenty of headroom
    # while still catching genuinely dead connections (which never pong at all).
    
    def __init__(self, session_manager: Optional[SessionManager] = None, state_manager: Optional[StateManager] = None):
        import time
        start_time = time.time()
        logger.info(f"[WebSocketManager] Initializing (start: {start_time:.3f}s)")
        
        self.active_connections: Dict[str, WebSocket] = {}
        # ── ONE SEND AT A TIME PER SOCKET ───────────────────────────────────
        # Starlette WebSockets are NOT safe for concurrent sends: two coroutines
        # awaiting send_json() on the same socket can interleave at the ASGI
        # layer and emit a single frame containing TWO JSON objects. The client
        # then dies on `JSON.parse` with "Unexpected non-whitespace character
        # after JSON at position N" (observed live at position 232,
        # useIRISWebSocket.ts:446) and DROPS THE WHOLE FRAME — including
        # whatever message would have completed the turn.
        #
        # This backend has many concurrent senders by design: streamed
        # chat_chunk / chat_reasoning marshalled from an executor thread via
        # run_coroutine_threadsafe, FIRE-AND-FORGET crawler UI events, listening
        # state broadcasts, tts_word events, narration and the chat heartbeat.
        # Any two overlapping is enough.
        #
        # A per-(client, event-loop) lock serialises them. It is keyed by BOTH
        # client and running loop because asyncio.Lock binds to the loop that
        # first acquires it, and this backend legitimately sends from more than
        # one loop (the crawler tool runs on a worker loop via
        # run_coroutine_threadsafe(coro, asyncio.new_event_loop()) in
        # tool_decision._run_async, while the gateway sends from the main loop).
        # A single lock per client shared across loops raised "bound to a
        # different event loop", which send_to_client treated as a failure and
        # DISCONNECTED the live client mid-turn (live 2026-08-12,
        # pin_8b41f386d397). Keying by loop gives every loop its own lock, so a
        # send can never be cross-loop-blocked; per-client within a loop, a slow
        # socket still cannot block delivery to everyone else.
        self._send_locks: Dict[tuple, asyncio.Lock] = {}
        # Pending undelivered messages per session, replayed by flush_pending
        # on (re)connect (guaranteed delivery; see buffer_message).
        self._pending: Dict[str, deque] = {}
        self._session_manager = session_manager or get_session_manager()
        self._state_manager = state_manager or get_state_manager()
        self._heartbeat_tasks: Dict[str, asyncio.Task] = {}
        self._last_pong: Dict[str, datetime] = {}
        self._last_activity: Dict[str, float] = {}
        # REQ-8 AC5: hook invoked when a stale connection for client_id is replaced
        # by a new socket (reconnect). Set by IRISGateway to soft-cancel the
        # previously-active thread's in-flight work. None-safe.
        self.on_client_replace: Optional[callable] = None
        
        logger.info(f"[WebSocketManager] Initialization complete (elapsed: {time.time() - start_time:.3f}s)")
    
    async def connect(self, websocket: WebSocket, client_id: str, session_id: Optional[str] = None) -> Optional[str]:
        """
        Accept a new WebSocket connection and associate it with a session.
        If session_id is not provided, a new session is created.
        Returns the session_id if successful, None otherwise.
        
        Error Handling:
        - Connection failures: Logged and None returned
        - Session creation failures: Logged and None returned
        - State initialization failures: Logged but connection continues
        """
        import time
        connect_start = time.time()
        logger.info(f"[WebSocketManager] Connecting client {client_id} (start: {connect_start:.3f}s)")
        
        try:
            if client_id in self.active_connections:
                # A new WebSocket arrived for an already-registered client_id.
                # This happens when the frontend reconnects before the backend has
                # cleaned up the stale entry (e.g. during the rapid reconnect loop).
                # Remove the stale entry and fall through to accept + register the
                # fresh WebSocket.  Do NOT return early: the new websocket object
                # has not been accepted yet and must be accepted below, otherwise
                # websocket.receive_text() will raise "WebSocket is not connected."
                logger.info(
                    f"Client {client_id} reconnecting — replacing stale connection entry"
                )
                self.active_connections.pop(client_id)
                # REQ-8 AC5: a new socket replacing a stale one means the old
                # connection's in-flight DER loop may still be broadcasting to this
                # session. Notify the gateway so it can soft-cancel the previously
                # active thread (the incoming sync_state will re-bind / cancel as
                # needed). The hook is set by IRISGateway; None-safe if unset.
                if self.on_client_replace is not None:
                    try:
                        self.on_client_replace(client_id)
                    except Exception as exc:
                        logger.warning(
                            f"[WebSocketManager] on_client_replace hook failed: {exc}"
                        )
                # Cancel the stale heartbeat task.
                if client_id in self._heartbeat_tasks:
                    self._heartbeat_tasks[client_id].cancel()
                    del self._heartbeat_tasks[client_id]
                # Do NOT call stale_ws.close() here.
                # Starlette's WebSocket.close() immediately sets
                # application_state = DISCONNECTED before sending the close
                # frame.  If the old coroutine is mid-way through
                # receive_text() — which checks application_state — it will
                # raise RuntimeError("WebSocket is not connected. Need to call
                # 'accept' first.") instead of the expected WebSocketDisconnect.
                # That RuntimeError escapes to the except-Exception handler in
                # websocket_endpoint, logs a spurious ERROR, and can run the
                # finally block before the new socket is fully registered,
                # disrupting the fresh connection.
                #
                # Correct behaviour: just evict the stale entry from the dict
                # and cancel its heartbeat.  The old coroutine will receive a
                # natural WebSocketDisconnect once the client closes the
                # underlying TCP connection (which happens immediately in
                # virtually all browser reconnect scenarios).  The
                # owns_connection guard in the finally block of
                # websocket_endpoint then prevents the stale coroutine from
                # evicting the newly-registered socket.
 
            # Accept WebSocket connection with error handling
            try:
                await websocket.accept()
            except Exception as e:
                logger.error(f"Failed to accept WebSocket connection for client {client_id}: {e}", exc_info=True)
                return None

            self.active_connections[client_id] = websocket
            
            # Create or get session with error handling
            try:
                # Derive a stable session_id from the client_id when none is
                # provided.  This ensures that a reconnecting client (after a
                # brief network blip or a backend-initiated ping timeout) always
                # returns to the same logical session and reloads any confirmed
                # field values that were persisted to disk.
                if session_id is None:
                    session_id = f"session_{client_id}"

                existing_session = self._session_manager.get_session(session_id)
                connect_start_session = time.time()
                
                if existing_session is not None:
                    # Quick reconnect — session still alive in memory.
                    # Cancel any pending garbage-collection that was scheduled
                    # when the client previously disconnected.
                    existing_session.cleanup_scheduled = False
                    existing_session.is_active = True
                    existing_session.touch()
                    logger.info(
                        f"Client {client_id} re-joined existing session {session_id}"
                    )
                else:
                    # First connect, or session was purged after a long
                    # absence.  create_session() initialises the state manager
                    # and loads the persisted JSON from
                    # backend/sessions/{session_id}/session_state.json if it
                    # exists, so confirmed values survive backend restarts.
                    self._session_manager.create_session(session_id=session_id)
                    logger.info(
                        f"Client {client_id} started session {session_id} "
                        f"(loaded from disk if prior state existed)"
                    )
                
                connect_end_session = time.time()
                logger.debug(f"[WebSocketManager] Session operations for client {client_id} took {connect_end_session - connect_start_session:.3f}s")
            except Exception as e:
                logger.error(f"Failed to create/restore session for client {client_id}: {e}", exc_info=True)
                # Clean up connection
                if client_id in self.active_connections:
                    del self.active_connections[client_id]
                return None

            # Associate client with session
            self._session_manager.associate_client_with_session(client_id, session_id)
            
            # Start heartbeat for this client
            self._last_pong[client_id] = datetime.now()
            connect_start_heartbeat = time.time()
            self._heartbeat_tasks[client_id] = asyncio.create_task(self._heartbeat_loop(client_id))
            connect_end_heartbeat = time.time()
            logger.debug(f"[WebSocketManager] Heartbeat task created for client {client_id} in {connect_end_heartbeat - connect_start_heartbeat:.3f}s")
            
            logger.info(f"Client {client_id} connected to session {session_id}. Total clients: {len(self.active_connections)}")
            return session_id
        except Exception as e:
            logger.error(f"Unexpected error during connection for client {client_id}: {e}", exc_info=True)
            # Clean up any partial state
            if client_id in self.active_connections:
                del self.active_connections[client_id]
            return None

    def mark_liveness(self, client_id: str) -> None:
        """Mark a client as active (received any inbound frame)."""
        self._last_activity[client_id] = time.time()

    async def flush_pending(self, session_id: str, client_id: str) -> None:
        """Flush any buffered undelivered messages for a session/client.

        Replays messages buffered by :meth:`buffer_message` (which the gateway
        calls when a send fails because the client was disconnected mid-turn).
        This is what makes the final chat_message survive a mid-turn disconnect:
        without it, the turn's terminal message was lost and the UI sat stuck
        at "Loading 0/2" forever (live 2026-08-12, pin_8b41f386d397). Called
        after get_state() in _handle_request_state on every (re)connect.
        """
        _q = self._pending.get(session_id)
        if not _q:
            return
        websocket = self.active_connections.get(client_id)
        if not websocket:
            return  # not connected yet — leave buffered for the next reconnect
        try:
            _lock = self._get_send_lock(client_id)
            async with _lock:
                while _q:
                    _msg = _q.popleft()
                    try:
                        await websocket.send_json(_msg)
                    except Exception:
                        # Send failed again — re-buffer the rest and stop.
                        _q.appendleft(_msg)
                        break
            if not _q:
                self._pending.pop(session_id, None)
        except Exception:
            pass  # replay is best-effort; never break the reconnect path

    def buffer_message(self, session_id: str, message: dict) -> None:
        """Buffer a message for replay on the client's next (re)connect.

        Bounded per session (maxlen) so an abandoned session cannot grow the
        queue without limit (CLAUDE.md: memory footprint bounded). The gateway
        calls this when send_to_client returns False — the client disconnected
        mid-turn (or never connected), and the message (typically the final
        chat_message) must not be lost.
        """
        _q = self._pending.setdefault(session_id, deque(maxlen=_PENDING_MAX))
        _q.append(message)

    def _get_send_lock(self, client_id: str) -> asyncio.Lock:
        """Return the per-(client, event-loop) send lock, creating it on first use.

        Keyed by (client_id, id(running loop)) because asyncio.Lock binds to
        the loop that first acquires it, and this backend legitimately sends
        from more than one loop (see _send_locks' comment in __init__). Returns
        a fresh lock per (client, loop); the setdefault keeps concurrent first
        senders from racing to create the lock itself.
        """
        try:
            _loop_id = id(asyncio.get_running_loop())
        except RuntimeError:
            # No running loop in this thread (rare, e.g. a test calling
            # send_to_client from a bare thread) — share one lock per client.
            _loop_id = 0
        _key = (client_id, _loop_id)
        _lock = self._send_locks.get(_key)
        if _lock is None:
            _lock = asyncio.Lock()
            self._send_locks[_key] = _lock
        return _lock

    def disconnect(self, client_id: str):
        """Remove a client connection and dissociate from its session."""
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            # Drop the send locks too, or _send_locks grows unbounded across
            # reconnects (CLAUDE.md: memory footprint bounded). Keys are
            # (client_id, loop_id) tuples — remove every loop's lock for this
            # client.
            for _key in [k for k in self._send_locks if k[0] == client_id]:
                self._send_locks.pop(_key, None)
            # Dissociate client from session but don't end the session
            session_id = self._session_manager.dissociate_client(client_id)

            # Cancel heartbeat and schedule awaiting it so CancelledError is consumed
            task = self._heartbeat_tasks.pop(client_id, None)
            if task and not task.done():
                task.cancel()
                # Schedule a fire-and-forget await so the task fully exits
                async def _reap(t: asyncio.Task) -> None:
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass
                asyncio.ensure_future(_reap(task))

            # Clean up pong tracking
            if client_id in self._last_pong:
                del self._last_pong[client_id]
            if client_id in self._last_activity:
                del self._last_activity[client_id]

            logger.debug(f"Client {client_id} disconnected from session {session_id}. Total clients: {len(self.active_connections)}")
    
    async def _heartbeat_loop(self, client_id: str):
        """
        Send ping messages every PING_INTERVAL seconds.
        Disconnect client if pong not received within PONG_TIMEOUT.
        
        Error Handling:
        - Ping send failures: Log and disconnect client
        - Pong timeout: Log warning and disconnect client with reconnection attempt
        """
        try:
            while client_id in self.active_connections:
                await asyncio.sleep(self.PING_INTERVAL)
                
                if client_id not in self.active_connections:
                    break
                
                # Send ping with error handling
                try:
                    # Record send time BEFORE awaiting so the timestamp is
                    # accurate even if send_to_client takes a moment.
                    ping_sent_at = datetime.now()
                    sent = await self.send_to_client(client_id, {"type": "ping", "payload": {}})
                    if not sent:
                        # send_to_client already called disconnect() for us when
                        # the underlying write failed.  Stop the heartbeat loop
                        # WITHOUT logging a spurious "did not respond to ping"
                        # warning — the socket was simply already gone.
                        logger.debug(f"Client {client_id} unreachable during ping — heartbeat stopping")
                        break
                    logger.debug(f"Sent ping to client {client_id}")

                    # Wait for pong response
                    await asyncio.sleep(self.PONG_TIMEOUT)

                    # Reliable check: did we receive a pong AFTER we sent this ping?
                    # Comparing timestamps avoids the old "time_since_pong > 35s"
                    # arithmetic which fired spuriously when the asyncio event loop
                    # was busy (LLM/TTS) and the pong landed just after the window.
                    last_pong = self._last_pong.get(client_id)
                    if last_pong is None or last_pong < ping_sent_at:
                        logger.warning(
                            f"Client {client_id} did not respond to ping within {self.PONG_TIMEOUT}s, disconnecting",
                            extra={"client_id": client_id, "timeout": self.PONG_TIMEOUT}
                        )
                        self.disconnect(client_id)
                        break
                except Exception as e:
                    logger.error(
                        f"Error in heartbeat for client {client_id}: {e}",
                        exc_info=True,
                        extra={"client_id": client_id, "error": str(e)}
                    )
                    self.disconnect(client_id)
                    break
        except asyncio.CancelledError:
            logger.debug(f"Heartbeat task cancelled for client {client_id}")
        except Exception as e:
            logger.error(
                f"Unexpected error in heartbeat loop for client {client_id}: {e}",
                exc_info=True,
                extra={"client_id": client_id, "error": str(e)}
            )
            self.disconnect(client_id)
    
    async def handle_pong(self, client_id: str):
        """
        Handle pong message from client.
        Updates the last pong timestamp for the client.
        """
        if client_id in self._last_pong:
            self._last_pong[client_id] = datetime.now()
            logger.debug(f"Received pong from client {client_id}")
    
    def get_session_id_for_client(self, client_id: str) -> Optional[str]:
        """Get the session ID for a given client ID."""
        return self._session_manager.client_to_session.get(client_id)

    def session_exists(self, session_id: str) -> bool:
        """True if a session with the given ID is currently registered.

        Used by the event bridge to decide between session-routed delivery and
        a fallback broadcast: events emitted under placeholder sessions (e.g.
        the DER sub-loop session "unknown") must not be silently dropped.
        """
        return self._session_manager.get_session(session_id) is not None

    async def send_to_client(self, client_id: str, message: dict) -> bool:
        """
        Send a message to a specific client.
        Returns True if sent successfully.
        """
        websocket = self.active_connections.get(client_id)
        if not websocket:
            return False

        try:
            # Serialise per socket, per event loop — see _send_locks.
            _lock = self._get_send_lock(client_id)
            async with _lock:
                await websocket.send_json(message)
            return True
        except Exception as e:
            logger.error(f"Error sending to {client_id}: {e}")
            # Identity check: only remove the stale socket that failed.
            # A concurrent reconnect may have already replaced active_connections[client_id]
            # with a fresh (accepted) socket — don't evict that new connection.
            if self.active_connections.get(client_id) is websocket:
                self.disconnect(client_id)
            return False

    async def broadcast(self, message: dict, exclude_clients: Optional[Set[str]] = None):
        """Broadcast a message to all connected clients."""
        if exclude_clients is None:
            exclude_clients = set()

        # Snapshot the dict so mutations during iteration (reconnects) don't
        # cause RuntimeError.  Store (client_id, websocket) pairs so the
        # identity check below can avoid evicting a freshly-reconnected socket.
        snapshot = list(self.active_connections.items())
        disconnected: list[tuple[str, object]] = []
        for client_id, websocket in snapshot:
            if client_id not in exclude_clients:
                try:
                    # Same per-client, per-loop lock as send_to_client — this path wrote
                    # to the socket DIRECTLY, so locking only send_to_client
                    # would still leave broadcasts able to interleave with a
                    # streamed chunk and corrupt the frame.
                    _lock = self._get_send_lock(client_id)
                    async with _lock:
                        await websocket.send_json(message)
                except Exception:
                    disconnected.append((client_id, websocket))

        for client_id, websocket in disconnected:
            if self.active_connections.get(client_id) is websocket:
                self.disconnect(client_id)

    async def broadcast_to_session(self, session_id: str, message: dict, exclude_clients: Optional[Set[str]] = None):
        """Broadcast a message to all clients in a specific session."""
        session = self._session_manager.get_session(session_id)
        if not session:
            return

        if exclude_clients is None:
            exclude_clients = set()

        clients_in_session = session.connected_clients
        for client_id in clients_in_session:
            if client_id not in exclude_clients:
                await self.send_to_client(client_id, message)

    def get_connection_count(self) -> int:
        """Get number of active connections."""
        return len(self.active_connections)

    def get_client_ids(self) -> List[str]:
        """Get list of all connected client IDs."""
        return list(self.active_connections.keys())

    def get_active_session_ids(self) -> List[str]:
        """Return list of session IDs with at least one connected client."""
        # Use client_to_session to find all sessions that have active clients
        session_ids = []
        seen = set()
        for client_id, session_id in self._session_manager.client_to_session.items():
            if session_id not in seen and client_id in self.active_connections:
                seen.add(session_id)
                session_ids.append(session_id)
        return session_ids

    def get_clients_for_session(self, session_id: str) -> List[str]:
        """Return list of client_ids connected in a given session."""
        session = self._session_manager.get_session(session_id)
        if not session:
            return []
        # Filter to only clients that are actually in active_connections
        return [
            client_id for client_id in session.connected_clients
            if client_id in self.active_connections
        ]


# Global instance
_ws_manager: Optional[WebSocketManager] = None


def get_websocket_manager() -> WebSocketManager:
    """Get or create the singleton WebSocketManager."""
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WebSocketManager()
    return _ws_manager
