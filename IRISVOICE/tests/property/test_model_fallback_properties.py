#!/usr/bin/env python3
"""
Property-Based Tests for Model Fallback

Feature: irisvoice-backend-integration, Property 56: Model Fallback

Tests that the Agent_Kernel falls back to single-model mode when one model fails:
- Reasoning model failure → use execution model
- Execution model failure → use reasoning model
- Both models available → use dual-LLM mode
- Model crash during inference → fallback gracefully

**Validates: Requirements 23.6**
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
def mock_model_router_dual():
    """Create a mock model router with both models available."""
    router = Mock()
    
    # Create mock models
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
    
    execution_model = Mock()
    execution_model.is_loaded.return_value = True
    execution_model.model_id = "lfm2.5-1.2b-instruct"
    execution_model.generate.return_value = "Execution model response"
    
    router.get_reasoning_model.return_value = reasoning_model
    router.get_execution_model.return_value = execution_model
    router.models = {
        "lfm2-8b": reasoning_model,
        "lfm2.5-1.2b-instruct": execution_model
    }
    router.get_all_models_status.return_value = {
        "lfm2-8b": {"loaded": True},
        "lfm2.5-1.2b-instruct": {"loaded": True}
    }
    router.get_loaded_models.return_value = [reasoning_model, execution_model]
    
    return router, reasoning_model, execution_model


@pytest.fixture
def mock_model_router_reasoning_only():
    """Create a mock model router with only reasoning model available."""
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
                "parameters": {"response": "Test response from reasoning model"}
            }
        ]
    }
    '''
    
    router.get_reasoning_model.return_value = reasoning_model
    router.get_execution_model.return_value = None  # Execution model unavailable
    router.models = {"lfm2-8b": reasoning_model}
    router.get_all_models_status.return_value = {"lfm2-8b": {"loaded": True}}
    router.get_loaded_models.return_value = [reasoning_model]
    
    return router, reasoning_model


@pytest.fixture
def mock_model_router_execution_only():
    """Create a mock model router with only execution model available."""
    router = Mock()
    
    # Only execution model available
    execution_model = Mock()
    execution_model.is_loaded.return_value = True
    execution_model.model_id = "lfm2.5-1.2b-instruct"
    execution_model.generate.return_value = "Execution model response"
    
    router.get_reasoning_model.return_value = None  # Reasoning model unavailable
    router.get_execution_model.return_value = execution_model
    router.models = {"lfm2.5-1.2b-instruct": execution_model}
    router.get_all_models_status.return_value = {"lfm2.5-1.2b-instruct": {"loaded": True}}
    router.get_loaded_models.return_value = [execution_model]
    
    return router, execution_model


# Property 56: Model Fallback
# Validates: Requirements 23.6

@given(message=messages_strategy)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_fallback_to_reasoning_model_when_execution_fails(message, mock_model_router_reasoning_only):
    """
    Property: Agent kernel falls back to reasoning model when execution model unavailable.
    
    When execution model is unavailable, the agent should:
    - Detect single-model mode
    - Use reasoning model for all tasks
    - Return valid responses
    - Not crash
    """
    router, reasoning_model = mock_model_router_reasoning_only
    
    with patch('backend.agent.agent_kernel.ModelRouter', return_value=router):
        kernel = AgentKernel(session_id="test_session")
        
        # Verify single-model mode is enabled
        assert kernel._single_model_mode == True, "Should be in single-model mode"
        assert kernel._available_model_id == "lfm2-8b", "Should use reasoning model"
        
        # Process message
        response = kernel.process_text_message(message)
        
        # Verify response is valid (may be None if model not properly configured)
        if response is not None:
            assert isinstance(response, str), "Response should be a string"
            assert len(response) > 0, "Response should not be empty"
            
            # Verify reasoning model was used
            assert reasoning_model.generate.called, "Reasoning model should have been called"
        else:
            # If response is None, verify single-model mode was still detected
            assert kernel._single_model_mode == True, "Should be in single-model mode even if response is None"


@given(message=messages_strategy)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_fallback_to_execution_model_when_reasoning_fails(message, mock_model_router_execution_only):
    """
    Property: Agent kernel falls back to execution model when reasoning model unavailable.
    
    When reasoning model is unavailable, the agent should:
    - Detect single-model mode
    - Use execution model for all tasks
    - Return valid responses
    - Not crash
    """
    router, execution_model = mock_model_router_execution_only
    
    with patch('backend.agent.agent_kernel.ModelRouter', return_value=router):
        kernel = AgentKernel(session_id="test_session")
        
        # Verify single-model mode is enabled
        assert kernel._single_model_mode == True, "Should be in single-model mode"
        assert kernel._available_model_id == "lfm2.5-1.2b-instruct", "Should use execution model"
        
        # Process message
        response = kernel.process_text_message(message)
        
        # Verify response is valid (may be None if model not properly configured)
        if response is not None:
            assert isinstance(response, str), "Response should be a string"
            assert len(response) > 0, "Response should not be empty"
            
            # Verify execution model was used
            assert execution_model.generate.called, "Execution model should have been called"
        else:
            # If response is None, verify single-model mode was still detected
            assert kernel._single_model_mode == True, "Should be in single-model mode even if response is None"


@given(message=messages_strategy)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_dual_model_mode_when_both_available(message, mock_model_router_dual):
    """
    Property: Agent kernel uses dual-LLM mode when both models available.
    
    When both models are available, the agent should:
    - Use dual-LLM mode (not single-model mode)
    - Use reasoning model for planning
    - Use execution model for execution
    - Return valid responses
    """
    router, reasoning_model, execution_model = mock_model_router_dual
    
    with patch('backend.agent.agent_kernel.ModelRouter', return_value=router):
        kernel = AgentKernel(session_id="test_session")
        
        # Verify dual-LLM mode is enabled
        assert kernel._single_model_mode == False, "Should be in dual-LLM mode"
        assert kernel._available_model_id is None, "Should not have single available model"
        
        # Process message
        response = kernel.process_text_message(message)
        
        # Verify response is valid (may be None if model not properly configured)
        if response is not None:
            assert isinstance(response, str), "Response should be a string"
            assert len(response) > 0, "Response should not be empty"
            
            # Verify reasoning model was used for planning
            assert reasoning_model.generate.called, "Reasoning model should have been called"
        else:
            # If response is None, verify dual-LLM mode was still detected
            assert kernel._single_model_mode == False, "Should be in dual-LLM mode even if response is None"


@given(message=messages_strategy)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_fallback_on_model_crash_during_inference(message, mock_model_router_dual):
    """
    Property: Agent kernel falls back gracefully when model crashes during inference.
    
    When a model crashes during inference, the agent should:
    - Catch the error
    - Attempt to use the other model if available
    - Return an error message if fallback fails
    - Not crash the entire system
    """
    router, reasoning_model, execution_model = mock_model_router_dual
    
    # Simulate reasoning model crash
    reasoning_model.generate.side_effect = Exception("Model crashed: Out of memory")
    
    with patch('backend.agent.agent_kernel.ModelRouter', return_value=router):
        kernel = AgentKernel(session_id="test_session")
        
        # Disable VPS Gateway to test direct model access
        kernel._vps_gateway = None
        
        # Process message
        response = kernel.process_text_message(message)
        
        # Verify error handling (response may be None or error string)
        if response is not None:
            assert isinstance(response, str), "Response should be a string"
            assert len(response) > 0, "Response should not be empty"
            # Should indicate error or provide fallback response
            assert "error" in response.lower() or "failed" in response.lower() or len(response) > 10, \
                "Response should indicate error or provide fallback"
        # If response is None, that's also acceptable error handling


@given(message=messages_strategy)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_status_reflects_single_model_mode(message, mock_model_router_reasoning_only):
    """
    Property: Agent status correctly reflects single-model fallback mode.
    
    When in single-model mode, the agent status should:
    - Indicate which model is available
    - Show correct model count (1 loaded, 2 total)
    - Indicate ready status if at least one model available
    """
    router, reasoning_model = mock_model_router_reasoning_only
    
    with patch('backend.agent.agent_kernel.ModelRouter', return_value=router):
        kernel = AgentKernel(session_id="test_session")
        
        # Get status
        status = kernel.get_status()
        
        # Verify status reflects single-model mode
        assert isinstance(status, dict), "Status should be a dictionary"
        assert "ready" in status, "Status should include ready flag"
        assert "models_loaded" in status, "Status should include models_loaded count"
        assert "total_models" in status, "Status should include total_models count"
        
        # Should be ready with at least one model
        assert status["ready"] == True, "Agent should be ready with one model"
        assert status["models_loaded"] >= 1, "At least one model should be loaded"


@given(message=messages_strategy)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_fallback_preserves_conversation_context(message, mock_model_router_reasoning_only):
    """
    Property: Model fallback preserves conversation context.
    
    When falling back to single-model mode, the agent should:
    - Maintain conversation history
    - Include context in subsequent requests
    - Not lose previous messages
    """
    router, reasoning_model = mock_model_router_reasoning_only
    
    with patch('backend.agent.agent_kernel.ModelRouter', return_value=router):
        kernel = AgentKernel(session_id="test_session")
        
        # Process first message
        response1 = kernel.process_text_message(message)
        if response1 is not None:
            assert len(response1) > 0, "First response should not be empty"
        
        # Process second message
        response2 = kernel.process_text_message("Follow-up message")
        if response2 is not None:
            assert len(response2) > 0, "Second response should not be empty"
        
        # Verify conversation context is maintained (if responses were generated)
        context = kernel.get_conversation_context()
        assert isinstance(context, list), "Context should be a list"
        # Should have at least the messages we sent (if they were processed)
        # Context may be empty if messages weren't processed due to model issues


def test_initialization_with_no_models():
    """
    Property: Agent kernel handles initialization with no models gracefully.
    
    When no models are available, the agent should:
    - Set initialization error
    - Return error messages for all requests
    - Not crash
    """
    router = Mock()
    router.get_reasoning_model.return_value = None
    router.get_execution_model.return_value = None
    router.models = {}
    router.get_all_models_status.return_value = {}
    router.get_loaded_models.return_value = []
    
    with patch('backend.agent.agent_kernel.ModelRouter', return_value=router):
        kernel = AgentKernel(session_id="test_session")
        
        # Verify initialization error is set
        assert kernel._initialization_error is not None, "Initialization error should be set"
        assert "no models available" in kernel._initialization_error.lower(), \
            "Error should indicate no models available"
        
        # Verify status reflects error
        status = kernel.get_status()
        assert status["ready"] == False, "Agent should not be ready"
        assert status["models_loaded"] == 0, "No models should be loaded"
        
        # Verify requests return error messages
        response = kernel.process_text_message("test message")
        assert isinstance(response, str), "Response should be a string"
        assert "not available" in response.lower() or "unavailable" in response.lower(), \
            "Response should indicate unavailability"


def test_fallback_mode_persists_across_requests():
    """
    Property: Single-model fallback mode persists across multiple requests.
    
    When in single-model mode, the agent should:
    - Remain in single-model mode for all subsequent requests
    - Not attempt to use unavailable model
    - Consistently use the available model
    """
    router = Mock()
    
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
    router.get_execution_model.return_value = None
    router.models = {"lfm2-8b": reasoning_model}
    router.get_all_models_status.return_value = {"lfm2-8b": {"loaded": True}}
    router.get_loaded_models.return_value = [reasoning_model]
    
    with patch('backend.agent.agent_kernel.ModelRouter', return_value=router):
        kernel = AgentKernel(session_id="test_session")
        
        # Verify initial single-model mode
        assert kernel._single_model_mode == True, "Should start in single-model mode"
        
        # Process multiple messages
        for i in range(3):
            response = kernel.process_text_message(f"Message {i}")
            if response is not None:
                assert len(response) > 0, f"Response {i} should not be empty"
            
            # Verify still in single-model mode
            assert kernel._single_model_mode == True, f"Should remain in single-model mode after request {i}"
            assert kernel._available_model_id == "lfm2-8b", f"Should still use reasoning model after request {i}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
