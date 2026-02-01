"""
IRIS WebSocket Connection Manager
Handles client connections, message routing, and broadcasts
"""
import json
from typing import Dict, List, Set
from fastapi import WebSocket


class WebSocketManager:
    """
    Manages WebSocket connections for IRIS.
    Handles connection/disconnection, message broadcasting, and client tracking.
    """
    
    def __init__(self):
        # Active connections: client_id -> WebSocket
        self.active_connections: Dict[str, WebSocket] = {}
        # Client metadata: client_id -> metadata
        self.client_info: Dict[str, dict] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str) -> bool:
        """
        Accept a new WebSocket connection.
        Returns True if successful, False if client_id already exists.
        """
        if client_id in self.active_connections:
            print(f"Client {client_id} already connected")
            return False
        
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.client_info[client_id] = {
            "connected_at": self._get_timestamp(),
            "message_count": 0
        }
        print(f"Client {client_id} connected. Total: {len(self.active_connections)}")
        return True
    
    def disconnect(self, client_id: str) -> None:
        """Remove a client connection"""
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            if client_id in self.client_info:
                del self.client_info[client_id]
            print(f"Client {client_id} disconnected. Total: {len(self.active_connections)}")
    
    async def send_to_client(self, client_id: str, message: dict) -> bool:
        """
        Send a message to a specific client.
        Returns True if sent successfully.
        """
        if client_id not in self.active_connections:
            return False
        
        try:
            websocket = self.active_connections[client_id]
            await websocket.send_json(message)
            self.client_info[client_id]["message_count"] += 1
            return True
        except Exception as e:
            print(f"Error sending to {client_id}: {e}")
            self.disconnect(client_id)
            return False
    
    async def broadcast(self, message: dict, exclude: Set[str] = None) -> int:
        """
        Broadcast a message to all connected clients.
        Returns count of successful sends.
        Optionally exclude specific client IDs.
        """
        exclude = exclude or set()
        successful = 0
        
        # Collect disconnected clients during iteration
        disconnected = []
        
        for client_id, websocket in self.active_connections.items():
            if client_id in exclude:
                continue
            
            try:
                await websocket.send_json(message)
                self.client_info[client_id]["message_count"] += 1
                successful += 1
            except Exception as e:
                print(f"Error broadcasting to {client_id}: {e}")
                disconnected.append(client_id)
        
        # Clean up disconnected clients
        for client_id in disconnected:
            self.disconnect(client_id)
        
        return successful
    
    async def send_error(self, client_id: str, error_message: str, field_id: str = None) -> bool:
        """Send a validation error to a client"""
        error_payload = {
            "type": "validation_error",
            "error": error_message
        }
        if field_id:
            error_payload["field_id"] = field_id
        
        return await self.send_to_client(client_id, error_payload)
    
    def get_connection_count(self) -> int:
        """Get number of active connections"""
        return len(self.active_connections)
    
    def get_client_ids(self) -> List[str]:
        """Get list of all connected client IDs"""
        return list(self.active_connections.keys())
    
    @staticmethod
    def _get_timestamp() -> str:
        """Get current ISO timestamp"""
        from datetime import datetime
        return datetime.now().isoformat()


# Global instance
_ws_manager: WebSocketManager = None


def get_websocket_manager() -> WebSocketManager:
    """Get or create the singleton WebSocketManager"""
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WebSocketManager()
    return _ws_manager
