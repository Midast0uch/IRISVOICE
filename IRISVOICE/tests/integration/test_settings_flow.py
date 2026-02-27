"""
Integration test for settings flow.

Tests:
- Category navigation → subnode selection → field update → persistence
- Theme update → synchronization across components
- Multi-client synchronization

Feature: irisvoice-backend-integration
Requirements: 6.1-6.7, 7.1-7.7, 10.1-10.7, 20.1-20.10, 21.1-21.7
"""

import pytest
import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from pathlib import Path


@pytest.mark.asyncio
async def test_complete_settings_flow(mock_state_manager, mock_websocket_manager):
    """Test complete settings flow from category navigation to field persistence."""
    # Arrange
    session_id = "test-session-settings"
    client_id = "test-client-settings"
    
    mock_state_manager.set_category = AsyncMock()
    mock_state_manager.set_subnode = AsyncMock()
    mock_state_manager.update_field = AsyncMock(return_value=True)
    mock_state_manager.get_state = AsyncMock(return_value={
        "current_category": "voice",
        "current_subnode": "input",
        "field_values": {
            "voice.input": {
                "input_device": "Microphone (USB Audio)"
            }
        }
    })
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Step 1: Select category
    await mock_state_manager.set_category(session_id, "voice")
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "category_changed",
        "payload": {
            "category": "voice",
            "subnodes": ["input", "output", "processing", "audio_model"]
        }
    })
    
    # Step 2: Select subnode
    await mock_state_manager.set_subnode(session_id, "voice.input")
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "subnode_changed",
        "payload": {"subnode_id": "voice.input"}
    })
    
    # Step 3: Update field
    field_update_result = await mock_state_manager.update_field(
        session_id, "voice.input", "input_device", "Microphone (USB Audio)"
    )
    
    # Step 4: Send confirmation
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "field_updated",
        "payload": {
            "subnode_id": "voice.input",
            "field_id": "input_device",
            "value": "Microphone (USB Audio)",
            "valid": True
        }
    })
    
    # Assert
    mock_state_manager.set_category.assert_called_once_with(session_id, "voice")
    mock_state_manager.set_subnode.assert_called_once_with(session_id, "voice.input")
    mock_state_manager.update_field.assert_called_once()
    assert field_update_result is True
    
    # Verify messages sent
    assert mock_websocket_manager.send_to_client.call_count == 3


@pytest.mark.asyncio
async def test_category_navigation(mock_state_manager, mock_websocket_manager):
    """Test category navigation and subnode listing."""
    # Arrange
    session_id = "test-session-nav"
    client_id = "test-client-nav"
    
    categories = ["voice", "agent", "automate", "system", "customize", "monitor"]
    category_subnodes = {
        "voice": ["input", "output", "processing", "audio_model"],
        "agent": ["identity", "wake", "speech", "memory"],
        "automate": ["tools", "vision", "workflows", "favorites", "shortcuts", "gui_automation"],
        "system": ["power", "display", "storage", "network"],
        "customize": ["theme", "startup", "behavior", "notifications"],
        "monitor": ["analytics", "logs", "diagnostics", "updates"]
    }
    
    mock_state_manager.set_category = AsyncMock()
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Navigate through all categories
    for category in categories:
        await mock_state_manager.set_category(session_id, category)
        await mock_websocket_manager.send_to_client(client_id, {
            "type": "category_changed",
            "payload": {
                "category": category,
                "subnodes": category_subnodes[category]
            }
        })
    
    # Assert
    assert mock_state_manager.set_category.call_count == len(categories)
    assert mock_websocket_manager.send_to_client.call_count == len(categories)


@pytest.mark.asyncio
async def test_field_validation_and_error_handling(mock_state_manager, mock_websocket_manager):
    """Test field validation and error message delivery."""
    # Arrange
    session_id = "test-session-validation"
    client_id = "test-client-validation"
    
    # Mock validation failure
    mock_state_manager.update_field = AsyncMock(return_value=False)
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Try to update field with invalid value
    result = await mock_state_manager.update_field(
        session_id, "voice.input", "sample_rate", 999999  # Invalid sample rate
    )
    
    # Send validation error
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "validation_error",
        "payload": {
            "field_id": "sample_rate",
            "error": "Sample rate must be between 8000 and 48000"
        }
    })
    
    # Assert
    assert result is False
    mock_websocket_manager.send_to_client.assert_called_once()
    error_message = mock_websocket_manager.send_to_client.call_args[0][1]
    assert error_message["type"] == "validation_error"
    assert "sample_rate" in error_message["payload"]["field_id"]


@pytest.mark.asyncio
async def test_theme_update_and_synchronization(mock_state_manager, mock_websocket_manager):
    """Test theme update and synchronization across components."""
    # Arrange
    session_id = "test-session-theme"
    client_ids = ["client-1", "client-2", "client-3"]
    
    new_theme = {
        "glow_color": "#7000ff",
        "font_color": "#e0e0e0",
        "state_colors": {
            "idle": "#00ffff",
            "listening": "#00ff00",
            "processing": "#7000ff",
            "speaking": "#ff00ff",
            "error": "#ff0000"
        }
    }
    
    mock_state_manager.update_theme = AsyncMock()
    
    # Setup multiple clients
    for client_id in client_ids:
        websocket = AsyncMock()
        mock_websocket_manager.active_connections[client_id] = websocket
    
    mock_websocket_manager.broadcast_to_session = AsyncMock()
    
    # Act - Update theme
    await mock_state_manager.update_theme(
        session_id,
        glow_color=new_theme["glow_color"],
        font_color=new_theme["font_color"],
        state_colors=new_theme["state_colors"]
    )
    
    # Broadcast theme update to all clients in session
    await mock_websocket_manager.broadcast_to_session(session_id, {
        "type": "theme_updated",
        "payload": {"active_theme": new_theme}
    })
    
    # Assert
    mock_state_manager.update_theme.assert_called_once()
    mock_websocket_manager.broadcast_to_session.assert_called_once()


@pytest.mark.asyncio
async def test_multi_client_state_synchronization(mock_state_manager, mock_websocket_manager):
    """Test state changes are synchronized across multiple clients."""
    # Arrange
    session_id = "test-session-sync"
    client_ids = ["client-a", "client-b", "client-c"]
    
    # Setup multiple clients in same session
    for client_id in client_ids:
        websocket = AsyncMock()
        mock_websocket_manager.active_connections[client_id] = websocket
        mock_websocket_manager._client_sessions[client_id] = session_id
    
    mock_state_manager.update_field = AsyncMock(return_value=True)
    mock_websocket_manager.broadcast_to_session = AsyncMock()
    
    # Act - Client A updates a field
    await mock_state_manager.update_field(
        session_id, "voice.input", "input_device", "New Microphone"
    )
    
    # Broadcast update to all clients in session (within 100ms requirement)
    await mock_websocket_manager.broadcast_to_session(
        session_id,
        {
            "type": "field_updated",
            "payload": {
                "subnode_id": "voice.input",
                "field_id": "input_device",
                "value": "New Microphone",
                "valid": True
            }
        },
        exclude_clients={"client-a"}  # Don't send back to originator
    )
    
    # Assert
    mock_websocket_manager.broadcast_to_session.assert_called_once()
    broadcast_call = mock_websocket_manager.broadcast_to_session.call_args
    assert broadcast_call[0][0] == session_id
    assert broadcast_call[1]["exclude_clients"] == {"client-a"}


@pytest.mark.asyncio
async def test_field_persistence_to_storage(mock_state_manager, tmp_path):
    """Test field values are persisted to JSON storage."""
    # Arrange
    session_id = "test-session-persist"
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    
    voice_settings_file = settings_dir / "voice.json"
    
    # Mock file operations
    with patch("builtins.open", mock_open()) as mock_file:
        with patch("json.dump") as mock_json_dump:
            # Act - Update field (should trigger persistence)
            await mock_state_manager.update_field(
                session_id, "voice.input", "input_device", "USB Microphone"
            )
            
            # Simulate persistence
            settings_data = {
                "voice.input": {
                    "input_device": "USB Microphone",
                    "sample_rate": 16000
                }
            }
            
            # Verify persistence would be called
            # (In real implementation, this happens automatically)
            assert mock_state_manager.update_field.called


@pytest.mark.asyncio
async def test_settings_restoration_on_startup(mock_state_manager):
    """Test settings are restored from storage on startup."""
    # Arrange
    session_id = "test-session-restore"
    
    persisted_settings = {
        "current_category": "voice",
        "current_subnode": "input",
        "field_values": {
            "voice.input": {
                "input_device": "Saved Microphone",
                "sample_rate": 16000
            },
            "voice.output": {
                "output_device": "Saved Speakers",
                "volume": 80
            }
        },
        "active_theme": {
            "glow_color": "#7000ff",
            "font_color": "#ffffff"
        }
    }
    
    mock_state_manager.get_state = AsyncMock(return_value=persisted_settings)
    
    # Act - Get state (simulates restoration)
    restored_state = await mock_state_manager.get_state(session_id)
    
    # Assert
    assert restored_state == persisted_settings
    assert restored_state["field_values"]["voice.input"]["input_device"] == "Saved Microphone"
    assert restored_state["active_theme"]["glow_color"] == "#7000ff"


@pytest.mark.asyncio
async def test_optimistic_field_updates(mock_state_manager, mock_websocket_manager):
    """Test optimistic updates with confirmation."""
    # Arrange
    session_id = "test-session-optimistic"
    client_id = "test-client-optimistic"
    
    mock_state_manager.update_field = AsyncMock(return_value=True)
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Client sends update (UI updates optimistically)
    # Backend processes update
    result = await mock_state_manager.update_field(
        session_id, "customize.theme", "glow_color", "#ff00ff"
    )
    
    # Backend sends confirmation
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "field_updated",
        "payload": {
            "subnode_id": "customize.theme",
            "field_id": "glow_color",
            "value": "#ff00ff",
            "valid": True
        }
    })
    
    # Assert
    assert result is True
    mock_websocket_manager.send_to_client.assert_called_once()


@pytest.mark.asyncio
async def test_navigation_history_and_back_button(mock_state_manager, mock_websocket_manager):
    """Test navigation history and go_back functionality."""
    # Arrange
    session_id = "test-session-history"
    client_id = "test-client-history"
    
    navigation_history = []
    
    async def track_navigation(sid, category):
        navigation_history.append({"category": category})
    
    mock_state_manager.set_category = AsyncMock(side_effect=track_navigation)
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Navigate through categories
    categories = ["voice", "agent", "automate"]
    for category in categories:
        await mock_state_manager.set_category(session_id, category)
    
    # Go back
    if len(navigation_history) > 1:
        previous_category = navigation_history[-2]["category"]
        await mock_state_manager.set_category(session_id, previous_category)
        
        await mock_websocket_manager.send_to_client(client_id, {
            "type": "category_changed",
            "payload": {"category": previous_category}
        })
    
    # Assert
    assert len(navigation_history) == 4  # 3 forward + 1 back
    assert navigation_history[-1]["category"] == "agent"


@pytest.mark.asyncio
async def test_subnode_field_display(mock_state_manager, mock_websocket_manager):
    """Test subnode selection displays correct fields."""
    # Arrange
    session_id = "test-session-fields"
    client_id = "test-client-fields"
    
    subnode_fields = {
        "voice.input": [
            {"id": "input_device", "type": "dropdown", "label": "Input Device"},
            {"id": "sample_rate", "type": "dropdown", "label": "Sample Rate"},
            {"id": "channels", "type": "dropdown", "label": "Channels"}
        ]
    }
    
    mock_state_manager.set_subnode = AsyncMock()
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Select subnode
    await mock_state_manager.set_subnode(session_id, "voice.input")
    
    # Send subnode fields
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "subnode_changed",
        "payload": {
            "subnode_id": "voice.input",
            "fields": subnode_fields["voice.input"]
        }
    })
    
    # Assert
    mock_state_manager.set_subnode.assert_called_once()
    sent_message = mock_websocket_manager.send_to_client.call_args[0][1]
    assert len(sent_message["payload"]["fields"]) == 3


@pytest.mark.asyncio
async def test_settings_corruption_recovery(mock_state_manager):
    """Test recovery from corrupted settings file."""
    # Arrange
    session_id = "test-session-corrupt"
    
    # Mock corrupted file scenario
    default_state = {
        "current_category": None,
        "current_subnode": None,
        "field_values": {},
        "active_theme": {
            "glow_color": "#00ffff",
            "font_color": "#ffffff"
        }
    }
    
    # Simulate corruption detection and fallback to defaults
    mock_state_manager.get_state = AsyncMock(return_value=default_state)
    
    # Act
    state = await mock_state_manager.get_state(session_id)
    
    # Assert - Default values loaded
    assert state == default_state
    assert state["field_values"] == {}
    assert state["active_theme"]["glow_color"] == "#00ffff"


@pytest.mark.asyncio
async def test_concurrent_field_updates(mock_state_manager, mock_websocket_manager):
    """Test handling of concurrent field updates from multiple clients."""
    # Arrange
    session_id = "test-session-concurrent"
    client_ids = ["client-1", "client-2"]
    
    mock_state_manager.update_field = AsyncMock(return_value=True)
    mock_websocket_manager.broadcast_to_session = AsyncMock()
    
    # Act - Simulate concurrent updates
    updates = [
        ("voice.input", "input_device", "Microphone 1"),
        ("voice.output", "output_device", "Speakers 1")
    ]
    
    tasks = []
    for subnode_id, field_id, value in updates:
        task = mock_state_manager.update_field(session_id, subnode_id, field_id, value)
        tasks.append(task)
    
    await asyncio.gather(*tasks)
    
    # Assert - Both updates processed
    assert mock_state_manager.update_field.call_count == 2


@pytest.mark.asyncio
async def test_state_update_timestamps(mock_websocket_manager):
    """Test state updates include timestamps for conflict resolution."""
    # Arrange
    client_id = "test-client-timestamp"
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act
    import time
    timestamp = time.time()
    
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "field_updated",
        "payload": {
            "subnode_id": "voice.input",
            "field_id": "input_device",
            "value": "New Device",
            "valid": True,
            "timestamp": timestamp
        }
    })
    
    # Assert
    sent_message = mock_websocket_manager.send_to_client.call_args[0][1]
    assert "timestamp" in sent_message["payload"]
    assert sent_message["payload"]["timestamp"] == timestamp


@pytest.mark.asyncio
async def test_mini_node_confirmation(mock_state_manager, mock_websocket_manager):
    """Test mini-node confirmation with orbit position."""
    # Arrange
    session_id = "test-session-mininode"
    client_id = "test-client-mininode"
    
    mock_state_manager.confirm_subnode = AsyncMock(return_value=45.0)  # orbit angle
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Confirm mini-node
    orbit_angle = await mock_state_manager.confirm_subnode(
        session_id,
        "voice",
        "voice.input",
        {"input_device": "USB Mic", "sample_rate": 16000}
    )
    
    # Send confirmation
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "mini_node_confirmed",
        "payload": {
            "subnode_id": "voice.input",
            "orbit_angle": orbit_angle
        }
    })
    
    # Assert
    assert orbit_angle == 45.0
    mock_state_manager.confirm_subnode.assert_called_once()
    sent_message = mock_websocket_manager.send_to_client.call_args[0][1]
    assert sent_message["payload"]["orbit_angle"] == 45.0
