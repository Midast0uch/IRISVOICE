"""
IRIS WebSocket Connection Manager (Session-Aware)
Handles client connections, session association, and message routing.
"""
import json
from typing import Dict, List, Set, Optional
from fastapi import WebSocket
from datetime import datetime

from .sessions import get_session_manager, SessionManager
from .state_manager import get_state_manager, StateManager


class WebSocketManager:
    """
    Manages WebSocket connections and associates them with IRIS sessions.
    """
    
    def __init__(self, session_manager: Optional[SessionManager] = None, state_manager: Optional[StateManager] = None):
        self.active_connections: Dict[str, WebSocket] = {}
        self._session_manager = session_manager or get_session_manager()
        self._state_manager = state_manager or get_state_manager()
    
    async def connect(self, websocket: WebSocket, client_id: str, session_id: Optional[str] = None) -> Optional[str]:
        """
        Accept a new WebSocket connection and associate it with a session.
        If session_id is not provided, a new session is created.
        Returns the session_id if successful, None otherwise.
        """
        if client_id in self.active_connections:
            print(f"Client {client_id} already connected.")
            return self._session_manager.client_to_session.get(client_id)
        
        await websocket.accept()
        self.active_connections[client_id] = websocket
        
        # Create or get session
        if session_id is None:
            session_id = self._session_manager.create_session()
            # Initialize the state for the new session
            await self._state_manager.initialize_session_state(session_id)
        elif not self._session_manager.get_session(session_id):
             # If client requests a specific session that doesn't exist, create it
            self._session_manager.create_session(session_id=session_id)
            await self._state_manager.initialize_session_state(session_id)

        # Associate client with session
        self._session_manager.associate_client_with_session(client_id, session_id)
        
        print(f"Client {client_id} connected to session {session_id}. Total clients: {len(self.active_connections)}")
        return session_id
    
    def disconnect(self, client_id: str):
        """Remove a client connection and dissociate from its session."""
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            # Dissociate client from session but don't end the session
            session_id = self._session_manager.dissociate_client(client_id)
            print(f"Client {client_id} disconnected from session {session_id}. Total clients: {len(self.active_connections)}")
    
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
            print(f"Error sending to {client_id}: {e}")
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


# Global instance
_ws_manager: Optional[WebSocketManager] = None


def get_websocket_manager() -> WebSocketManager:
    """Get or create the singleton WebSocketManager."""
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WebSocketManager()
    return _ws_manager
