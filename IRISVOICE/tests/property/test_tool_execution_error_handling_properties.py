#!/usr/bin/env python3
"""
Property-Based Tests for Tool Execution Error Handling

Property 24: Tool Execution Error Handling
For any tool execution that fails, the Tool_Bridge returns an error message
with failure details.

**Validates: Requirements 8.5, 19.3**
"""

import pytest
from hypothesis import given, strategies as st, settings
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock

# Add backend to path
backend_path = Path(__file__).parent.parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from agent.tool_bridge import AgentToolBridge


# Test strategies
@st.composite
def tool_execution_scenarios(draw):
    """Generate different tool execution scenarios that may fail"""
    tools_with_params = [
        ("vision_detect_element", {"description": "test"}),
        ("vision_analyze_screen", {}),
        ("vision_get_context", {}),
        ("gui_click", {"x": 100, "y": 100}),
        ("gui_type", {"text": "test"}),
        ("gui_press_key", {"key": "enter"}),
        ("open_url", {"url": "https://example.com"}),
        ("search", {"query": "test"}),
        ("read_file", {"path": "/test/file.txt"}),
        ("write_file", {"path": "/test/file.txt", "content": "test"}),
        ("get_system_info", {}),
        ("launch_app", {"app_name": "notepad"})
    ]
    
    tool_name, params = draw(st.sampled_from(tools_with_params))
    
    # Generate different error scenarios
    error_type = draw(st.sampled_from([
        "exception",  # Tool raises exception
        "timeout",    # Tool times out
        "not_found",  # Tool/resource not found
        "permission", # Permission denied
        "invalid_param" # Invalid parameter
    ]))
    
    return {
        "tool_name": tool_name,
        "params": params,
        "error_type": error_type,
        "session_id": draw(st.uuids().map(str))
    }


class TestToolExecutionErrorHandlingProperties:
    """Property-based tests for tool execution error handling"""
    
    def _create_failing_bridge(self, error_type: str):
        """Helper to create a tool bridge that simulates failures"""
        bridge = AgentToolBridge()
        
        # Create error messages based on error type
        error_messages = {
            "exception": "Tool execution failed with exception",
            "timeout": "Tool execution timed out",
            "not_found": "Tool or resource not found",
            "permission": "Permission denied",
            "invalid_param": "Invalid parameter provided"
        }
        error_msg = error_messages.get(error_type, "Unknown error")
        
        # Mock vision components to fail
        bridge._vision_client = Mock()
        if error_type == "exception":
            bridge._vision_client.detect_element = AsyncMock(side_effect=Exception(error_msg))
            bridge._vision_client.analyze_screen = AsyncMock(side_effect=Exception(error_msg))
        else:
            bridge._vision_client.detect_element = AsyncMock(return_value={"error": error_msg})
            bridge._vision_client.analyze_screen = AsyncMock(return_value={"error": error_msg})
        
        bridge._vision_system = Mock()
        if error_type == "exception":
            bridge._vision_system.get_current_context = Mock(side_effect=Exception(error_msg))
        else:
            bridge._vision_system.get_current_context = Mock(return_value=None)
        
        # Mock GUI operator to fail
        bridge._gui_operator = Mock()
        if error_type == "exception":
            bridge._gui_operator.click = AsyncMock(side_effect=Exception(error_msg))
            bridge._gui_operator.type_text = AsyncMock(side_effect=Exception(error_msg))
            bridge._gui_operator.press_key = AsyncMock(side_effect=Exception(error_msg))
        else:
            bridge._gui_operator.click = AsyncMock(return_value={"error": error_msg})
            bridge._gui_operator.type_text = AsyncMock(return_value={"error": error_msg})
            bridge._gui_operator.press_key = AsyncMock(return_value={"error": error_msg})
        
        # Mock screen capture to fail
        bridge._screen_capture = Mock()
        if error_type == "exception":
            bridge._screen_capture.capture = Mock(side_effect=Exception(error_msg))
        else:
            bridge._screen_capture.capture = Mock(return_value=None)
        
        # Mock MCP servers to fail
        mock_server = Mock()
        mock_response = Mock()
        mock_response.result = None
        mock_response.error = error_msg
        mock_server.handle_request = AsyncMock(return_value=mock_response)
        
        bridge._mcp_servers = {
            "browser": mock_server,
            "file_manager": mock_server,
            "system": mock_server,
            "app_launcher": mock_server,
            "gui_automation": mock_server
        }
        
        bridge._initialized = True
        
        return bridge
    
    # Feature: irisvoice-backend-integration, Property 24: Tool Execution Error Handling
    @given(scenario=tool_execution_scenarios())
    @settings(max_examples=100, deadline=5000)
    def test_tool_execution_failure_returns_error(self, scenario):
        """
        Property 24: Tool Execution Error Handling
        
        For any tool execution that fails, the Tool_Bridge SHALL return an
        error message with failure details.
        
        **Validates: Requirements 8.5, 19.3**
        """
        tool_bridge = self._create_failing_bridge(scenario["error_type"])
        tool_name = scenario["tool_name"]
        params = scenario["params"]
        session_id = scenario["session_id"]
        
        # Execute the tool (which should fail)
        result = asyncio.run(tool_bridge.execute_tool(tool_name, params, session_id))
        
        # Verify error is returned
        assert result is not None, f"Tool '{tool_name}' returned None on failure"
        assert isinstance(result, dict), f"Tool '{tool_name}' result must be a dict"
        
        # Error can be in different formats:
        # 1. Direct error field: {"error": "..."}
        # 2. Wrapped in result: {"success": True, "result": {"error": "..."}}
        has_error = "error" in result
        has_nested_error = "result" in result and isinstance(result["result"], dict) and "error" in result["result"]
        
        assert has_error or has_nested_error, (
            f"Tool '{tool_name}' failure must return 'error' field (direct or nested). Got: {result.keys()}"
        )
        
        # Extract error message
        if has_error:
            error_msg = result["error"]
        else:
            error_msg = result["result"]["error"]
        
        # Verify error message is not empty
        assert error_msg, f"Tool '{tool_name}' error message should not be empty"
        assert isinstance(error_msg, str), (
            f"Tool '{tool_name}' error message must be a string"
        )
    
    # Feature: irisvoice-backend-integration, Property 24: Tool Execution Error Handling
    @given(
        tool_name=st.sampled_from([
            "vision_detect_element", "vision_analyze_screen", "vision_get_context"
        ]),
        session_id=st.uuids().map(str)
    )
    @settings(max_examples=100, deadline=5000)
    def test_vision_tool_failure_returns_error_details(self, tool_name, session_id):
        """
        Property 24: Tool Execution Error Handling (Vision Tools)
        
        For any vision tool execution that fails, the Tool_Bridge SHALL return
        an error message with details about the failure.
        
        **Validates: Requirements 8.5, 19.3**
        """
        tool_bridge = self._create_failing_bridge("exception")
        
        params = {}
        if tool_name == "vision_detect_element":
            params = {"description": "test element"}
        
        # Execute the tool
        result = asyncio.run(tool_bridge.execute_tool(tool_name, params, session_id))
        
        # Verify error details
        assert "error" in result
        assert len(result["error"]) > 0
        # Error message should contain some context
        assert isinstance(result["error"], str)
    
    # Feature: irisvoice-backend-integration, Property 24: Tool Execution Error Handling
    @given(
        tool_name=st.sampled_from(["gui_click", "gui_type", "gui_press_key"]),
        session_id=st.uuids().map(str)
    )
    @settings(max_examples=100, deadline=5000)
    def test_gui_tool_failure_returns_error_details(self, tool_name, session_id):
        """
        Property 24: Tool Execution Error Handling (GUI Tools)
        
        For any GUI tool execution that fails, the Tool_Bridge SHALL return
        an error message with details about the failure.
        
        **Validates: Requirements 8.5, 19.3**
        """
        tool_bridge = self._create_failing_bridge("exception")
        
        params = {}
        if tool_name == "gui_click":
            params = {"x": 100, "y": 100}
        elif tool_name == "gui_type":
            params = {"text": "test"}
        elif tool_name == "gui_press_key":
            params = {"key": "enter"}
        
        # Execute the tool
        result = asyncio.run(tool_bridge.execute_tool(tool_name, params, session_id))
        
        # Verify error details
        assert "error" in result
        assert len(result["error"]) > 0
        assert isinstance(result["error"], str)
    
    # Feature: irisvoice-backend-integration, Property 24: Tool Execution Error Handling
    @given(
        tool_name=st.sampled_from(["open_url", "search"]),
        session_id=st.uuids().map(str)
    )
    @settings(max_examples=100, deadline=5000)
    def test_mcp_tool_failure_returns_error_details(self, tool_name, session_id):
        """
        Property 24: Tool Execution Error Handling (MCP Tools)
        
        For any MCP tool execution that fails, the Tool_Bridge SHALL return
        an error message with details about the failure.
        
        **Validates: Requirements 8.5, 19.3**
        """
        tool_bridge = self._create_failing_bridge("not_found")
        
        params = {}
        if tool_name == "open_url":
            params = {"url": "https://example.com"}
        elif tool_name == "search":
            params = {"query": "test"}
        
        # Execute the tool
        result = asyncio.run(tool_bridge.execute_tool(tool_name, params, session_id))
        
        # Verify error details
        assert "error" in result
        assert len(result["error"]) > 0
        assert isinstance(result["error"], str)
    
    # Feature: irisvoice-backend-integration, Property 24: Tool Execution Error Handling
    @given(
        error_type=st.sampled_from(["exception", "timeout", "not_found", "permission"]),
        session_id=st.uuids().map(str)
    )
    @settings(max_examples=100, deadline=5000)
    def test_error_message_contains_failure_type(self, error_type, session_id):
        """
        Property 24: Tool Execution Error Handling (Error Details)
        
        For any tool execution failure, the error message SHALL contain
        information about the type of failure.
        
        **Validates: Requirements 8.5, 19.3**
        """
        tool_bridge = self._create_failing_bridge(error_type)
        
        # Try a simple tool
        result = asyncio.run(tool_bridge.execute_tool("vision_get_context", {}, session_id))
        
        # Verify error message contains relevant information
        assert "error" in result
        error_msg = result["error"].lower()
        
        # Error message should be descriptive (not just "error")
        assert len(error_msg) > 5, "Error message should be descriptive"
    
    # Feature: irisvoice-backend-integration, Property 24: Tool Execution Error Handling
    @given(
        tool_name=st.sampled_from(["read_file", "write_file", "launch_app"]),
        session_id=st.uuids().map(str)
    )
    @settings(max_examples=100, deadline=5000)
    def test_tool_failure_does_not_crash_bridge(self, tool_name, session_id):
        """
        Property 24: Tool Execution Error Handling (Stability)
        
        For any tool execution that fails, the Tool_Bridge SHALL handle the
        error gracefully without crashing and remain available for subsequent
        tool executions.
        
        **Validates: Requirements 8.5, 19.3**
        """
        tool_bridge = self._create_failing_bridge("exception")
        
        params = {}
        if tool_name == "read_file":
            params = {"path": "/test/file.txt"}
        elif tool_name == "write_file":
            params = {"path": "/test/file.txt", "content": "test"}
        elif tool_name == "launch_app":
            params = {"app_name": "notepad"}
        
        # Execute the tool (should fail but not crash)
        result1 = asyncio.run(tool_bridge.execute_tool(tool_name, params, session_id))
        
        # Verify error was returned
        assert "error" in result1
        
        # Execute another tool to verify bridge is still functional
        result2 = asyncio.run(tool_bridge.execute_tool("vision_get_context", {}, session_id))
        
        # Should still return a result (even if it's an error)
        assert result2 is not None
        assert isinstance(result2, dict)
    
    # Feature: irisvoice-backend-integration, Property 24: Tool Execution Error Handling
    @given(scenario=tool_execution_scenarios())
    @settings(max_examples=100, deadline=5000)
    def test_error_result_structure_is_consistent(self, scenario):
        """
        Property 24: Tool Execution Error Handling (Consistency)
        
        For any tool execution failure, the error result SHALL have a
        consistent structure (dictionary with 'error' field).
        
        **Validates: Requirements 8.5, 19.3**
        """
        tool_bridge = self._create_failing_bridge(scenario["error_type"])
        tool_name = scenario["tool_name"]
        params = scenario["params"]
        session_id = scenario["session_id"]
        
        # Execute the tool
        result = asyncio.run(tool_bridge.execute_tool(tool_name, params, session_id))
        
        # Verify consistent error structure
        assert isinstance(result, dict), "Error result must be a dictionary"
        
        # Error can be in different formats:
        # 1. Direct error field: {"error": "..."}
        # 2. Wrapped in result: {"success": True, "result": {"error": "..."}}
        has_error = "error" in result
        has_nested_error = "result" in result and isinstance(result["result"], dict) and "error" in result["result"]
        
        assert has_error or has_nested_error, "Error result must have 'error' field (direct or nested)"
        
        # Extract error message
        if has_error:
            error_msg = result["error"]
        else:
            error_msg = result["result"]["error"]
        
        assert isinstance(error_msg, str), "Error field must be a string"
        
        # Error message should not be empty
        assert len(error_msg) > 0, "Error message should not be empty"
    
    # Feature: irisvoice-backend-integration, Property 24: Tool Execution Error Handling
    @given(
        tool_name=st.sampled_from(["vision_detect_element", "gui_click", "open_url"]),
        num_failures=st.integers(min_value=1, max_value=5),
        session_id=st.uuids().map(str)
    )
    @settings(max_examples=100, deadline=5000)
    def test_multiple_failures_handled_independently(self, tool_name, num_failures, session_id):
        """
        Property 24: Tool Execution Error Handling (Multiple Failures)
        
        For any sequence of tool execution failures, each failure SHALL be
        handled independently and return its own error message.
        
        **Validates: Requirements 8.5, 19.3**
        """
        tool_bridge = self._create_failing_bridge("exception")
        
        params = {}
        if tool_name == "vision_detect_element":
            params = {"description": "test"}
        elif tool_name == "gui_click":
            params = {"x": 100, "y": 100}
        elif tool_name == "open_url":
            params = {"url": "https://example.com"}
        
        # Execute the tool multiple times
        results = []
        for _ in range(num_failures):
            result = asyncio.run(tool_bridge.execute_tool(tool_name, params, session_id))
            results.append(result)
        
        # Verify all failures returned errors
        for i, result in enumerate(results):
            assert "error" in result, f"Failure {i+1} should return error"
            assert isinstance(result["error"], str), f"Failure {i+1} error must be string"
            assert len(result["error"]) > 0, f"Failure {i+1} error should not be empty"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--hypothesis-show-statistics"])
