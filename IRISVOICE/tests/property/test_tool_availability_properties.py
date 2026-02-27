#!/usr/bin/env python3
"""
Property-Based Tests for Tool Availability

Property 22: Tool Availability
For any request for agent tools, the backend returns a list containing at least:
vision, web, file, system, and app categories.

**Validates: Requirements 8.1, 8.2**
"""

import pytest
from hypothesis import given, strategies as st, settings
import asyncio
import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from agent.tool_bridge import AgentToolBridge


# Test strategies
@st.composite
def tool_request_scenarios(draw):
    """Generate different scenarios for requesting tools"""
    return {
        "request_type": draw(st.sampled_from(["all", "by_category", "by_name"])),
        "filter_category": draw(st.sampled_from([None, "vision", "web", "file", "system", "app", "gui"])),
        "session_id": draw(st.uuids().map(str))
    }


class TestToolAvailabilityProperties:
    """Property-based tests for tool availability"""
    
    @pytest.fixture
    def tool_bridge(self):
        """Create a tool bridge instance for testing"""
        bridge = AgentToolBridge()
        # Don't initialize to avoid dependencies, just test the tool listing
        return bridge
    
    # Feature: irisvoice-backend-integration, Property 22: Tool Availability
    @given(scenario=tool_request_scenarios())
    @settings(max_examples=100, deadline=None)
    def test_tool_availability_contains_required_categories(self, tool_bridge, scenario):
        """
        Property 22: Tool Availability
        
        For any request for agent tools, the backend SHALL return a list
        containing at least: vision, web, file, system, and app categories.
        
        **Validates: Requirements 8.1, 8.2**
        """
        # Get available tools
        tools = tool_bridge.get_available_tools()
        
        # Extract categories from tools
        categories = set(tool.get("category") for tool in tools)
        
        # Required categories per requirements
        required_categories = {"vision", "web", "file", "system", "app"}
        
        # Verify all required categories are present
        assert required_categories.issubset(categories), (
            f"Missing required categories. "
            f"Expected at least {required_categories}, "
            f"but got {categories}"
        )
        
        # Verify tools list is not empty
        assert len(tools) > 0, "Tools list should not be empty"
        
        # Verify each tool has required fields
        for tool in tools:
            assert "name" in tool, f"Tool missing 'name' field: {tool}"
            assert "description" in tool, f"Tool missing 'description' field: {tool}"
            assert "category" in tool, f"Tool missing 'category' field: {tool}"
            assert "parameters" in tool, f"Tool missing 'parameters' field: {tool}"
    
    # Feature: irisvoice-backend-integration, Property 22: Tool Availability
    @given(
        category=st.sampled_from(["vision", "web", "file", "system", "app", "gui"]),
        session_id=st.uuids().map(str)
    )
    @settings(max_examples=100, deadline=None)
    def test_each_category_has_tools(self, tool_bridge, category, session_id):
        """
        Property 22: Tool Availability (Category Coverage)
        
        For any required category, there SHALL be at least one tool available
        in that category.
        
        **Validates: Requirements 8.1, 8.2**
        """
        # Get available tools
        tools = tool_bridge.get_available_tools()
        
        # Filter tools by category
        category_tools = [tool for tool in tools if tool.get("category") == category]
        
        # Required categories must have at least one tool
        required_categories = {"vision", "web", "file", "system", "app"}
        
        if category in required_categories:
            assert len(category_tools) > 0, (
                f"Required category '{category}' has no tools available"
            )
        
        # Verify tool structure for this category
        for tool in category_tools:
            assert isinstance(tool["name"], str), "Tool name must be a string"
            assert isinstance(tool["description"], str), "Tool description must be a string"
            assert isinstance(tool["parameters"], dict), "Tool parameters must be a dict"
    
    # Feature: irisvoice-backend-integration, Property 22: Tool Availability
    @given(
        num_requests=st.integers(min_value=1, max_value=10),
        session_id=st.uuids().map(str)
    )
    @settings(max_examples=100, deadline=None)
    def test_tool_availability_consistency(self, tool_bridge, num_requests, session_id):
        """
        Property 22: Tool Availability (Consistency)
        
        For any sequence of tool availability requests, the returned tool list
        SHALL be consistent (same tools, same categories).
        
        **Validates: Requirements 8.1, 8.2**
        """
        # Get tools multiple times
        tool_lists = [tool_bridge.get_available_tools() for _ in range(num_requests)]
        
        # Verify all lists are identical
        first_list = tool_lists[0]
        for i, tool_list in enumerate(tool_lists[1:], start=1):
            assert len(tool_list) == len(first_list), (
                f"Tool list {i} has different length than first list"
            )
            
            # Compare tool names (order-independent)
            first_names = set(tool["name"] for tool in first_list)
            current_names = set(tool["name"] for tool in tool_list)
            assert first_names == current_names, (
                f"Tool list {i} has different tools than first list"
            )
    
    # Feature: irisvoice-backend-integration, Property 22: Tool Availability
    @given(
        tool_name=st.text(min_size=1, max_size=50),
        session_id=st.uuids().map(str)
    )
    @settings(max_examples=100, deadline=None)
    def test_tool_names_are_unique(self, tool_bridge, tool_name, session_id):
        """
        Property 22: Tool Availability (Uniqueness)
        
        For any tool list, all tool names SHALL be unique (no duplicates).
        
        **Validates: Requirements 8.1, 8.2**
        """
        # Get available tools
        tools = tool_bridge.get_available_tools()
        
        # Extract tool names
        tool_names = [tool["name"] for tool in tools]
        
        # Verify no duplicates
        assert len(tool_names) == len(set(tool_names)), (
            f"Tool names are not unique. Duplicates found: "
            f"{[name for name in tool_names if tool_names.count(name) > 1]}"
        )
    
    # Feature: irisvoice-backend-integration, Property 22: Tool Availability
    @given(session_id=st.uuids().map(str))
    @settings(max_examples=100, deadline=None)
    def test_tool_parameters_are_valid(self, tool_bridge, session_id):
        """
        Property 22: Tool Availability (Parameter Validation)
        
        For any tool in the available tools list, the parameters field SHALL
        be a valid dictionary with proper type specifications.
        
        **Validates: Requirements 8.1, 8.2**
        """
        # Get available tools
        tools = tool_bridge.get_available_tools()
        
        # Verify each tool's parameters
        for tool in tools:
            params = tool["parameters"]
            
            # Parameters must be a dict
            assert isinstance(params, dict), (
                f"Tool '{tool['name']}' has invalid parameters type: {type(params)}"
            )
            
            # Each parameter should have a type specification
            for param_name, param_spec in params.items():
                if isinstance(param_spec, dict):
                    # Check for type field
                    if "type" in param_spec:
                        assert isinstance(param_spec["type"], str), (
                            f"Tool '{tool['name']}' parameter '{param_name}' "
                            f"has invalid type specification"
                        )
    
    # Feature: irisvoice-backend-integration, Property 22: Tool Availability
    @given(
        category_filter=st.sampled_from([None, "vision", "web", "file", "system", "app", "gui"]),
        session_id=st.uuids().map(str)
    )
    @settings(max_examples=100, deadline=None)
    def test_tool_categories_are_valid(self, tool_bridge, category_filter, session_id):
        """
        Property 22: Tool Availability (Category Validation)
        
        For any tool in the available tools list, the category SHALL be one
        of the valid categories: vision, web, file, system, app, gui.
        
        **Validates: Requirements 8.1, 8.2**
        """
        # Get available tools
        tools = tool_bridge.get_available_tools()
        
        # Valid categories
        valid_categories = {"vision", "web", "file", "system", "app", "gui"}
        
        # Verify each tool has a valid category
        for tool in tools:
            category = tool.get("category")
            assert category in valid_categories, (
                f"Tool '{tool['name']}' has invalid category: {category}. "
                f"Valid categories are: {valid_categories}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--hypothesis-show-statistics"])
