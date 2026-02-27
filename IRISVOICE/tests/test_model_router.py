#!/usr/bin/env python3
"""
Unit tests for ModelWrapper and ModelRouter classes.

Tests the dual-LLM model routing functionality.
"""

import pytest
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from agent.model_router import ModelRouter
from agent.model_wrapper import ModelWrapper


class TestModelRouter:
    """Test ModelRouter functionality."""
    
    def test_router_initialization(self):
        """Test that ModelRouter initializes with config."""
        router = ModelRouter()
        assert router.is_ready()
        assert len(router.models) > 0
    
    def test_get_reasoning_model(self):
        """Test getting the reasoning model."""
        router = ModelRouter()
        reasoning_model = router.get_reasoning_model()
        assert reasoning_model is not None
        assert reasoning_model.has_capability("reasoning")
    
    def test_get_execution_model(self):
        """Test getting the execution model."""
        router = ModelRouter()
        execution_model = router.get_execution_model()
        assert execution_model is not None
        assert execution_model.has_capability("tool_execution")
    
    def test_route_message_reasoning(self):
        """Test routing a reasoning message to the reasoning model."""
        router = ModelRouter()
        
        # Test reasoning queries
        reasoning_queries = [
            "What is the best approach to solve this problem?",
            "Can you help me plan a strategy?",
            "I need to think through this carefully",
        ]
        
        for query in reasoning_queries:
            model_id = router.route_message(query)
            model = router.models[model_id]
            assert model.has_capability("reasoning"), f"Query '{query}' should route to reasoning model"
    
    def test_route_message_tool_execution(self):
        """Test routing a tool execution message to the execution model."""
        router = ModelRouter()
        
        # Test tool execution queries
        tool_queries = [
            "Execute the file operation",
            "Run the search tool",
            "Call the API function",
            "Invoke the browser automation",
            "Use tool: file_manager",
            "Perform action: click button",
        ]
        
        for query in tool_queries:
            model_id = router.route_message(query)
            model = router.models[model_id]
            assert model.has_capability("tool_execution"), f"Query '{query}' should route to execution model"
    
    def test_route_message_with_context_reasoning(self):
        """Test routing with explicit reasoning context."""
        router = ModelRouter()
        
        message = "Some message"
        context = {"requires_reasoning": True}
        
        model_id = router.route_message(message, context)
        model = router.models[model_id]
        assert model.has_capability("reasoning")
    
    def test_route_message_with_context_tools(self):
        """Test routing with explicit tool execution context."""
        router = ModelRouter()
        
        message = "Some message"
        context = {"requires_tools": True}
        
        model_id = router.route_message(message, context)
        model = router.models[model_id]
        assert model.has_capability("tool_execution")
    
    def test_list_available_capabilities(self):
        """Test listing all available capabilities."""
        router = ModelRouter()
        capabilities = router.list_available_capabilities()
        
        assert "reasoning" in capabilities
        assert "tool_execution" in capabilities
        assert len(capabilities) > 0
    
    def test_get_all_models_status(self):
        """Test getting status of all models."""
        router = ModelRouter()
        status = router.get_all_models_status()
        
        assert len(status) > 0
        for model_id, model_status in status.items():
            assert "model_id" in model_status
            assert "capabilities" in model_status
            assert "loaded" in model_status


class TestModelWrapper:
    """Test ModelWrapper functionality."""
    
    def test_model_wrapper_initialization(self):
        """Test ModelWrapper initialization."""
        wrapper = ModelWrapper(
            model_id="test_model",
            model_path="./test/path",
            capabilities=["reasoning"],
            constraints={"device": "cpu", "dtype": "float32"}
        )
        
        assert wrapper.model_id == "test_model"
        assert wrapper.model_path == "./test/path"
        assert wrapper.capabilities == ["reasoning"]
        assert wrapper.device == "cpu"
        assert wrapper.dtype == "float32"
    
    def test_has_capability(self):
        """Test capability checking."""
        wrapper = ModelWrapper(
            model_id="test_model",
            model_path="./test/path",
            capabilities=["reasoning", "planning"],
        )
        
        assert wrapper.has_capability("reasoning")
        assert wrapper.has_capability("planning")
        assert not wrapper.has_capability("tool_execution")
    
    def test_is_loaded_initially_false(self):
        """Test that model is not loaded initially (lazy loading)."""
        wrapper = ModelWrapper(
            model_id="test_model",
            model_path="./test/path",
            capabilities=["reasoning"],
        )
        
        assert not wrapper.is_loaded()
    
    def test_get_status(self):
        """Test getting model status."""
        wrapper = ModelWrapper(
            model_id="test_model",
            model_path="./test/path",
            capabilities=["reasoning"],
            constraints={"device": "cpu"}
        )
        
        status = wrapper.get_status()
        assert status["model_id"] == "test_model"
        assert status["model_path"] == "./test/path"
        assert status["capabilities"] == ["reasoning"]
        assert status["loaded"] == False
        assert status["device"] == "cpu"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
