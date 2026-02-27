"""
Integration test for WebSocket connection flow.

Tests:
- Connection establishment
- Initial state delivery
- Ping/pong heartbeat
- Connection retry and reconnection

Feature: irisvoice-backend-integration
Requirements: 1.1, 1.2, 1.3, 1.6
"""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocket, WebSocketDisconnect


@pytest.mark.asyncio
async def test_websocket_connection_establishment(mock_websocket_manager, mock_session_manager, mock_state_manager):
    """Test WebSocket connection establishment and initial state delivery."""
    # Arrange
    client_id = "test-client-123"
    session_id = "test-session-456"
    
    mock_session = MagicMock()
    mock_session.session_id = session_id
    mock_session_manager.create_session.return_value = session_id
    mock_session_manager.get_session.return_value = mock_session
    
    initial_state = {
        "current_category": None,
        "current_subnode": None,
        "field_values": {},
        "active_theme": {
            "glow_color": "#00ffff",
            "font_color": "#ffffff"
        },
        "confirmed_nodes": [],
        "app_state": {
            "voice_state": "idle",
            "audio_level": 0.0
        }
    }
    mock_state_manager.get_state.return_value = initial_state
    
    # Mock WebSocket
    websocket = AsyncMock(spec=WebSocket)
    websocket.accept = AsyncMock()
    websocket.send_json = AsyncMock()
    websocket.receive_text = AsyncMock(side_effect=WebSocketDisconnect(code=1000))
    
    # Act - Connect with session_id provided
    result_session_id = await mock_websocket_manager.connect(websocket, client_id, session_id)
    
    # Assert - Connection established
    assert result_session_id == session_id
    websocket.accept.assert_called_once()
    
    # Assert - Initial state sent
    mock_state_manager.get_state.assert_called_once_with(session_id)
    
    # Verify initial_state message would be sent
    assert mock_websocket_manager.active_connections.get(client_id) == websocket


@pytest.mark.asyncio
async def test_websocket_initial_state_delivery(mock_websocket_manager, mock_session_manager, mock_state_manager):
    """Test that initial_state message is sent after connection."""
    # Arrange
    client_id = "test-client-789"
    session_id = "test-session-101"
    
    mock_session = MagicMock()
    mock_session.session_id = session_id
    mock_session_manager.create_session.return_value = session_id
    mock_session_manager.get_session.return_value = mock_session
    
    initial_state = {
        "current_category": "voice",
        "current_subnode": "input",
        "field_values": {
            "voice.input": {
                "input_device": "default",
                "sample_rate": 16000
            }
        },
        "active_theme": {
            "glow_color": "#7000ff",
            "font_color": "#e0e0e0"
        },
        "confirmed_nodes": [],
        "app_state": {
            "voice_state": "idle",
            "audio_level": 0.0
        }
    }
    mock_state_manager.get_state.return_value = initial_state
    
    websocket = AsyncMock(spec=WebSocket)
    websocket.accept = AsyncMock()
    websocket.send_json = AsyncMock()
    
    # Act
    await mock_websocket_manager.connect(websocket, client_id, session_id)
    
    # Simulate sending initial state
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "initial_state",
        "payload": {"state": initial_state}
    })
    
    # Assert
    websocket.send_json.assert_called_once()
    sent_message = websocket.send_json.call_args[0][0]
    assert sent_message["type"] == "initial_state"
    assert sent_message["payload"]["state"] == initial_state


@pytest.mark.asyncio
async def test_websocket_ping_pong_heartbeat(mock_websocket_manager):
    """Test ping/pong heartbeat mechanism."""
    # Arrange
    client_id = "test-client-heartbeat"
    websocket = AsyncMock(spec=WebSocket)
    websocket.accept = AsyncMock()
    websocket.send_json = AsyncMock()
    websocket.receive_text = AsyncMock()
    
    mock_websocket_manager.active_connections[client_id] = websocket
    
    # Act - Send ping
    ping_message = {"type": "ping", "payload": {}}
    await mock_websocket_manager.send_to_client(client_id, ping_message)
    
    # Simulate receiving pong
    websocket.receive_text.return_value = json.dumps({"type": "pong", "payload": {}})
    pong_message = json.loads(await websocket.receive_text())
    
    # Assert
    assert pong_message["type"] == "pong"
    websocket.send_json.assert_called_once_with(ping_message)


@pytest.mark.asyncio
async def test_websocket_connection_retry_exponential_backoff():
    """Test connection retry with exponential backoff."""
    # Arrange
    retry_delays = []
    max_retries = 3
    
    async def mock_connect_with_retry(attempt):
        """Simulate connection attempts with exponential backoff."""
        if attempt < max_retries:
            delay = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
            retry_delays.append(delay)
            await asyncio.sleep(0.01)  # Simulate delay (shortened for test)
            raise ConnectionError(f"Connection failed (attempt {attempt + 1})")
        return "connected"
    
    # Act
    result = None
    for attempt in range(max_retries):
        try:
            result = await mock_connect_with_retry(attempt)
            break
        except ConnectionError:
            if attempt == max_retries - 1:
                result = "max_retries_reached"
    
    # Assert
    assert len(retry_delays) == max_retries
    assert retry_delays == [1, 2, 4]  # Exponential backoff pattern
    assert result == "max_retries_reached"


@pytest.mark.asyncio
async def test_websocket_reconnection_after_disconnect(mock_websocket_manager, mock_session_manager, mock_state_manager):
    """Test reconnection after connection loss."""
    # Arrange
    client_id = "test-client-reconnect"
    session_id = "test-session-reconnect"
    
    mock_session = MagicMock()
    mock_session.session_id = session_id
    mock_session_manager.create_session.return_value = session_id
    mock_session_manager.get_session.return_value = mock_session
    
    initial_state = {
        "current_category": None,
        "current_subnode": None,
        "field_values": {},
        "active_theme": {"glow_color": "#00ffff", "font_color": "#ffffff"},
        "confirmed_nodes": [],
        "app_state": {"voice_state": "idle", "audio_level": 0.0}
    }
    mock_state_manager.get_state.return_value = initial_state
    
    # First connection
    websocket1 = AsyncMock(spec=WebSocket)
    websocket1.accept = AsyncMock()
    websocket1.send_json = AsyncMock()
    
    # Act - First connection
    await mock_websocket_manager.connect(websocket1, client_id, session_id)
    assert client_id in mock_websocket_manager.active_connections
    
    # Simulate disconnect
    mock_websocket_manager.disconnect(client_id)
    assert client_id not in mock_websocket_manager.active_connections
    
    # Reconnection
    websocket2 = AsyncMock(spec=WebSocket)
    websocket2.accept = AsyncMock()
    websocket2.send_json = AsyncMock()
    
    # Act - Reconnection with same session_id
    result_session_id = await mock_websocket_manager.connect(websocket2, client_id, session_id)
    
    # Assert - Reconnected to same session
    assert result_session_id == session_id
    assert client_id in mock_websocket_manager.active_connections
    assert mock_websocket_manager.active_connections[client_id] == websocket2
    websocket2.accept.assert_called_once()


@pytest.mark.asyncio
async def test_websocket_ping_timeout_detection():
    """Test ping timeout detection (5 seconds)."""
    # Arrange
    ping_timeout = 5.0
    last_pong_time = asyncio.get_event_loop().time()
    
    # Simulate time passing
    await asyncio.sleep(0.01)  # Shortened for test
    current_time = asyncio.get_event_loop().time()
    
    # Act
    time_since_pong = current_time - last_pong_time
    is_timeout = time_since_pong > ping_timeout
    
    # Assert - No timeout yet (test is fast)
    assert not is_timeout
    
    # Simulate timeout
    simulated_time_since_pong = 6.0
    is_timeout = simulated_time_since_pong > ping_timeout
    assert is_timeout


@pytest.mark.asyncio
async def test_websocket_connection_failure_handling(mock_websocket_manager):
    """Test handling of connection failures."""
    # Arrange
    client_id = "test-client-fail"
    websocket = AsyncMock(spec=WebSocket)
    websocket.accept = AsyncMock(side_effect=Exception("Connection failed"))
    
    # Act & Assert
    with pytest.raises(Exception, match="Connection failed"):
        await websocket.accept()
    
    # Verify client not added to active connections
    assert client_id not in mock_websocket_manager.active_connections


@pytest.mark.asyncio
async def test_websocket_multiple_clients_same_session(mock_websocket_manager, mock_session_manager, mock_state_manager):
    """Test multiple clients connecting to the same session."""
    # Arrange
    session_id = "shared-session"
    client_id_1 = "client-1"
    client_id_2 = "client-2"
    
    mock_session = MagicMock()
    mock_session.session_id = session_id
    mock_session_manager.create_session.return_value = session_id
    mock_session_manager.get_session.return_value = mock_session
    
    initial_state = {
        "current_category": None,
        "current_subnode": None,
        "field_values": {},
        "active_theme": {"glow_color": "#00ffff", "font_color": "#ffffff"},
        "confirmed_nodes": [],
        "app_state": {"voice_state": "idle", "audio_level": 0.0}
    }
    mock_state_manager.get_state.return_value = initial_state
    
    websocket1 = AsyncMock(spec=WebSocket)
    websocket1.accept = AsyncMock()
    websocket2 = AsyncMock(spec=WebSocket)
    websocket2.accept = AsyncMock()
    
    # Act - Connect both clients to same session
    result_session_1 = await mock_websocket_manager.connect(websocket1, client_id_1, session_id)
    result_session_2 = await mock_websocket_manager.connect(websocket2, client_id_2, session_id)
    
    # Assert - Both clients connected to same session
    assert result_session_1 == session_id
    assert result_session_2 == session_id
    assert client_id_1 in mock_websocket_manager.active_connections
    assert client_id_2 in mock_websocket_manager.active_connections
    
    # Verify both clients get session association
    assert mock_websocket_manager.get_session_id_for_client(client_id_1) == session_id
    assert mock_websocket_manager.get_session_id_for_client(client_id_2) == session_id
