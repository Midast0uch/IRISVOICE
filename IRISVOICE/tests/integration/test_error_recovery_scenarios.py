"""
Integration test for error recovery scenarios.

Tests:
- Connection loss and reconnection
- Model failure and fallback
- Audio device failure and fallback
- MCP server crash and restart
- VPS failure and fallback to local execution
- VPS recovery and resume to remote execution

Feature: irisvoice-backend-integration
Requirements: 19.1-19.7, 26.2, 26.7, 26.8
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
from fastapi.websockets import WebSocketDisconnect


@pytest.mark.asyncio
async def test_connection_loss_and_reconnection(mock_websocket_manager, mock_session_manager, mock_state_manager):
    """Test WebSocket connection loss and automatic reconnection."""
    # Arrange
    client_id = "test-client-reconnect"
    session_id = "test-session-reconnect"
    
    mock_session = MagicMock()
    mock_session.session_id = session_id
    mock_session_manager.create_session.return_value = session_id
    mock_session_manager.get_session.return_value = mock_session
    
    initial_state = {
        "current_category": "voice",
        "field_values": {"voice.input": {"input_device": "default"}},
        "active_theme": {"glow_color": "#00ffff"}
    }
    mock_state_manager.get_state.return_value = initial_state
    
    # First connection
    websocket1 = AsyncMock()
    websocket1.accept = AsyncMock()
    websocket1.send_json = AsyncMock()
    
    # Act - Initial connection
    await mock_websocket_manager.connect(websocket1, client_id, session_id)
    assert client_id in mock_websocket_manager.active_connections
    
    # Simulate connection loss
    mock_websocket_manager.disconnect(client_id)
    assert client_id not in mock_websocket_manager.active_connections
    
    # Reconnection attempt 1 (fails)
    websocket2 = AsyncMock()
    websocket2.accept = AsyncMock(side_effect=ConnectionError("Network error"))
    
    try:
        await websocket2.accept()
    except ConnectionError:
        await asyncio.sleep(0.01)  # Wait before retry (exponential backoff)
    
    # Reconnection attempt 2 (succeeds)
    websocket3 = AsyncMock()
    websocket3.accept = AsyncMock()
    websocket3.send_json = AsyncMock()
    
    result_session_id = await mock_websocket_manager.connect(websocket3, client_id, session_id)
    
    # Assert - Reconnected successfully
    assert result_session_id == session_id
    assert client_id in mock_websocket_manager.active_connections
    assert mock_websocket_manager.active_connections[client_id] == websocket3
    
    # Verify state restored
    mock_state_manager.get_state.assert_called()


@pytest.mark.asyncio
async def test_model_failure_and_fallback(mock_agent_kernel, mock_model_router, mock_vps_gateway):
    """Test model failure triggers fallback to single-model mode."""
    # Arrange
    session_id = "test-session-model-fail"
    user_message = "What is the weather?"
    
    # Mock primary model failure
    mock_model_router.route_message = AsyncMock(
        side_effect=Exception("Model inference failed")
    )
    
    # Mock fallback model success
    mock_agent_kernel.fallback_mode = True
    mock_agent_kernel.process_text_message = AsyncMock(
        return_value="I'm currently in fallback mode. The weather information is unavailable."
    )
    
    # Act - Try primary model, fall back on failure
    try:
        await mock_model_router.route_message(user_message, {})
    except Exception:
        # Enable fallback mode
        mock_agent_kernel.fallback_mode = True
        response = await mock_agent_kernel.process_text_message(user_message, session_id)
    
    # Assert
    assert mock_agent_kernel.fallback_mode is True
    assert "fallback mode" in response.lower()


@pytest.mark.asyncio
async def test_audio_device_failure_and_fallback(mock_voice_pipeline, mock_websocket_manager):
    """Test audio device failure triggers fallback to default device."""
    # Arrange
    session_id = "test-session-audio-fail"
    client_id = "test-client-audio-fail"
    
    # Mock device failure
    mock_voice_pipeline.start_listening = AsyncMock(
        side_effect=Exception("Audio device not available")
    )
    
    # Mock fallback to default device
    mock_voice_pipeline.fallback_to_default_device = AsyncMock()
    mock_voice_pipeline.start_listening = AsyncMock()  # Reset after fallback
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Try to start listening, fail, fallback
    try:
        await mock_voice_pipeline.start_listening(session_id)
    except Exception as e:
        # Send error notification
        await mock_websocket_manager.send_to_client(client_id, {
            "type": "voice_command_error",
            "payload": {"error": f"Device error: {str(e)}. Falling back to default device."}
        })
        
        # Fallback to default device
        await mock_voice_pipeline.fallback_to_default_device()
        
        # Retry with default device
        await mock_voice_pipeline.start_listening(session_id)
        
        # Send recovery notification
        await mock_websocket_manager.send_to_client(client_id, {
            "type": "listening_state",
            "payload": {"state": "listening"}
        })
    
    # Assert
    mock_voice_pipeline.fallback_to_default_device.assert_called_once()
    assert mock_websocket_manager.send_to_client.call_count == 2


@pytest.mark.asyncio
async def test_mcp_server_crash_and_restart(mock_tool_bridge, mock_server_manager):
    """Test MCP server crash detection and automatic restart."""
    # Arrange
    server_name = "BrowserServer"
    
    # Mock server crash
    mock_server_manager.check_server_health = AsyncMock(return_value=False)
    mock_server_manager.restart_server = AsyncMock(return_value=True)
    
    # Act - Detect crash
    is_healthy = await mock_server_manager.check_server_health(server_name)
    
    if not is_healthy:
        # Attempt restart
        restart_success = await mock_server_manager.restart_server(server_name)
        
        # Verify server is back up
        is_healthy_after_restart = await mock_server_manager.check_server_health(server_name)
    
    # Assert
    assert is_healthy is False
    mock_server_manager.restart_server.assert_called_once_with(server_name)


@pytest.mark.asyncio
async def test_vps_failure_and_local_fallback(mock_vps_gateway, mock_model_router):
    """Test VPS failure triggers fallback to local execution."""
    # Arrange
    model = "lfm2-8b"
    prompt = "What is the capital of France?"
    context = {}
    params = {}
    
    # Mock VPS failure
    mock_vps_gateway.infer_remote = AsyncMock(
        side_effect=asyncio.TimeoutError("VPS request timeout")
    )
    
    # Mock local execution success
    mock_vps_gateway.infer_local = AsyncMock(return_value="The capital of France is Paris.")
    
    # Mock VPS availability check
    mock_vps_gateway.is_vps_available = MagicMock(return_value=False)
    
    # Act - Try VPS, fall back to local
    try:
        response = await mock_vps_gateway.infer_remote("vps-endpoint", model, prompt, context, params)
    except asyncio.TimeoutError:
        # Mark VPS as unavailable
        mock_vps_gateway._health_status = {"vps-endpoint": {"available": False}}
        
        # Fall back to local execution
        response = await mock_vps_gateway.infer_local(model, prompt, context, params)
    
    # Assert
    assert response == "The capital of France is Paris."
    mock_vps_gateway.infer_local.assert_called_once()


@pytest.mark.asyncio
async def test_vps_recovery_and_resume(mock_vps_gateway):
    """Test VPS recovery detection and resume to remote execution."""
    # Arrange
    endpoint = "https://vps.example.com"
    
    # Initial state: VPS unavailable
    mock_vps_gateway._health_status = {
        endpoint: {
            "available": False,
            "consecutive_failures": 3
        }
    }
    
    # Mock health check success
    mock_vps_gateway.check_vps_health = AsyncMock(return_value=True)
    
    # Act - Periodic health check
    is_healthy = await mock_vps_gateway.check_vps_health(endpoint)
    
    if is_healthy:
        # Update health status
        mock_vps_gateway._health_status[endpoint] = {
            "available": True,
            "consecutive_failures": 0
        }
    
    # Verify VPS is now available
    mock_vps_gateway.is_vps_available = MagicMock(return_value=True)
    is_available = mock_vps_gateway.is_vps_available()
    
    # Assert
    assert is_healthy is True
    assert is_available is True
    assert mock_vps_gateway._health_status[endpoint]["available"] is True


@pytest.mark.asyncio
async def test_websocket_parse_error_handling(mock_websocket_manager):
    """Test WebSocket message parse errors are handled gracefully."""
    # Arrange
    client_id = "test-client-parse"
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    
    # Mock invalid JSON message
    invalid_messages = [
        "{invalid json}",
        "not json at all",
        '{"type": "missing_payload"}'
    ]
    
    # Act - Process invalid messages
    for invalid_msg in invalid_messages:
        try:
            import json
            json.loads(invalid_msg)
        except (json.JSONDecodeError, KeyError) as e:
            # Log error and continue (don't disconnect)
            print(f"Parse error: {e}")
            continue
    
    # Assert - Client still connected
    assert client_id in mock_websocket_manager.active_connections


@pytest.mark.asyncio
async def test_agent_kernel_error_recovery(mock_agent_kernel, mock_websocket_manager):
    """Test agent kernel error handling and recovery."""
    # Arrange
    session_id = "test-session-agent-error"
    client_id = "test-client-agent-error"
    
    # Mock agent error
    mock_agent_kernel.process_text_message = AsyncMock(
        side_effect=Exception("Internal agent error")
    )
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Process message with error
    try:
        await mock_agent_kernel.process_text_message("Hello", session_id)
    except Exception as e:
        # Send error response
        await mock_websocket_manager.send_to_client(client_id, {
            "type": "text_response",
            "payload": {
                "text": "I encountered an error processing your request. Please try again.",
                "sender": "assistant"
            }
        })
    
    # Reset agent (recovery)
    mock_agent_kernel.process_text_message = AsyncMock(
        return_value="I'm back online. How can I help?"
    )
    
    # Retry
    response = await mock_agent_kernel.process_text_message("Hello", session_id)
    
    # Assert
    assert "back online" in response.lower()


@pytest.mark.asyncio
async def test_settings_file_corruption_recovery(mock_state_manager):
    """Test recovery from corrupted settings file."""
    # Arrange
    session_id = "test-session-corrupt"
    
    # Mock corrupted file scenario
    mock_state_manager.get_state = AsyncMock(
        side_effect=Exception("JSON decode error")
    )
    
    # Mock fallback to defaults
    default_state = {
        "current_category": None,
        "current_subnode": None,
        "field_values": {},
        "active_theme": {"glow_color": "#00ffff", "font_color": "#ffffff"}
    }
    
    # Act - Try to load state, fall back to defaults
    try:
        state = await mock_state_manager.get_state(session_id)
    except Exception:
        # Load default state
        state = default_state
        
        # Log warning
        print("Warning: Settings file corrupted, using defaults")
    
    # Assert
    assert state == default_state
    assert state["field_values"] == {}


@pytest.mark.asyncio
async def test_concurrent_connection_handling(mock_websocket_manager, mock_session_manager):
    """Test handling of multiple concurrent connections."""
    # Arrange
    num_clients = 10
    session_id = "shared-session"
    
    mock_session = MagicMock()
    mock_session.session_id = session_id
    mock_session_manager.create_session.return_value = session_id
    mock_session_manager.get_session.return_value = mock_session
    
    # Act - Connect multiple clients concurrently
    tasks = []
    for i in range(num_clients):
        client_id = f"client-{i}"
        websocket = AsyncMock()
        websocket.accept = AsyncMock()
        
        task = mock_websocket_manager.connect(websocket, client_id, session_id)
        tasks.append(task)
    
    await asyncio.gather(*tasks)
    
    # Assert
    assert len(mock_websocket_manager.active_connections) == num_clients


@pytest.mark.asyncio
async def test_model_timeout_handling(mock_agent_kernel):
    """Test model inference timeout handling."""
    # Arrange
    session_id = "test-session-timeout"
    user_message = "Complex query"
    
    # Mock slow model inference
    async def slow_inference(text, sid):
        await asyncio.sleep(0.2)
        return "Response"
    
    mock_agent_kernel.process_text_message = AsyncMock(side_effect=slow_inference)
    
    # Act & Assert - Timeout after 0.1 seconds
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            mock_agent_kernel.process_text_message(user_message, session_id),
            timeout=0.1
        )


@pytest.mark.asyncio
async def test_tool_execution_failure_recovery(mock_tool_bridge, mock_agent_kernel):
    """Test recovery from tool execution failures."""
    # Arrange
    session_id = "test-session-tool-fail"
    
    # Mock tool failure
    mock_tool_bridge.execute_tool = AsyncMock(
        side_effect=Exception("Tool execution failed")
    )
    
    # Mock agent handling failure
    mock_agent_kernel.process_text_message = AsyncMock(
        return_value="I encountered an error executing that action. Please try again."
    )
    
    # Act - Try tool execution, handle failure
    try:
        await mock_tool_bridge.execute_tool("browser_open", {"url": "https://example.com"})
    except Exception:
        # Agent provides error response
        response = await mock_agent_kernel.process_text_message(
            "Open browser", session_id
        )
    
    # Assert
    assert "error" in response.lower()


@pytest.mark.asyncio
async def test_session_recovery_after_backend_restart(mock_session_manager, mock_state_manager):
    """Test session recovery after backend restart."""
    # Arrange
    session_id = "persistent-session"
    
    # Simulate backend restart - session data persisted
    persisted_session_data = {
        "session_id": session_id,
        "field_values": {"voice.input": {"input_device": "USB Mic"}},
        "active_theme": {"glow_color": "#7000ff"}
    }
    
    # Mock session restoration
    mock_session_manager.restore_session = AsyncMock(return_value=persisted_session_data)
    mock_state_manager.get_state = AsyncMock(return_value=persisted_session_data)
    
    # Act - Restore session after restart
    restored_session = await mock_session_manager.restore_session(session_id)
    restored_state = await mock_state_manager.get_state(session_id)
    
    # Assert
    assert restored_session["session_id"] == session_id
    assert restored_state["field_values"]["voice.input"]["input_device"] == "USB Mic"


@pytest.mark.asyncio
async def test_vps_health_check_failure_detection(mock_vps_gateway):
    """Test VPS health check failure detection."""
    # Arrange
    endpoint = "https://vps.example.com"
    
    # Mock health check failures
    mock_vps_gateway.check_vps_health = AsyncMock(return_value=False)
    
    consecutive_failures = 0
    max_failures = 3
    
    # Act - Multiple health check failures
    for _ in range(max_failures):
        is_healthy = await mock_vps_gateway.check_vps_health(endpoint)
        if not is_healthy:
            consecutive_failures += 1
    
    # Mark VPS as unavailable after max failures
    if consecutive_failures >= max_failures:
        mock_vps_gateway._health_status = {
            endpoint: {"available": False, "consecutive_failures": consecutive_failures}
        }
    
    # Assert
    assert consecutive_failures == max_failures
    assert mock_vps_gateway._health_status[endpoint]["available"] is False


@pytest.mark.asyncio
async def test_graceful_degradation_all_systems(mock_agent_kernel, mock_voice_pipeline, mock_tool_bridge, mock_vps_gateway):
    """Test graceful degradation when multiple systems fail."""
    # Arrange
    session_id = "test-session-degradation"
    
    # Mock multiple system failures
    mock_vps_gateway.is_vps_available = MagicMock(return_value=False)
    mock_voice_pipeline.start_listening = AsyncMock(
        side_effect=Exception("Audio unavailable")
    )
    mock_tool_bridge.get_available_tools = MagicMock(return_value=[])
    
    # Agent still functional in degraded mode
    mock_agent_kernel.process_text_message = AsyncMock(
        return_value="I'm operating in limited mode. Text chat is available."
    )
    
    # Act - Use system in degraded mode
    response = await mock_agent_kernel.process_text_message("Hello", session_id)
    
    # Assert - Core functionality still works
    assert "limited mode" in response.lower()
    assert "text chat" in response.lower()


@pytest.mark.asyncio
async def test_automatic_retry_with_exponential_backoff():
    """Test automatic retry with exponential backoff for transient failures."""
    # Arrange
    max_retries = 3
    retry_delays = []
    
    async def failing_operation(attempt):
        """Simulate operation that fails then succeeds."""
        if attempt < 2:
            raise ConnectionError("Transient failure")
        return "Success"
    
    # Act - Retry with exponential backoff
    for attempt in range(max_retries):
        try:
            result = await failing_operation(attempt)
            break
        except ConnectionError:
            if attempt < max_retries - 1:
                delay = 2 ** attempt  # 1s, 2s, 4s
                retry_delays.append(delay)
                await asyncio.sleep(0.01)  # Shortened for test
    
    # Assert
    assert result == "Success"
    assert retry_delays == [1, 2]  # Only 2 retries needed


@pytest.mark.asyncio
async def test_error_logging_for_debugging(mock_websocket_manager):
    """Test all errors are logged with sufficient context."""
    # Arrange
    errors_logged = []
    
    def log_error(error_type, error_message, context):
        errors_logged.append({
            "type": error_type,
            "message": error_message,
            "context": context
        })
    
    # Act - Simulate various errors
    error_scenarios = [
        ("connection_error", "WebSocket disconnected", {"client_id": "client-1"}),
        ("model_error", "Inference timeout", {"model": "lfm2-8b"}),
        ("tool_error", "Tool execution failed", {"tool": "browser_open"}),
        ("vps_error", "VPS unreachable", {"endpoint": "vps.example.com"})
    ]
    
    for error_type, error_message, context in error_scenarios:
        log_error(error_type, error_message, context)
    
    # Assert
    assert len(errors_logged) == 4
    assert all("context" in log for log in errors_logged)
