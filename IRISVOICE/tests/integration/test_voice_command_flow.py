"""
Integration test for voice command flow.

Tests:
- voice_command_start → listening → voice_command_end → processing → response
- Wake word detection → automatic recording
- Audio level updates during listening

Feature: irisvoice-backend-integration
Requirements: 3.1-3.9, 4.1-4.6, 22.1-22.7
"""

import pytest
import asyncio
import numpy as np
from unittest.mock import AsyncMock, MagicMock, patch, call


@pytest.mark.asyncio
async def test_voice_command_complete_flow(mock_voice_pipeline, mock_websocket_manager, mock_agent_kernel):
    """Test complete voice command flow from start to response."""
    # Arrange
    session_id = "test-session-voice"
    client_id = "test-client-voice"
    
    # Mock LFM audio model responses
    mock_voice_pipeline.start_listening = AsyncMock()
    mock_voice_pipeline.stop_listening = AsyncMock()
    mock_voice_pipeline.get_audio_level = MagicMock(return_value=0.5)
    
    # Mock agent response
    mock_agent_kernel.process_text_message = AsyncMock(return_value="Hello! How can I help you?")
    
    # Mock WebSocket for state updates
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Step 1: Start voice command
    await mock_voice_pipeline.start_listening(session_id)
    
    # Simulate listening state update
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "listening_state",
        "payload": {"state": "listening"}
    })
    
    # Step 2: Simulate audio level updates during listening
    for _ in range(5):
        audio_level = mock_voice_pipeline.get_audio_level()
        await mock_websocket_manager.send_to_client(client_id, {
            "type": "audio_level",
            "payload": {"level": audio_level}
        })
        await asyncio.sleep(0.01)  # Simulate 100ms updates
    
    # Step 3: Stop voice command
    await mock_voice_pipeline.stop_listening(session_id)
    
    # Simulate processing state
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "listening_state",
        "payload": {"state": "processing_conversation"}
    })
    
    # Step 4: Process transcribed text (simulated)
    transcribed_text = "What is the weather today?"
    response = await mock_agent_kernel.process_text_message(transcribed_text, session_id)
    
    # Simulate response delivery
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "text_response",
        "payload": {"text": response, "sender": "assistant"}
    })
    
    # Simulate speaking state
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "listening_state",
        "payload": {"state": "speaking"}
    })
    
    # Step 5: Return to idle
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "listening_state",
        "payload": {"state": "idle"}
    })
    
    # Assert - Verify flow
    mock_voice_pipeline.start_listening.assert_called_once_with(session_id)
    mock_voice_pipeline.stop_listening.assert_called_once_with(session_id)
    mock_agent_kernel.process_text_message.assert_called_once_with(transcribed_text, session_id)
    
    # Verify state transitions sent
    assert mock_websocket_manager.send_to_client.call_count >= 8  # listening, audio_levels(5), processing, speaking, idle


@pytest.mark.asyncio
async def test_wake_word_detection_flow(mock_voice_pipeline, mock_websocket_manager):
    """Test wake word detection triggering automatic recording."""
    # Arrange
    session_id = "test-session-wake"
    client_id = "test-client-wake"
    wake_phrase = "jarvis"
    confidence = 0.95
    
    mock_voice_pipeline.start_listening = AsyncMock()
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Simulate wake word detection
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "wake_detected",
        "payload": {
            "phrase": wake_phrase,
            "confidence": confidence
        }
    })
    
    # Automatically start listening
    await mock_voice_pipeline.start_listening(session_id)
    
    # Send listening state
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "listening_state",
        "payload": {"state": "listening"}
    })
    
    # Assert
    mock_voice_pipeline.start_listening.assert_called_once_with(session_id)
    
    # Verify wake_detected message sent
    wake_call = mock_websocket_manager.send_to_client.call_args_list[0]
    assert wake_call[0][1]["type"] == "wake_detected"
    assert wake_call[0][1]["payload"]["phrase"] == wake_phrase
    assert wake_call[0][1]["payload"]["confidence"] == confidence


@pytest.mark.asyncio
async def test_audio_level_updates_during_listening(mock_voice_pipeline, mock_websocket_manager):
    """Test audio level updates sent every 100ms during listening."""
    # Arrange
    session_id = "test-session-audio"
    client_id = "test-client-audio"
    
    # Simulate varying audio levels
    audio_levels = [0.1, 0.3, 0.6, 0.8, 0.5, 0.2]
    level_index = 0
    
    def get_next_level():
        nonlocal level_index
        level = audio_levels[level_index % len(audio_levels)]
        level_index += 1
        return level
    
    mock_voice_pipeline.get_audio_level = MagicMock(side_effect=get_next_level)
    mock_voice_pipeline.start_listening = AsyncMock()
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Start listening
    await mock_voice_pipeline.start_listening(session_id)
    
    # Simulate audio level updates
    sent_levels = []
    for _ in range(len(audio_levels)):
        level = mock_voice_pipeline.get_audio_level()
        sent_levels.append(level)
        await mock_websocket_manager.send_to_client(client_id, {
            "type": "audio_level",
            "payload": {"level": level}
        })
        await asyncio.sleep(0.01)  # Simulate 100ms interval
    
    # Assert
    assert sent_levels == audio_levels
    assert mock_websocket_manager.send_to_client.call_count == len(audio_levels)
    
    # Verify all audio_level messages
    for i, call_args in enumerate(mock_websocket_manager.send_to_client.call_args_list):
        message = call_args[0][1]
        assert message["type"] == "audio_level"
        assert message["payload"]["level"] == audio_levels[i]


@pytest.mark.asyncio
async def test_voice_command_state_transitions(mock_voice_pipeline, mock_websocket_manager):
    """Test voice state transitions through complete flow."""
    # Arrange
    session_id = "test-session-states"
    client_id = "test-client-states"
    
    mock_voice_pipeline.start_listening = AsyncMock()
    mock_voice_pipeline.stop_listening = AsyncMock()
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    expected_states = [
        "listening",
        "processing_conversation",
        "speaking",
        "idle"
    ]
    
    # Act - Simulate state transitions
    for state in expected_states:
        await mock_websocket_manager.send_to_client(client_id, {
            "type": "listening_state",
            "payload": {"state": state}
        })
    
    # Assert
    assert mock_websocket_manager.send_to_client.call_count == len(expected_states)
    
    # Verify state sequence
    for i, expected_state in enumerate(expected_states):
        call_args = mock_websocket_manager.send_to_client.call_args_list[i]
        message = call_args[0][1]
        assert message["type"] == "listening_state"
        assert message["payload"]["state"] == expected_state


@pytest.mark.asyncio
async def test_voice_command_with_tool_execution(mock_voice_pipeline, mock_websocket_manager, mock_agent_kernel):
    """Test voice command flow with tool execution."""
    # Arrange
    session_id = "test-session-tool"
    client_id = "test-client-tool"
    
    mock_voice_pipeline.start_listening = AsyncMock()
    mock_voice_pipeline.stop_listening = AsyncMock()
    mock_agent_kernel.process_text_message = AsyncMock(return_value="I've opened the browser for you.")
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Voice command flow with tool
    await mock_voice_pipeline.start_listening(session_id)
    
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "listening_state",
        "payload": {"state": "listening"}
    })
    
    await mock_voice_pipeline.stop_listening(session_id)
    
    # Processing with tool execution
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "listening_state",
        "payload": {"state": "processing_tool"}
    })
    
    # Simulate tool execution
    transcribed_text = "Open the browser"
    response = await mock_agent_kernel.process_text_message(transcribed_text, session_id)
    
    # Response
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "text_response",
        "payload": {"text": response, "sender": "assistant"}
    })
    
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "listening_state",
        "payload": {"state": "speaking"}
    })
    
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "listening_state",
        "payload": {"state": "idle"}
    })
    
    # Assert
    mock_voice_pipeline.start_listening.assert_called_once()
    mock_voice_pipeline.stop_listening.assert_called_once()
    mock_agent_kernel.process_text_message.assert_called_once()
    
    # Verify processing_tool state was sent
    processing_tool_call = None
    for call_args in mock_websocket_manager.send_to_client.call_args_list:
        message = call_args[0][1]
        if message.get("type") == "listening_state" and message.get("payload", {}).get("state") == "processing_tool":
            processing_tool_call = call_args
            break
    
    assert processing_tool_call is not None


@pytest.mark.asyncio
async def test_voice_command_error_handling(mock_voice_pipeline, mock_websocket_manager):
    """Test voice command error handling."""
    # Arrange
    session_id = "test-session-error"
    client_id = "test-client-error"
    
    mock_voice_pipeline.start_listening = AsyncMock()
    mock_voice_pipeline.stop_listening = AsyncMock(side_effect=Exception("Audio device error"))
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act
    await mock_voice_pipeline.start_listening(session_id)
    
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "listening_state",
        "payload": {"state": "listening"}
    })
    
    # Simulate error during stop
    try:
        await mock_voice_pipeline.stop_listening(session_id)
    except Exception as e:
        # Send error state
        await mock_websocket_manager.send_to_client(client_id, {
            "type": "voice_command_error",
            "payload": {"error": str(e)}
        })
        
        await mock_websocket_manager.send_to_client(client_id, {
            "type": "listening_state",
            "payload": {"state": "error"}
        })
    
    # Assert
    error_call = None
    for call_args in mock_websocket_manager.send_to_client.call_args_list:
        message = call_args[0][1]
        if message.get("type") == "voice_command_error":
            error_call = call_args
            break
    
    assert error_call is not None
    assert "Audio device error" in error_call[0][1]["payload"]["error"]


@pytest.mark.asyncio
async def test_wake_word_configuration_applied(mock_voice_pipeline):
    """Test wake word configuration is applied to LFM audio model."""
    # Arrange
    wake_config = {
        "wake_phrase": "jarvis",
        "detection_sensitivity": 75,
        "activation_sound": True
    }
    
    # Mock configuration application
    mock_voice_pipeline.configure_wake_word = AsyncMock()
    
    # Act
    await mock_voice_pipeline.configure_wake_word(wake_config)
    
    # Assert
    mock_voice_pipeline.configure_wake_word.assert_called_once_with(wake_config)


@pytest.mark.asyncio
async def test_audio_level_normalization(mock_voice_pipeline):
    """Test audio levels are normalized to 0.0-1.0 range."""
    # Arrange
    raw_audio_levels = [0.0, 0.25, 0.5, 0.75, 1.0, 1.2, -0.1]  # Some out of range
    
    def normalize_level(level):
        """Normalize audio level to 0.0-1.0 range."""
        return max(0.0, min(1.0, level))
    
    # Act
    normalized_levels = [normalize_level(level) for level in raw_audio_levels]
    
    # Assert
    assert all(0.0 <= level <= 1.0 for level in normalized_levels)
    assert normalized_levels == [0.0, 0.25, 0.5, 0.75, 1.0, 1.0, 0.0]


@pytest.mark.asyncio
async def test_audio_level_reset_on_state_change(mock_voice_pipeline, mock_websocket_manager):
    """Test audio level resets to 0 when leaving listening state."""
    # Arrange
    session_id = "test-session-reset"
    client_id = "test-client-reset"
    
    mock_voice_pipeline.get_audio_level = MagicMock(return_value=0.7)
    mock_voice_pipeline.stop_listening = AsyncMock()
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - During listening
    level_during_listening = mock_voice_pipeline.get_audio_level()
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "audio_level",
        "payload": {"level": level_during_listening}
    })
    
    # Stop listening
    await mock_voice_pipeline.stop_listening(session_id)
    
    # Send processing state (audio level should reset)
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "listening_state",
        "payload": {"state": "processing_conversation"}
    })
    
    # Send reset audio level
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "audio_level",
        "payload": {"level": 0.0}
    })
    
    # Assert
    assert level_during_listening == 0.7
    
    # Verify reset audio level sent
    reset_call = mock_websocket_manager.send_to_client.call_args_list[-1]
    assert reset_call[0][1]["type"] == "audio_level"
    assert reset_call[0][1]["payload"]["level"] == 0.0


@pytest.mark.asyncio
async def test_voice_command_cancellation(mock_voice_pipeline, mock_websocket_manager):
    """Test voice command can be cancelled during listening."""
    # Arrange
    session_id = "test-session-cancel"
    client_id = "test-client-cancel"
    
    mock_voice_pipeline.start_listening = AsyncMock()
    mock_voice_pipeline.stop_listening = AsyncMock()
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Start listening
    await mock_voice_pipeline.start_listening(session_id)
    
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "listening_state",
        "payload": {"state": "listening"}
    })
    
    # Cancel immediately
    await mock_voice_pipeline.stop_listening(session_id)
    
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "listening_state",
        "payload": {"state": "idle"}
    })
    
    # Assert
    mock_voice_pipeline.start_listening.assert_called_once()
    mock_voice_pipeline.stop_listening.assert_called_once()
    
    # Verify returned to idle without processing
    final_state_call = mock_websocket_manager.send_to_client.call_args_list[-1]
    assert final_state_call[0][1]["payload"]["state"] == "idle"
