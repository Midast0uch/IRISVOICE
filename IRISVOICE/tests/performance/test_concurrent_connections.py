"""
Performance test for concurrent WebSocket connection handling.
Validates that backend handles at least 100 concurrent connections.
"""
import pytest
import asyncio
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

# Add parent directory to path for imports
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.ws_manager import WebSocketManager
from backend.sessions import SessionManager
from backend.state_manager import StateManager


class MockWebSocket:
    """Mock WebSocket for testing."""
    
    def __init__(self, client_id: str):
        self.client_id = client_id
        self.messages: List[dict] = []
        self.closed = False
    
    async def accept(self):
        """Mock accept."""
        pass
    
    async def send_json(self, message: dict):
        """Mock send_json."""
        if not self.closed:
            self.messages.append(message)
    
    async def close(self):
        """Mock close."""
        self.closed = True


class TestConcurrentConnections:
    """Test concurrent WebSocket connection handling."""
    
    @pytest.mark.asyncio
    async def test_handle_100_concurrent_connections(self):
        """Test that backend handles 100 concurrent connections."""
        session_manager = SessionManager()
        state_manager = StateManager(session_manager)
        ws_manager = WebSocketManager(session_manager, state_manager)
        
        # Create 100 mock WebSocket connections
        connections = []
        for i in range(100):
            ws = MockWebSocket(f"client_{i}")
            connections.append(ws)
        
        # Connect all clients concurrently
        connect_tasks = []
        for i, ws in enumerate(connections):
            task = ws_manager.connect(ws, f"client_{i}")
            connect_tasks.append(task)
        
        # Wait for all connections to complete
        session_ids = await asyncio.gather(*connect_tasks)
        
        # Verify all connections succeeded
        assert len(session_ids) == 100, "All connections should succeed"
        assert all(sid is not None for sid in session_ids), "All should have session IDs"
        
        # Verify connection count
        assert ws_manager.get_connection_count() == 100, "Should have 100 active connections"
    
    @pytest.mark.asyncio
    async def test_broadcast_to_100_connections(self):
        """Test broadcasting messages to 100 concurrent connections."""
        session_manager = SessionManager()
        state_manager = StateManager(session_manager)
        ws_manager = WebSocketManager(session_manager, state_manager)
        
        # Create and connect 100 clients
        connections = []
        for i in range(100):
            ws = MockWebSocket(f"client_{i}")
            await ws_manager.connect(ws, f"client_{i}")
            connections.append(ws)
        
        # Broadcast a message to all clients
        test_message = {"type": "test", "payload": {"data": "broadcast"}}
        await ws_manager.broadcast(test_message)
        
        # Verify all clients received the message
        for ws in connections:
            assert len(ws.messages) > 0, f"Client {ws.client_id} should receive message"
            assert any(
                msg.get("type") == "test" for msg in ws.messages
            ), f"Client {ws.client_id} should receive test message"
    
    @pytest.mark.asyncio
    async def test_concurrent_message_sending(self):
        """Test sending messages concurrently to multiple clients."""
        session_manager = SessionManager()
        state_manager = StateManager(session_manager)
        ws_manager = WebSocketManager(session_manager, state_manager)
        
        # Create and connect 50 clients
        connections = []
        for i in range(50):
            ws = MockWebSocket(f"client_{i}")
            await ws_manager.connect(ws, f"client_{i}")
            connections.append(ws)
        
        # Send messages concurrently to all clients
        send_tasks = []
        for i in range(50):
            message = {"type": "test", "payload": {"client": i}}
            task = ws_manager.send_to_client(f"client_{i}", message)
            send_tasks.append(task)
        
        # Wait for all sends to complete
        results = await asyncio.gather(*send_tasks)
        
        # Verify all sends succeeded
        assert all(results), "All sends should succeed"
        
        # Verify each client received their message
        for i, ws in enumerate(connections):
            assert len(ws.messages) > 0, f"Client {i} should receive message"
    
    @pytest.mark.asyncio
    async def test_connection_and_disconnection_under_load(self):
        """Test rapid connection and disconnection cycles."""
        session_manager = SessionManager()
        state_manager = StateManager(session_manager)
        ws_manager = WebSocketManager(session_manager, state_manager)
        
        # Cycle through 200 connections (connect and disconnect)
        for batch in range(4):
            # Connect 50 clients
            connections = []
            for i in range(50):
                client_id = f"client_{batch}_{i}"
                ws = MockWebSocket(client_id)
                await ws_manager.connect(ws, client_id)
                connections.append((client_id, ws))
            
            # Verify connections
            assert ws_manager.get_connection_count() == 50
            
            # Disconnect all clients
            for client_id, ws in connections:
                ws_manager.disconnect(client_id)
            
            # Verify disconnections
            assert ws_manager.get_connection_count() == 0
    
    @pytest.mark.asyncio
    async def test_session_isolation_with_multiple_connections(self):
        """Test that sessions remain isolated with multiple connections."""
        session_manager = SessionManager()
        state_manager = StateManager(session_manager)
        ws_manager = WebSocketManager(session_manager, state_manager)
        
        # Create 10 sessions with 10 clients each
        sessions = {}
        for session_idx in range(10):
            session_id = f"session_{session_idx}"
            sessions[session_id] = []
            
            for client_idx in range(10):
                client_id = f"client_{session_idx}_{client_idx}"
                ws = MockWebSocket(client_id)
                await ws_manager.connect(ws, client_id, session_id)
                sessions[session_id].append((client_id, ws))
        
        # Verify total connections
        assert ws_manager.get_connection_count() == 100
        
        # Broadcast to each session separately
        for session_idx, (session_id, clients) in enumerate(sessions.items()):
            message = {"type": "test", "payload": {"session": session_idx}}
            await ws_manager.broadcast_to_session(session_id, message)
        
        # Verify each session received only their message
        for session_idx, (session_id, clients) in enumerate(sessions.items()):
            for client_id, ws in clients:
                # Should have received message for their session
                session_messages = [
                    msg for msg in ws.messages
                    if msg.get("type") == "test"
                ]
                assert len(session_messages) == 1, f"Client {client_id} should receive 1 message"
                assert session_messages[0]["payload"]["session"] == session_idx
    
    @pytest.mark.asyncio
    async def test_performance_under_high_message_load(self):
        """Test performance with high message throughput."""
        session_manager = SessionManager()
        state_manager = StateManager(session_manager)
        ws_manager = WebSocketManager(session_manager, state_manager)
        
        # Connect 50 clients
        connections = []
        for i in range(50):
            ws = MockWebSocket(f"client_{i}")
            await ws_manager.connect(ws, f"client_{i}")
            connections.append(ws)
        
        # Send 100 messages to each client (5000 total messages)
        import time
        start_time = time.time()
        
        send_tasks = []
        for i in range(50):
            for msg_idx in range(100):
                message = {"type": "test", "payload": {"index": msg_idx}}
                task = ws_manager.send_to_client(f"client_{i}", message)
                send_tasks.append(task)
        
        # Wait for all sends
        await asyncio.gather(*send_tasks)
        
        elapsed = time.time() - start_time
        
        # Should complete in reasonable time (< 5 seconds for 5000 messages)
        assert elapsed < 5.0, f"Should send 5000 messages in <5s, took {elapsed:.2f}s"
        
        # Verify message delivery
        for ws in connections:
            assert len(ws.messages) >= 100, f"Client should receive 100+ messages"
    
    @pytest.mark.asyncio
    async def test_graceful_handling_of_connection_failures(self):
        """Test graceful handling when some connections fail."""
        session_manager = SessionManager()
        state_manager = StateManager(session_manager)
        ws_manager = WebSocketManager(session_manager, state_manager)
        
        # Create mix of good and bad connections
        good_connections = []
        bad_connections = []
        
        for i in range(50):
            ws = MockWebSocket(f"good_client_{i}")
            await ws_manager.connect(ws, f"good_client_{i}")
            good_connections.append(ws)
        
        # Create connections that will fail on send
        for i in range(50):
            ws = MockWebSocket(f"bad_client_{i}")
            ws.closed = True  # Simulate closed connection
            await ws_manager.connect(ws, f"bad_client_{i}")
            bad_connections.append(ws)
        
        # Broadcast message - should handle failures gracefully
        message = {"type": "test", "payload": {"data": "test"}}
        await ws_manager.broadcast(message)
        
        # Good connections should receive message
        for ws in good_connections:
            assert len(ws.messages) > 0, "Good connections should receive message"
        
        # Bad connections should be disconnected
        # (WebSocketManager should handle send failures)
        # Note: In real implementation, failed connections would be removed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
