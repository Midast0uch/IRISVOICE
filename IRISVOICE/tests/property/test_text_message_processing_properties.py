"""
Property-based tests for text message processing.
Tests universal properties that should hold for text message processing,
including message handling, response format, and processing consistency.
"""
import pytest
from hypothesis import given, settings, strategies as st, seed
import sys
import os
from unittest.mock import Mock, patch
import json

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.agent.agent_kernel import AgentKernel


# ============================================================================
# Test Data Generators (Hypothesis Strategies)
# ============================================================================

@st.composite
def text_message(draw):
    """Generate realistic text messages."""
    return draw(st.one_of(
        # Simple questions
        st.sampled_from([
            "What is the weather today?",
            "Can you help me with this task?",
            "How do I solve this problem?",
            "Tell me about artificial intelligence",
            "What are the best practices for coding?",
            "Explain quantum computing",
            "How does machine learning work?",
        ]),
        # Commands
        st.sampled_from([
            "Search for information about Python",
            "Open the browser",
            "Create a new file",
            "Run the tests",
            "Deploy the application",
            "Show me the logs",
            "Check system status",
        ]),
        # General text (alphanumeric with common punctuation)
        st.text(min_size=1, max_size=200, alphabet=st.characters(
            whitelist_categories=('Lu', 'Ll', 'Nd', 'Zs'),
            whitelist_characters='?!.,;:\'"'
        ))
    ))


@st.composite
def session_id_generator(draw):
    """Generate valid session IDs."""
    return draw(st.one_of(
        st.text(min_size=1, max_size=50, alphabet=st.characters(
            whitelist_categories=('Lu', 'Ll', 'Nd'),
            whitelist_characters='-_'
        )),
        st.uuids().map(str)
    ))


# ============================================================================
# Property 13: Text Message Processing
# Feature: irisvoice-backend-integration, Property 13: Text Message Processing
# Validates: Requirements 5.1, 5.2
# ============================================================================

class TestTextMessageProcessing:
    """
    Property 13: Text Message Processing
    
    For any text_message received by the backend, the Agent_Kernel shall 
    process it using the lfm2-8b model and send a text_response.
    
    This tests:
    - Requirement 5.1: Text message processing
    - Requirement 5.2: Agent response format
    """
    
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        message=text_message(),
        session_id=session_id_generator()
    )
    def test_text_message_processed_and_response_generated(self, message, session_id):
        """
        Property: For any text message, the agent processes it and generates a response.
        
        # Feature: irisvoice-backend-integration, Property 13: Text Message Processing
        **Validates: Requirements 5.1, 5.2**
        """
        # Setup: Create kernel with mocked models
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            # Create mock reasoning model (lfm2-8b)
            mock_reasoning_model = Mock()
            mock_reasoning_model.model_id = "lfm2-8b"
            mock_reasoning_model.is_loaded.return_value = False
            mock_reasoning_model.load.return_value = None
            mock_reasoning_model.generate.return_value = json.dumps({
                "analysis": "Processing user text message",
                "requires_tools": False,
                "steps": [{
                    "step": 1,
                    "action": "Generate text response",
                    "tool": None,
                    "parameters": {}
                }]
            })
            
            # Create mock execution model (lfm2.5-1.2b-instruct)
            mock_execution_model = Mock()
            mock_execution_model.model_id = "lfm2.5-1.2b-instruct"
            mock_execution_model.is_loaded.return_value = False
            mock_execution_model.load.return_value = None
            mock_execution_model.generate.return_value = "Text response generated"
            
            # Setup mock router
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_reasoning_model
            mock_router.get_execution_model.return_value = mock_execution_model
            mock_router.models = {
                "reasoning": mock_reasoning_model,
                "execution": mock_execution_model
            }
            mock_router_class.return_value = mock_router
            
            # Create kernel
            kernel = AgentKernel(session_id=session_id)
            
            # Execute: Process the text message
            response = kernel.process_text_message(message, session_id)
            
            # Verify: Response is generated
            assert response is not None, "Agent must generate a response for text message"
            assert isinstance(response, str), "Response must be a string"
            assert len(response) > 0, "Response must not be empty"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        message=text_message(),
        session_id=session_id_generator()
    )
    def test_text_message_uses_reasoning_model(self, message, session_id):
        """
        Property: For any text message, the agent uses the lfm2-8b reasoning model.
        
        # Feature: irisvoice-backend-integration, Property 13: Text Message Processing
        **Validates: Requirements 5.1**
        """
        # Setup: Create kernel with mocked models
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            # Track model calls
            reasoning_calls = []
            execution_calls = []
            
            def reasoning_generate(prompt, **kwargs):
                reasoning_calls.append(prompt)
                return json.dumps({
                    "analysis": "Using reasoning model",
                    "requires_tools": False,
                    "steps": [{
                        "step": 1,
                        "action": "Generate response",
                        "tool": None,
                        "parameters": {}
                    }]
                })
            
            def execution_generate(prompt, **kwargs):
                execution_calls.append(prompt)
                return "Response from execution model"
            
            mock_reasoning_model = Mock()
            mock_reasoning_model.model_id = "lfm2-8b"
            mock_reasoning_model.is_loaded.return_value = False
            mock_reasoning_model.load.return_value = None
            mock_reasoning_model.generate.side_effect = reasoning_generate
            
            mock_execution_model = Mock()
            mock_execution_model.model_id = "lfm2.5-1.2b-instruct"
            mock_execution_model.is_loaded.return_value = False
            mock_execution_model.load.return_value = None
            mock_execution_model.generate.side_effect = execution_generate
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_reasoning_model
            mock_router.get_execution_model.return_value = mock_execution_model
            mock_router.models = {
                "reasoning": mock_reasoning_model,
                "execution": mock_execution_model
            }
            mock_router_class.return_value = mock_router
            
            kernel = AgentKernel(session_id=session_id)
            
            # Execute: Process the text message
            response = kernel.process_text_message(message, session_id)
            
            # Verify: Reasoning model (lfm2-8b) was called
            assert len(reasoning_calls) > 0, \
                "Reasoning model (lfm2-8b) must be called for text message processing"
            assert response is not None
            assert isinstance(response, str)
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        message=text_message(),
        session_id=session_id_generator()
    )
    def test_text_message_response_format_valid(self, message, session_id):
        """
        Property: For any text message, the response format is valid (string, non-empty).
        
        # Feature: irisvoice-backend-integration, Property 13: Text Message Processing
        **Validates: Requirements 5.2**
        """
        # Setup: Create kernel with mocked models
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            mock_reasoning_model = Mock()
            mock_reasoning_model.model_id = "lfm2-8b"
            mock_reasoning_model.is_loaded.return_value = False
            mock_reasoning_model.load.return_value = None
            mock_reasoning_model.generate.return_value = json.dumps({
                "analysis": "Valid format",
                "requires_tools": False,
                "steps": [{
                    "step": 1,
                    "action": "Return valid response",
                    "tool": None,
                    "parameters": {}
                }]
            })
            
            mock_execution_model = Mock()
            mock_execution_model.model_id = "lfm2.5-1.2b-instruct"
            mock_execution_model.is_loaded.return_value = False
            mock_execution_model.load.return_value = None
            mock_execution_model.generate.return_value = "Valid formatted text response"
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_reasoning_model
            mock_router.get_execution_model.return_value = mock_execution_model
            mock_router.models = {
                "reasoning": mock_reasoning_model,
                "execution": mock_execution_model
            }
            mock_router_class.return_value = mock_router
            
            kernel = AgentKernel(session_id=session_id)
            
            # Execute: Process the text message
            response = kernel.process_text_message(message, session_id)
            
            # Verify: Response format is valid
            assert isinstance(response, str), "Response must be a string"
            assert len(response) > 0, "Response must not be empty"
            # Response should be human-readable text
            assert any(c in response for c in [' ', '.', ',', '!', '?']) or len(response) < 50, \
                "Response should be human-readable text"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        message=text_message(),
        session_id=session_id_generator()
    )
    def test_text_message_added_to_conversation_memory(self, message, session_id):
        """
        Property: For any text message, both the message and response are added to memory.
        
        # Feature: irisvoice-backend-integration, Property 13: Text Message Processing
        **Validates: Requirements 5.1**
        """
        # Setup: Create kernel with mocked models
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            mock_reasoning_model = Mock()
            mock_reasoning_model.model_id = "lfm2-8b"
            mock_reasoning_model.is_loaded.return_value = False
            mock_reasoning_model.load.return_value = None
            mock_reasoning_model.generate.return_value = json.dumps({
                "analysis": "Memory test",
                "requires_tools": False,
                "steps": [{
                    "step": 1,
                    "action": "Respond",
                    "tool": None,
                    "parameters": {}
                }]
            })
            
            mock_execution_model = Mock()
            mock_execution_model.model_id = "lfm2.5-1.2b-instruct"
            mock_execution_model.is_loaded.return_value = False
            mock_execution_model.load.return_value = None
            mock_execution_model.generate.return_value = "Memory test response"
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_reasoning_model
            mock_router.get_execution_model.return_value = mock_execution_model
            mock_router.models = {
                "reasoning": mock_reasoning_model,
                "execution": mock_execution_model
            }
            mock_router_class.return_value = mock_router
            
            kernel = AgentKernel(session_id=session_id)
            
            # Clear any existing messages
            kernel._conversation_memory.clear()
            
            # Execute: Process the text message
            response = kernel.process_text_message(message, session_id)
            
            # Verify: Both user message and assistant response are in memory
            context = kernel._conversation_memory.get_context()
            assert len(context) == 2, \
                "Both user message and assistant response should be in memory"
            
            # Verify the first message is the user's text message
            assert context[0]["role"] == "user", \
                "First message should be from user"
            assert context[0]["content"] == message, \
                "First message content should match the input text message"
            
            # Verify the second message is the assistant's response
            assert context[1]["role"] == "assistant", \
                "Second message should be from assistant"
            assert context[1]["content"] == response, \
                "Second message content should match the response"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        message=text_message(),
        session_id=session_id_generator()
    )
    def test_text_message_processing_consistency(self, message, session_id):
        """
        Property: For any text message, processing is consistent and deterministic.
        
        # Feature: irisvoice-backend-integration, Property 13: Text Message Processing
        **Validates: Requirements 5.1, 5.2**
        """
        # Setup: Create kernel with mocked models
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            mock_reasoning_model = Mock()
            mock_reasoning_model.model_id = "lfm2-8b"
            mock_reasoning_model.is_loaded.return_value = False
            mock_reasoning_model.load.return_value = None
            mock_reasoning_model.generate.return_value = json.dumps({
                "analysis": "Consistent processing",
                "requires_tools": False,
                "steps": [{
                    "step": 1,
                    "action": "Generate consistent response",
                    "tool": None,
                    "parameters": {}
                }]
            })
            
            mock_execution_model = Mock()
            mock_execution_model.model_id = "lfm2.5-1.2b-instruct"
            mock_execution_model.is_loaded.return_value = False
            mock_execution_model.load.return_value = None
            mock_execution_model.generate.return_value = "Consistent response"
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_reasoning_model
            mock_router.get_execution_model.return_value = mock_execution_model
            mock_router.models = {
                "reasoning": mock_reasoning_model,
                "execution": mock_execution_model
            }
            mock_router_class.return_value = mock_router
            
            kernel = AgentKernel(session_id=session_id)
            
            # Clear memory for clean test
            kernel._conversation_memory.clear()
            
            # Execute: Process the same message twice
            response1 = kernel.process_text_message(message, session_id)
            
            # Clear memory between calls to ensure independence
            kernel._conversation_memory.clear()
            
            response2 = kernel.process_text_message(message, session_id)
            
            # Verify: Both responses are valid and consistent in format
            assert isinstance(response1, str) and isinstance(response2, str), \
                "Both responses must be strings"
            assert len(response1) > 0 and len(response2) > 0, \
                "Both responses must not be empty"
            # With mocked models returning the same output, responses should be identical
            assert response1 == response2, \
                "Processing the same message should produce consistent results with same model outputs"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        message=text_message(),
        session_id=session_id_generator()
    )
    def test_text_message_handles_unavailable_agent(self, message, session_id):
        """
        Property: For any text message when agent is unavailable, returns error message.
        
        # Feature: irisvoice-backend-integration, Property 13: Text Message Processing
        **Validates: Requirements 5.1**
        """
        # Setup: Create kernel with no models available
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = None
            mock_router.get_execution_model.return_value = None
            mock_router.models = {}
            mock_router_class.return_value = mock_router
            
            kernel = AgentKernel(session_id=session_id)
            
            # Execute: Process the text message
            response = kernel.process_text_message(message, session_id)
            
            # Verify: Error message is returned
            assert response is not None, "Must return a response even when unavailable"
            assert isinstance(response, str), "Error response must be a string"
            assert len(response) > 0, "Error response must not be empty"
            assert "not available" in response.lower() or "unavailable" in response.lower(), \
                "Error message should indicate agent is not available"
