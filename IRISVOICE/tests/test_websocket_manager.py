"""
Unit tests for WebSocketManager class.
Tests connection handling, heartbeat mechanism, and message routing.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
import sys
import os

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.ws_manager import WebSocketManager
from backend.sessions.session_manager import SessionManager
from backend.state_manager import StateManager


@pytest.fixture
def mock_session_manager():
    """Create a mock SessionManager."""
    manager = MagicMock(spec=SessionManager)
    manager.client_to_session = {}
    manager.create_session = AsyncMock(return_value="test-session-id")
    manager.get_session = MagicMock(return_value=MagicMock(connected_clients=set()))
    manager.associate_client_with_session = MagicMock()
    manager.dissociate_client = MagicMock(return_value="test-session-id")
    return manager


@pytest.fixture
def mock_state_manager():
    """Create a mock StateManager."""
    manager = MagicMock(spec=StateManager)
    manager.initialize_session_state = AsyncMock()
    manager.get_state = AsyncMock(return_value=None)
    return manager


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


@pytest.fixture
def ws_manager(mock_session_manager, mock_state_manager):
    """Create a WebSocketManager with mocked dependencies."""
    return WebSocketManager(
        session_manager=mock_session_manager,
        state_manager=mock_state_manager
    )


class TestWebSocketManagerConnection:
    """Test WebSocket connection handling."""
    
    @pytest.mark.asyncio
    async def test_connect_new_client(self, ws_manager, mock_websocket):
        """Test connecting a new client creates a session and starts heartbeat."""
        client_id = "test-client-1"
        
        session_id = await ws_manager.connect(mock_websocket, client_id)
        
        # Verify connection was accepted
        mock_websocket.accept.assert_called_once()
        
        # Verify session was created
        assert session_id == "test-session-id"
        
        # Verify client is in active connections
        assert client_id in ws_manager.active_connections
        
        # Verify heartbeat task was created
        assert client_id in ws_manager._heartbeat_tasks
        assert client_id in ws_manager._last_pong
        
        # Clean up
        ws_manager.disconnect(client_id)
    
    @pytest.mark.asyncio
    async def test_connect_with_existing_session(self, ws_manager, mock_websocket, mock_session_manager):
        """Test connecting a client with an existing session ID."""
        client_id = "test-client-2"
        existing_session_id = "existing-session"
        
        # Mock that session exists
        mock_session_manager.get_session.return_value = MagicMock(connected_clients=set())
        
        session_id = await ws_manager.connect(mock_websocket, client_id, existing_session_id)
        
        # Verify the existing session ID was used
        assert session_id == existing_session_id
        
        # Clean up
        ws_manager.disconnect(client_id)
    
    @pytest.mark.asyncio
    async def test_disconnect_cleans_up_resources(self, ws_manager, mock_websocket):
        """Test that disconnect properly cleans up all resources."""
        client_id = "test-client-3"
        
        # Connect client
        await ws_manager.connect(mock_websocket, client_id)
        
        # Verify resources exist
        assert client_id in ws_manager.active_connections
        assert client_id in ws_manager._heartbeat_tasks
        assert client_id in ws_manager._last_pong
        
        # Disconnect
        ws_manager.disconnect(client_id)
        
        # Verify all resources cleaned up
        assert client_id not in ws_manager.active_connections
        assert client_id not in ws_manager._heartbeat_tasks
        assert client_id not in ws_manager._last_pong


class TestWebSocketManagerHeartbeat:
    """Test ping/pong heartbeat mechanism."""
    
    @pytest.mark.asyncio
    async def test_handle_pong_updates_timestamp(self, ws_manager, mock_websocket):
        """Test that handle_pong updates the last pong timestamp."""
        client_id = "test-client-4"
        
        # Connect client
        await ws_manager.connect(mock_websocket, client_id)
        
        # Get initial timestamp
        initial_time = ws_manager._last_pong[client_id]
        
        # Wait a bit
        await asyncio.sleep(0.1)
        
        # Handle pong
        await ws_manager.handle_pong(client_id)
        
        # Verify timestamp was updated
        assert ws_manager._last_pong[client_id] > initial_time
        
        # Clean up
        ws_manager.disconnect(client_id)
    
    @pytest.mark.asyncio
    async def test_heartbeat_sends_ping(self, ws_manager, mock_websocket):
        """Test that heartbeat loop sends ping messages."""
        client_id = "test-client-5"
        
        # Reduce ping interval for testing
        original_interval = ws_manager.PING_INTERVAL
        ws_manager.PING_INTERVAL = 0.2  # 200ms for testing
        
        try:
            # Connect client
            await ws_manager.connect(mock_websocket, client_id)
            
            # Wait for at least one ping cycle
            await asyncio.sleep(0.3)
            
            # Verify ping was sent
            # Check if send_json was called with ping message
            calls = mock_websocket.send_json.call_args_list
            ping_sent = any(
                call[0][0].get("type") == "ping" 
                for call in calls
            )
            assert ping_sent, "Ping message should have been sent"
            
        finally:
            # Restore original interval
            ws_manager.PING_INTERVAL = original_interval
            ws_manager.disconnect(client_id)


class TestWebSocketManagerMessaging:
    """Test message sending and broadcasting."""
    
    @pytest.mark.asyncio
    async def test_send_to_client_success(self, ws_manager, mock_websocket):
        """Test sending a message to a specific client."""
        client_id = "test-client-6"
        
        # Connect client
        await ws_manager.connect(mock_websocket, client_id)
        
        # Send message
        message = {"type": "test", "payload": {"data": "hello"}}
        result = await ws_manager.send_to_client(client_id, message)
        
        # Verify message was sent
        assert result is True
        mock_websocket.send_json.assert_called()
        
        # Clean up
        ws_manager.disconnect(client_id)
    
    @pytest.mark.asyncio
    async def test_send_to_nonexistent_client(self, ws_manager):
        """Test sending to a client that doesn't exist returns False."""
        result = await ws_manager.send_to_client("nonexistent", {"type": "test"})
        assert result is False
    
    @pytest.mark.asyncio
    async def test_broadcast_to_all_clients(self, ws_manager):
        """Test broadcasting a message to all connected clients."""
        # Create multiple mock websockets
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws1.send_json = AsyncMock()
        
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()
        ws2.send_json = AsyncMock()
        
        # Connect multiple clients
        await ws_manager.connect(ws1, "client-1")
        await ws_manager.connect(ws2, "client-2")
        
        # Broadcast message
        message = {"type": "broadcast", "payload": {"data": "hello all"}}
        await ws_manager.broadcast(message)
        
        # Verify both clients received the message
        ws1.send_json.assert_called()
        ws2.send_json.assert_called()
        
        # Clean up
        ws_manager.disconnect("client-1")
        ws_manager.disconnect("client-2")
    
    @pytest.mark.asyncio
    async def test_broadcast_with_exclusions(self, ws_manager):
        """Test broadcasting with excluded clients."""
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws1.send_json = AsyncMock()
        
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()
        ws2.send_json = AsyncMock()
        
        # Connect clients
        await ws_manager.connect(ws1, "client-1")
        await ws_manager.connect(ws2, "client-2")
        
        # Reset call counts
        ws1.send_json.reset_mock()
        ws2.send_json.reset_mock()
        
        # Broadcast with exclusion
        message = {"type": "broadcast", "payload": {}}
        await ws_manager.broadcast(message, exclude_clients={"client-1"})
        
        # Verify only client-2 received the message
        ws1.send_json.assert_not_called()
        ws2.send_json.assert_called()
        
        # Clean up
        ws_manager.disconnect("client-1")
        ws_manager.disconnect("client-2")


class TestWebSocketManagerUtilities:
    """Test utility methods."""
    
    @pytest.mark.asyncio
    async def test_get_connection_count(self, ws_manager, mock_websocket):
        """Test getting the number of active connections."""
        assert ws_manager.get_connection_count() == 0
        
        await ws_manager.connect(mock_websocket, "client-1")
        assert ws_manager.get_connection_count() == 1
        
        ws_manager.disconnect("client-1")
        assert ws_manager.get_connection_count() == 0
    
    @pytest.mark.asyncio
    async def test_get_client_ids(self, ws_manager):
        """Test getting list of connected client IDs."""
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()
        
        await ws_manager.connect(ws1, "client-1")
        await ws_manager.connect(ws2, "client-2")
        
        client_ids = ws_manager.get_client_ids()
        assert "client-1" in client_ids
        assert "client-2" in client_ids
        assert len(client_ids) == 2
        
        # Clean up
        ws_manager.disconnect("client-1")
        ws_manager.disconnect("client-2")
    
    @pytest.mark.asyncio
    async def test_get_session_id_for_client(self, ws_manager, mock_websocket, mock_session_manager):
        """Test getting session ID for a client."""
        client_id = "test-client"
        session_id = "test-session"
        
        # Mock the session manager to return our session ID
        mock_session_manager.client_to_session[client_id] = session_id
        
        result = ws_manager.get_session_id_for_client(client_id)
        assert result == session_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
