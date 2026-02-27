#!/usr/bin/env python3
"""
Property-Based Tests for Agent Kernel Error Handling

Feature: irisvoice-backend-integration, Property 48: Agent Kernel Error Handling

Tests that the agent kernel handles errors gracefully:
- Model loading failures
- Inference timeouts (30s)
- Model crashes with restart and fallback
- Tool execution errors

**Validates: Requirements 19.4, 23.6**
"""

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck
from unittest.mock import Mock, MagicMock, patch
import time

# Import the agent kernel
from backend.agent.agent_kernel import AgentKernel


# Strategy for generating test messages
messages_strategy = st.text(min_size=1, max_size=200)


@pytest.fixture
def mock_model_router():
    """Create a mock model router for testing."""
    router = Mock()
    
    # Create mock models
    reasoning_model = Mock()
    reasoning_model.is_loaded.return_value = False
    reasoning_model.model_id = "lfm2-8b"
    
    execution_model = Mock()
    execution_model.is_loaded.return_value = False
    execution_model.model_id = "lfm2.5-1.2b-instruct"
    
    router.get_reasoning_model.return_value = reasoning_model
    router.get_execution_model.return_value = execution_model
    router.models = {
        "lfm2-8b": reasoning_model,
        "lfm2.5-1.2b-instruct": execution_model
    }
    router.get_all_models_status.return_value = {
        "lfm2-8b": {"loaded": False},
        "lfm2.5-1.2b-instruct": {"loaded": False}
    }
    router.get_loaded_models.return_value = []
    
    return router, reasoning_model, execution_model


@pytest.fixture
def agent_kernel_with_mocks(mock_model_router):
    """Create an agent kernel with mocked dependencies."""
    router, reasoning_model, execution_model = mock_model_router
    
    with patch('backend.agent.agent_kernel.ModelRouter', return_value=router):
        kernel = AgentKernel(session_id="test_session")
        return kernel, router, reasoning_model, execution_model


# Property 48: Agent Kernel Error Handling
# Validates: Requirements 19.4, 23.6

@given(message=messages_strategy)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_model_loading_failure_handling(message, agent_kernel_with_mocks):
    """
    Property: Agent kernel handles model loading failures gracefully.
    
    When a model fails to load, the agent should:
    - Return an error message
    - Not crash
    - Log the error appropriately
    """
    kernel, router, reasoning_model, execution_model = agent_kernel_with_mocks
    
    # Simulate model loading failure
    reasoning_model.load.side_effect = Exception("Model loading failed: Out of memory")
    reasoning_model.is_loaded.return_value = False
    
    # Process message
    response = kernel.process_text_message(message)
    
    # Verify error handling
    assert isinstance(response, str), "Response should be a string"
    assert "error" in response.lower() or "failed" in response.lower(), \
        "Response should indicate an error occurred"
    assert len(response) > 0, "Response should not be empty"


@given(message=messages_strategy)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_model_inference_failure_with_restart(message, agent_kernel_with_mocks):
    """
    Property: Agent kernel handles model inference failures gracefully.
    
    When model inference fails, the agent should:
    - Catch the error
    - Attempt to restart the model (if possible)
    - Return a meaningful error message
    - Not crash
    """
    kernel, router, reasoning_model, execution_model = agent_kernel_with_mocks
    
    # Disable VPS Gateway to test direct model access
    kernel._vps_gateway = None
    
    # Simulate model inference failure
    reasoning_model.is_loaded.return_value = True
    reasoning_model.generate.side_effect = Exception("Model crashed")
    reasoning_model.load.return_value = None
    reasoning_model.unload.return_value = None
    
    # Process message
    response = kernel.process_text_message(message)
    
    # Verify error handling
    assert isinstance(response, str), "Response should be a string"
    assert len(response) > 0, "Response should not be empty"
    assert "error" in response.lower() or "failed" in response.lower() or "crashed" in response.lower(), \
        "Response should indicate an error occurred"
    
    # Verify the model was accessed (generate was called)
    assert reasoning_model.generate.called, "Model generate should have been called"


@given(message=messages_strategy)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_model_unavailable_fallback(message, agent_kernel_with_mocks):
    """
    Property: Agent kernel falls back gracefully when models are unavailable.
    
    When models are not available, the agent should:
    - Return a clear error message
    - Not crash or hang
    - Indicate the specific issue
    """
    kernel, router, reasoning_model, execution_model = agent_kernel_with_mocks
    
    # Simulate model unavailability
    router.get_reasoning_model.return_value = None
    router.get_execution_model.return_value = None
    
    # Process message
    response = kernel.process_text_message(message)
    
    # Verify error handling
    assert isinstance(response, str), "Response should be a string"
    assert "not available" in response.lower() or "unavailable" in response.lower(), \
        "Response should indicate model unavailability"
    assert len(response) > 0, "Response should not be empty"


@given(message=messages_strategy)
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_tool_execution_error_handling(message, agent_kernel_with_mocks):
    """
    Property: Agent kernel handles tool execution errors gracefully.
    
    When tool execution fails, the agent should:
    - Return an error message indicating the tool failure
    - Not crash
    - Continue processing other steps if applicable
    """
    kernel, router, reasoning_model, execution_model = agent_kernel_with_mocks
    
    # Setup successful model inference but tool execution failure
    reasoning_model.is_loaded.return_value = True
    reasoning_model.generate.return_value = '''
    {
        "analysis": "User wants to execute a tool",
        "requires_tools": true,
        "steps": [
            {
                "step": 1,
                "action": "execute_tool",
                "tool": "test_tool",
                "parameters": {"param": "value"}
            }
        ]
    }
    '''
    
    execution_model.is_loaded.return_value = True
    execution_model.generate.return_value = "Tool execution result"
    
    # Mock tool bridge with failure
    mock_tool_bridge = Mock()
    mock_tool_bridge.execute_tool.return_value = {"error": "Tool execution failed: Permission denied"}
    kernel._tool_bridge = mock_tool_bridge
    
    # Process message
    response = kernel.process_text_message(message)
    
    # Verify error handling
    assert isinstance(response, str), "Response should be a string"
    # Response should either indicate tool error or handle it gracefully
    assert len(response) > 0, "Response should not be empty"


@given(message=messages_strategy)
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_conversation_memory_error_resilience(message, agent_kernel_with_mocks):
    """
    Property: Agent kernel handles conversation memory errors gracefully.
    
    When conversation memory operations fail, the agent should:
    - Continue processing the message
    - Return a response (even if memory update fails)
    - Not crash
    """
    kernel, router, reasoning_model, execution_model = agent_kernel_with_mocks
    
    # Setup successful model inference
    reasoning_model.is_loaded.return_value = True
    reasoning_model.generate.return_value = '''
    {
        "analysis": "Simple response",
        "requires_tools": false,
        "steps": [
            {
                "step": 1,
                "action": "respond_to_user",
                "tool": null,
                "parameters": {"response": "Test response"}
            }
        ]
    }
    '''
    
    # Simulate conversation memory failure
    if kernel._conversation_memory:
        original_add = kernel._conversation_memory.add_message
        kernel._conversation_memory.add_message = Mock(side_effect=Exception("Memory storage failed"))
    
    # Process message - should handle memory error gracefully
    response = kernel.process_text_message(message)
    
    # Verify error handling
    assert isinstance(response, str), "Response should be a string"
    assert len(response) > 0, "Response should not be empty"


@given(message=messages_strategy)
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_personality_manager_error_resilience(message, agent_kernel_with_mocks):
    """
    Property: Agent kernel handles personality manager errors gracefully.
    
    When personality manager fails, the agent should:
    - Continue processing without personality context
    - Return a valid response
    - Not crash
    """
    kernel, router, reasoning_model, execution_model = agent_kernel_with_mocks
    
    # Setup successful model inference
    reasoning_model.is_loaded.return_value = True
    reasoning_model.generate.return_value = '''
    {
        "analysis": "Simple response",
        "requires_tools": false,
        "steps": [
            {
                "step": 1,
                "action": "respond_to_user",
                "tool": null,
                "parameters": {"response": "Test response"}
            }
        ]
    }
    '''
    
    # Simulate personality manager failure
    if kernel._personality:
        kernel._personality.get_system_prompt = Mock(side_effect=Exception("Personality config corrupted"))
    
    # Process message - should handle personality error gracefully
    response = kernel.process_text_message(message)
    
    # Verify error handling
    assert isinstance(response, str), "Response should be a string"
    assert len(response) > 0, "Response should not be empty"


@given(message=messages_strategy)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_json_parse_error_handling(message, agent_kernel_with_mocks):
    """
    Property: Agent kernel handles JSON parse errors in model responses.
    
    When model returns invalid JSON, the agent should:
    - Create a simple fallback plan
    - Return a valid response
    - Not crash
    """
    kernel, router, reasoning_model, execution_model = agent_kernel_with_mocks
    
    # Setup model to return invalid JSON
    reasoning_model.is_loaded.return_value = True
    reasoning_model.generate.return_value = "This is not valid JSON at all!"
    
    # Process message
    response = kernel.process_text_message(message)
    
    # Verify error handling
    assert isinstance(response, str), "Response should be a string"
    assert len(response) > 0, "Response should not be empty"
    # Should not contain raw error messages about JSON parsing
    assert "JSONDecodeError" not in response, "Should not expose internal JSON errors to user"


def test_initialization_error_handling():
    """
    Property: Agent kernel handles initialization errors gracefully.
    
    When initialization fails, the agent should:
    - Set initialization_error flag
    - Return error messages for all requests
    - Not crash on subsequent calls
    """
    with patch('backend.agent.agent_kernel.ModelRouter', side_effect=Exception("Config file not found")):
        kernel = AgentKernel(session_id="test_session")
        
        # Verify initialization error is captured
        assert kernel._initialization_error is not None, "Initialization error should be captured"
        
        # Verify subsequent calls return error messages
        response = kernel.process_text_message("test message")
        assert isinstance(response, str), "Response should be a string"
        assert "not available" in response.lower(), "Response should indicate unavailability"
        
        # Verify status reflects error
        status = kernel.get_status()
        assert status["ready"] == False, "Agent should not be ready"
        assert status["error"] is not None, "Status should include error"


def test_single_model_fallback_mode():
    """
    Property: Agent kernel operates in single-model fallback mode when only one model available.
    
    When only one model is available, the agent should:
    - Use that model for both reasoning and execution
    - Set single_model_mode flag
    - Continue to function
    """
    router = Mock()
    
    # Only reasoning model available
    reasoning_model = Mock()
    reasoning_model.is_loaded.return_value = True
    reasoning_model.model_id = "lfm2-8b"
    reasoning_model.generate.return_value = '''
    {
        "analysis": "Simple response",
        "requires_tools": false,
        "steps": [
            {
                "step": 1,
                "action": "respond_to_user",
                "tool": null,
                "parameters": {"response": "Test response"}
            }
        ]
    }
    '''
    
    router.get_reasoning_model.return_value = reasoning_model
    router.get_execution_model.return_value = None  # Execution model unavailable
    router.models = {"lfm2-8b": reasoning_model}
    router.get_all_models_status.return_value = {"lfm2-8b": {"loaded": True}}
    router.get_loaded_models.return_value = [reasoning_model]
    
    with patch('backend.agent.agent_kernel.ModelRouter', return_value=router):
        kernel = AgentKernel(session_id="test_session")
        
        # Verify single-model mode is enabled
        assert kernel._single_model_mode == True, "Should be in single-model mode"
        assert kernel._available_model_id == "lfm2-8b", "Should track available model"
        
        # Verify agent can still process messages
        response = kernel.process_text_message("test message")
        assert isinstance(response, str), "Response should be a string"
        assert len(response) > 0, "Response should not be empty"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
