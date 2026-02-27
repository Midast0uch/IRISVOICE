#!/usr/bin/env python3
"""
Property-Based Tests for Tool Execution Routing

Property 23: Tool Execution Routing
For any tool execution request, the Tool_Bridge routes it to the appropriate
MCP server and returns the execution result.

**Validates: Requirements 8.3, 8.4**
"""

import pytest
from hypothesis import given, strategies as st, settings, assume
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch

# Add backend to path
backend_path = Path(__file__).parent.parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from agent.tool_bridge import AgentToolBridge


# Test strategies
@st.composite
def tool_execution_requests(draw):
    """Generate different tool execution requests"""
    # Simplified tool list for faster generation
    tools_with_params = [
        ("vision_get_context", {}),
        ("gui_click", {"x": 100, "y": 100}),
        ("open_url", {"url": "https://example.com"}),
        ("read_file", {"path": "/test/file.txt"}),
        ("get_system_info", {}),
        ("launch_app", {"app_name": "notepad"})
    ]
    
    tool_name, params = draw(st.sampled_from(tools_with_params))
    
    # Determine category
    category_map = {
        "vision_get_context": "vision",
        "gui_click": "gui",
        "open_url": "web",
        "read_file": "file",
        "get_system_info": "system",
        "launch_app": "app"
    }
    
    return {
        "tool_name": tool_name,
        "params": params,
        "category": category_map[tool_name],
        "session_id": draw(st.uuids().map(str))
    }


class TestToolExecutionRoutingProperties:
    """Property-based tests for tool execution routing"""
    
    def _create_mock_bridge(self):
        """Helper to create a mocked tool bridge"""
        bridge = AgentToolBridge()
        
        # Mock the internal components to avoid actual execution
        bridge._vision_client = Mock()
        bridge._vision_client.detect_element = AsyncMock(return_value={"x": 100, "y": 100})
        bridge._vision_client.analyze_screen = AsyncMock(return_value={"description": "test screen"})
        bridge._vision_client.validate_action = AsyncMock(return_value={"valid": True})
        
        bridge._vision_system = Mock()
        bridge._vision_system.get_current_context = Mock(return_value=Mock(
            description="test context",
            active_app="test_app",
            notable_items=[],
            needs_help=False,
            suggestion=None
        ))
        
        bridge._gui_operator = Mock()
        bridge._gui_operator.click = AsyncMock(return_value="clicked")
        bridge._gui_operator.type_text = AsyncMock(return_value="typed")
        bridge._gui_operator.press_key = AsyncMock(return_value="pressed")
        
        bridge._screen_capture = Mock()
        import numpy as np
        bridge._screen_capture.capture = Mock(return_value=np.zeros((100, 100, 3), dtype=np.uint8))
        
        # Mock MCP servers
        mock_server = Mock()
        mock_response = Mock()
        mock_response.result = {"success": True, "data": "test_result"}
        mock_response.error = None
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
    
    # Feature: irisvoice-backend-integration, Property 23: Tool Execution Routing
    @given(request=tool_execution_requests())
    @settings(max_examples=100, deadline=5000)
    def test_tool_execution_routes_to_correct_handler(self, request):
        """
        Property 23: Tool Execution Routing
        
        For any tool execution request, the Tool_Bridge SHALL route it to the
        appropriate MCP server and return the execution result.
        
        **Validates: Requirements 8.3, 8.4**
        """
        tool_bridge = self._create_mock_bridge()
        tool_name = request["tool_name"]
        params = request["params"]
        session_id = request["session_id"]
        
        # Execute the tool
        result = asyncio.run(tool_bridge.execute_tool(tool_name, params, session_id))
        
        # Verify result is returned
        assert result is not None, f"Tool '{tool_name}' returned None"
        assert isinstance(result, dict), f"Tool '{tool_name}' result must be a dict"
        
        # Result should either have success/result or error
        has_result = "result" in result or "success" in result
        has_error = "error" in result
        assert has_result or has_error, (
            f"Tool '{tool_name}' result must have either 'result'/'success' or 'error' field"
        )
    
    # Feature: irisvoice-backend-integration, Property 23: Tool Execution Routing
    @given(
        tool_name=st.sampled_from([
            "vision_detect_element", "vision_analyze_screen", "vision_get_context"
        ]),
        session_id=st.uuids().map(str)
    )
    @settings(max_examples=100, deadline=5000)
    def test_vision_tools_route_to_vision_handler(self, tool_name, session_id):
        """
        Property 23: Tool Execution Routing (Vision Tools)
        
        For any vision tool execution request, the Tool_Bridge SHALL route it
        to the vision handler (execute_vision_tool).
        
        **Validates: Requirements 8.3, 8.4**
        """
        tool_bridge = self._create_mock_bridge()
        params = {}
        if tool_name == "vision_detect_element":
            params = {"description": "test element"}
        elif tool_name == "vision_validate_action":
            params = {"action": "click", "target": "button"}
        
        # Execute the tool
        result = asyncio.run(tool_bridge.execute_tool(tool_name, params, session_id))
        
        # Verify vision client was called (if tool requires it)
        if tool_name == "vision_detect_element":
            assert tool_bridge._vision_client.detect_element.called or "error" in result
        elif tool_name == "vision_analyze_screen":
            assert tool_bridge._vision_client.analyze_screen.called or "error" in result
        elif tool_name == "vision_get_context":
            assert tool_bridge._vision_system.get_current_context.called or "error" in result
    
    # Feature: irisvoice-backend-integration, Property 23: Tool Execution Routing
    @given(
        tool_name=st.sampled_from(["gui_click", "gui_type", "gui_press_key"]),
        session_id=st.uuids().map(str)
    )
    @settings(max_examples=100, deadline=5000)
    def test_gui_tools_route_to_gui_handler(self, tool_name, session_id):
        """
        Property 23: Tool Execution Routing (GUI Tools)
        
        For any GUI tool execution request, the Tool_Bridge SHALL route it
        to the GUI handler (execute_gui_tool).
        
        **Validates: Requirements 8.3, 8.4**
        """
        tool_bridge = self._create_mock_bridge()
        params = {}
        if tool_name == "gui_click":
            params = {"x": 100, "y": 100}
        elif tool_name == "gui_type":
            params = {"text": "test text"}
        elif tool_name == "gui_press_key":
            params = {"key": "enter"}
        
        # Execute the tool
        result = asyncio.run(tool_bridge.execute_tool(tool_name, params, session_id))
        
        # Verify GUI operator was called
        if tool_name == "gui_click":
            assert tool_bridge._gui_operator.click.called
        elif tool_name == "gui_type":
            assert tool_bridge._gui_operator.type_text.called
        elif tool_name == "gui_press_key":
            assert tool_bridge._gui_operator.press_key.called
    
    # Feature: irisvoice-backend-integration, Property 23: Tool Execution Routing
    @given(
        tool_name=st.sampled_from(["open_url", "search"]),
        session_id=st.uuids().map(str)
    )
    @settings(max_examples=100, deadline=5000)
    def test_web_tools_route_to_browser_server(self, tool_name, session_id):
        """
        Property 23: Tool Execution Routing (Web Tools)
        
        For any web tool execution request, the Tool_Bridge SHALL route it
        to the browser MCP server.
        
        **Validates: Requirements 8.3, 8.4**
        """
        tool_bridge = self._create_mock_bridge()
        params = {}
        if tool_name == "open_url":
            params = {"url": "https://example.com"}
        elif tool_name == "search":
            params = {"query": "test query"}
        
        # Execute the tool
        result = asyncio.run(tool_bridge.execute_tool(tool_name, params, session_id))
        
        # Verify browser server was called
        assert tool_bridge._mcp_servers["browser"].handle_request.called
    
    # Feature: irisvoice-backend-integration, Property 23: Tool Execution Routing
    @given(
        tool_name=st.sampled_from(["read_file", "write_file", "list_directory"]),
        session_id=st.uuids().map(str)
    )
    @settings(max_examples=100, deadline=5000)
    def test_file_tools_route_to_file_manager_server(self, tool_name, session_id):
        """
        Property 23: Tool Execution Routing (File Tools)
        
        For any file tool execution request, the Tool_Bridge SHALL route it
        to the file_manager MCP server.
        
        **Validates: Requirements 8.3, 8.4**
        """
        tool_bridge = self._create_mock_bridge()
        params = {"path": "/test/path"}
        if tool_name == "write_file":
            params["content"] = "test content"
        
        # Execute the tool
        result = asyncio.run(tool_bridge.execute_tool(tool_name, params, session_id))
        
        # Verify file manager server was called
        assert tool_bridge._mcp_servers["file_manager"].handle_request.called
    
    # Feature: irisvoice-backend-integration, Property 23: Tool Execution Routing
    @given(
        tool_name=st.sampled_from(["get_system_info", "lock_screen"]),
        session_id=st.uuids().map(str)
    )
    @settings(max_examples=100, deadline=5000)
    def test_system_tools_route_to_system_server(self, tool_name, session_id):
        """
        Property 23: Tool Execution Routing (System Tools)
        
        For any system tool execution request, the Tool_Bridge SHALL route it
        to the system MCP server.
        
        **Validates: Requirements 8.3, 8.4**
        """
        tool_bridge = self._create_mock_bridge()
        params = {}
        
        # Execute the tool
        result = asyncio.run(tool_bridge.execute_tool(tool_name, params, session_id))
        
        # Verify system server was called
        assert tool_bridge._mcp_servers["system"].handle_request.called
    
    # Feature: irisvoice-backend-integration, Property 23: Tool Execution Routing
    @given(
        tool_name=st.sampled_from(["launch_app", "open_file"]),
        session_id=st.uuids().map(str)
    )
    @settings(max_examples=100, deadline=5000)
    def test_app_tools_route_to_app_launcher_server(self, tool_name, session_id):
        """
        Property 23: Tool Execution Routing (App Tools)
        
        For any app tool execution request, the Tool_Bridge SHALL route it
        to the app_launcher MCP server.
        
        **Validates: Requirements 8.3, 8.4**
        """
        tool_bridge = self._create_mock_bridge()
        params = {}
        if tool_name == "launch_app":
            params = {"app_name": "notepad"}
        elif tool_name == "open_file":
            params = {"file_path": "/test/file.txt"}
        
        # Execute the tool
        result = asyncio.run(tool_bridge.execute_tool(tool_name, params, session_id))
        
        # Verify app launcher server was called
        assert tool_bridge._mcp_servers["app_launcher"].handle_request.called
    
    # Feature: irisvoice-backend-integration, Property 23: Tool Execution Routing
    @given(
        unknown_tool=st.text(min_size=1, max_size=50).filter(
            lambda x: x not in [
                "vision_detect_element", "vision_analyze_screen", "vision_validate_action",
                "vision_get_context", "gui_click", "gui_type", "gui_press_key",
                "open_url", "search", "read_file", "write_file", "list_directory",
                "create_directory", "delete_file", "get_system_info", "lock_screen",
                "shutdown", "restart", "launch_app", "open_file", "take_screenshot"
            ]
        ),
        session_id=st.uuids().map(str)
    )
    @settings(max_examples=100, deadline=5000)
    def test_unknown_tool_returns_error(self, unknown_tool, session_id):
        """
        Property 23: Tool Execution Routing (Unknown Tools)
        
        For any unknown tool execution request, the Tool_Bridge SHALL return
        an error indicating the tool is not found.
        
        **Validates: Requirements 8.3, 8.4**
        """
        tool_bridge = self._create_mock_bridge()
        # Execute unknown tool
        result = asyncio.run(tool_bridge.execute_tool(unknown_tool, {}, session_id))
        
        # Verify error is returned
        assert "error" in result, f"Unknown tool '{unknown_tool}' should return error"
        assert "unknown" in result["error"].lower() or "not found" in result["error"].lower(), (
            f"Error message should indicate tool is unknown: {result['error']}"
        )
    
    # Feature: irisvoice-backend-integration, Property 23: Tool Execution Routing
    @given(request=tool_execution_requests())
    @settings(max_examples=100, deadline=5000)
    def test_tool_execution_result_structure(self, request):
        """
        Property 23: Tool Execution Routing (Result Structure)
        
        For any tool execution, the result SHALL be a dictionary with either
        a success/result field or an error field.
        
        **Validates: Requirements 8.3, 8.4**
        """
        tool_bridge = self._create_mock_bridge()
        tool_name = request["tool_name"]
        params = request["params"]
        session_id = request["session_id"]
        
        # Execute the tool
        result = asyncio.run(tool_bridge.execute_tool(tool_name, params, session_id))
        
        # Verify result structure
        assert isinstance(result, dict), "Result must be a dictionary"
        
        # Must have either success/result or error
        has_success_result = "success" in result or "result" in result
        has_error = "error" in result
        
        assert has_success_result or has_error, (
            f"Result must have either 'success'/'result' or 'error' field. Got: {result.keys()}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--hypothesis-show-statistics"])
