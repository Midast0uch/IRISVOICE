"""
IRIS WebSocket Connection Manager (Session-Aware)
Handles client connections, session association, and message routing.
"""
import json
import logging
import asyncio
from typing import Dict, List, Set, Optional
from fastapi import WebSocket
from datetime import datetime

logger = logging.getLogger(__name__)

from .sessions import get_session_manager, SessionManager
from .state_manager import get_state_manager, StateManager


class WebSocketManager:
    """
    Manages WebSocket connections and associates them with IRIS sessions.
    Includes ping/pong heartbeat mechanism to maintain connections.
    """
    
    PING_INTERVAL = 30  # seconds
    PONG_TIMEOUT = 5    # seconds
    
    def __init__(self, session_manager: Optional[SessionManager] = None, state_manager: Optional[StateManager] = None):
        self.active_connections: Dict[str, WebSocket] = {}
        self._session_manager = session_manager or get_session_manager()
        self._state_manager = state_manager or get_state_manager()
        self._heartbeat_tasks: Dict[str, asyncio.Task] = {}
        self._last_pong: Dict[str, datetime] = {}
    
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
                stale_ws = self.active_connections.pop(client_id)
                # Cancel old heartbeat before closing stale socket
                if client_id in self._heartbeat_tasks:
                    self._heartbeat_tasks[client_id].cancel()
                    del self._heartbeat_tasks[client_id]
                try:
                    await stale_ws.close()
                except Exception:
                    pass  # already closed or in error state; ignore

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
                if existing_session is not None:
                    # Quick reconnect — session still alive in memory.
                    # Cancel any pending garbage-collection that was scheduled
                    # when the client previously disconnected.
                    existing_session.cleanup_scheduled = False
                    existing_session.is_active = True
                    await existing_session.touch()
                    logger.info(
                        f"Client {client_id} re-joined existing session {session_id}"
                    )
                else:
                    # First connect, or session was purged after a long
                    # absence.  create_session() initialises the state manager
                    # and loads the persisted JSON from
                    # backend/sessions/{session_id}/session_state.json if it
                    # exists, so confirmed values survive backend restarts.
                    await self._session_manager.create_session(session_id=session_id)
                    logger.info(
                        f"Client {client_id} started session {session_id} "
                        f"(loaded from disk if prior state existed)"
                    )
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
            self._heartbeat_tasks[client_id] = asyncio.create_task(self._heartbeat_loop(client_id))
            
            logger.info(f"Client {client_id} connected to session {session_id}. Total clients: {len(self.active_connections)}")
            return session_id
        except Exception as e:
            logger.error(f"Unexpected error during connection for client {client_id}: {e}", exc_info=True)
            # Clean up any partial state
            if client_id in self.active_connections:
                del self.active_connections[client_id]
            return None
    
    def disconnect(self, client_id: str):
        """Remove a client connection and dissociate from its session."""
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            # Dissociate client from session but don't end the session
            session_id = self._session_manager.dissociate_client(client_id)
            
            # Cancel heartbeat task
            if client_id in self._heartbeat_tasks:
                self._heartbeat_tasks[client_id].cancel()
                del self._heartbeat_tasks[client_id]
            
            # Clean up pong tracking
            if client_id in self._last_pong:
                del self._last_pong[client_id]
            
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
                    await self.send_to_client(client_id, {"type": "ping", "payload": {}})
                    logger.debug(f"Sent ping to client {client_id}")
                    
                    # Wait for pong response
                    await asyncio.sleep(self.PONG_TIMEOUT)
                    
                    # Check if pong was received within timeout
                    if client_id in self._last_pong:
                        time_since_pong = (datetime.now() - self._last_pong[client_id]).total_seconds()
                        if time_since_pong > self.PONG_TIMEOUT + self.PING_INTERVAL:
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

    async def send_to_client(self, client_id: str, message: dict) -> bool:
        """
        Send a message to a specific client.
        Returns True if sent successfully.
        """
        websocket = self.active_connections.get(client_id)
        if not websocket:
            return False
        
        try:
            await websocket.send_json(message)
            return True
        except Exception as e:
            logger.error(f"Error sending to {client_id}: {e}")
            self.disconnect(client_id)
            return False
    
    async def broadcast(self, message: dict, exclude_clients: Optional[Set[str]] = None):
        """Broadcast a message to all connected clients."""
        if exclude_clients is None:
            exclude_clients = set()

        disconnected_clients = []
        for client_id, websocket in self.active_connections.items():
            if client_id not in exclude_clients:
                try:
                    await websocket.send_json(message)
                except Exception:
                    disconnected_clients.append(client_id)
        
        for client_id in disconnected_clients:
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
