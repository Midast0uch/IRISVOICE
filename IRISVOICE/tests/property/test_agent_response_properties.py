"""
Property-based tests for agent response generation.
Tests universal properties that should hold for agent response generation,
context awareness, response format, and error handling.
"""
import pytest
from hypothesis import given, settings, strategies as st, seed
import sys
import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch
import json

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.agent.agent_kernel import AgentKernel
from backend.agent.memory import ConversationMemory


# ============================================================================
# Test Data Generators (Hypothesis Strategies)
# ============================================================================

@st.composite
def user_message(draw):
    """Generate realistic user messages."""
    return draw(st.one_of(
        # Simple questions
        st.sampled_from([
            "What is the weather today?",
            "Can you help me with this task?",
            "How do I solve this problem?",
            "Tell me about artificial intelligence",
            "What are the best practices for coding?",
        ]),
        # Commands
        st.sampled_from([
            "Search for information about Python",
            "Open the browser",
            "Create a new file",
            "Run the tests",
            "Deploy the application",
        ]),
        # General text
        st.text(min_size=1, max_size=200, alphabet=st.characters(
            whitelist_categories=('Lu', 'Ll', 'Nd', 'Zs'),
            whitelist_characters='?!.,;:'
        ))
    ))


@st.composite
def conversation_history(draw):
    """Generate a conversation history with multiple messages."""
    num_messages = draw(st.integers(min_value=0, max_value=10))
    messages = []
    for _ in range(num_messages):
        role = draw(st.sampled_from(["user", "assistant"]))
        content = draw(user_message())
        messages.append({"role": role, "content": content})
    return messages


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
# Property 9: Agent Response Generation
# Feature: irisvoice-backend-integration, Property 9: Agent Response Generation
# Validates: Requirements 3.7, 3.8, 5.2, 5.3
# ============================================================================

class TestAgentResponseGeneration:
    """
    Property 9: Agent Response Generation
    
    For any processed voice command or text message, the Agent_Kernel shall 
    generate a response and send a text_response message.
    
    This tests:
    - Requirement 3.7: Agent response generation
    - Requirement 3.8: Agent context awareness
    - Requirement 5.2: Agent response format
    - Requirement 5.3: Agent error handling
    """
    
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        message=user_message(),
        session_id=session_id_generator()
    )
    def test_agent_generates_response_for_any_message(self, message, session_id):
        """
        Property: For any text message, the agent generates a response.
        
        # Feature: irisvoice-backend-integration, Property 9: Agent Response Generation
        **Validates: Requirements 3.7, 5.2**
        """
        # Setup: Create kernel with mocked models
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            # Create mock reasoning model
            mock_reasoning_model = Mock()
            mock_reasoning_model.model_id = "reasoning"
            mock_reasoning_model.is_loaded.return_value = False
            mock_reasoning_model.load.return_value = None
            mock_reasoning_model.generate.return_value = json.dumps({
                "analysis": "Processing user request",
                "requires_tools": False,
                "steps": [{
                    "step": 1,
                    "action": "Respond to user",
                    "tool": None,
                    "parameters": {}
                }]
            })
            
            # Create mock execution model
            mock_execution_model = Mock()
            mock_execution_model.model_id = "execution"
            mock_execution_model.is_loaded.return_value = False
            mock_execution_model.load.return_value = None
            mock_execution_model.generate.return_value = "Response generated"
            
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
            
            # Execute: Process the message
            response = kernel.process_text_message(message, session_id)
            
            # Verify: Response is generated
            assert response is not None, "Agent must generate a response"
            assert isinstance(response, str), "Response must be a string"
            assert len(response) > 0, "Response must not be empty"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        message=user_message(),
        history=conversation_history(),
        session_id=session_id_generator()
    )
    def test_agent_maintains_context_awareness(self, message, history, session_id):
        """
        Property: For any message with conversation history, the agent 
        maintains context awareness.
        
        # Feature: irisvoice-backend-integration, Property 9: Agent Response Generation
        **Validates: Requirements 3.8**
        """
        # Setup: Create kernel with mocked models
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            # Create mock reasoning model that captures the prompt
            captured_prompts = []
            
            def capture_generate(prompt, **kwargs):
                captured_prompts.append(prompt)
                return json.dumps({
                    "analysis": "Processing with context",
                    "requires_tools": False,
                    "steps": [{
                        "step": 1,
                        "action": "Respond with context",
                        "tool": None,
                        "parameters": {}
                    }]
                })
            
            mock_reasoning_model = Mock()
            mock_reasoning_model.model_id = "reasoning"
            mock_reasoning_model.is_loaded.return_value = False
            mock_reasoning_model.load.return_value = None
            mock_reasoning_model.generate.side_effect = capture_generate
            
            mock_execution_model = Mock()
            mock_execution_model.model_id = "execution"
            mock_execution_model.is_loaded.return_value = False
            mock_execution_model.load.return_value = None
            mock_execution_model.generate.return_value = "Context-aware response"
            
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
            
            # Add conversation history
            for msg in history:
                kernel._conversation_memory.add_message(msg["role"], msg["content"])
            
            # Execute: Process the message
            response = kernel.process_text_message(message, session_id)
            
            # Verify: Context is included in the prompt
            assert len(captured_prompts) > 0, "Model should be called"
            prompt = captured_prompts[0]
            
            # If there's history, it should be included in the prompt
            if len(history) > 0:
                assert "Conversation Context" in prompt or "context" in prompt.lower(), \
                    "Prompt should include conversation context when history exists"
            
            # Response should be generated
            assert response is not None
            assert isinstance(response, str)
            assert len(response) > 0
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        message=user_message(),
        session_id=session_id_generator()
    )
    def test_agent_response_format_is_valid(self, message, session_id):
        """
        Property: For any message, the agent response format is valid (string).
        
        # Feature: irisvoice-backend-integration, Property 9: Agent Response Generation
        **Validates: Requirements 5.2**
        """
        # Setup: Create kernel with mocked models
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            mock_reasoning_model = Mock()
            mock_reasoning_model.model_id = "reasoning"
            mock_reasoning_model.is_loaded.return_value = False
            mock_reasoning_model.load.return_value = None
            mock_reasoning_model.generate.return_value = json.dumps({
                "analysis": "Valid response",
                "requires_tools": False,
                "steps": [{
                    "step": 1,
                    "action": "Generate valid response",
                    "tool": None,
                    "parameters": {}
                }]
            })
            
            mock_execution_model = Mock()
            mock_execution_model.model_id = "execution"
            mock_execution_model.is_loaded.return_value = False
            mock_execution_model.load.return_value = None
            mock_execution_model.generate.return_value = "Valid formatted response"
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_reasoning_model
            mock_router.get_execution_model.return_value = mock_execution_model
            mock_router.models = {
                "reasoning": mock_reasoning_model,
                "execution": mock_execution_model
            }
            mock_router_class.return_value = mock_router
            
            kernel = AgentKernel(session_id=session_id)
            
            # Execute: Process the message
            response = kernel.process_text_message(message, session_id)
            
            # Verify: Response format is valid
            assert isinstance(response, str), "Response must be a string"
            assert len(response) > 0, "Response must not be empty"
            # Response should be human-readable (contains spaces or punctuation)
            assert any(c in response for c in [' ', '.', ',', '!', '?']) or len(response) < 50, \
                "Response should be human-readable text"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        message=user_message(),
        session_id=session_id_generator()
    )
    def test_agent_handles_model_errors_gracefully(self, message, session_id):
        """
        Property: For any message when models fail, the agent returns an error message.
        
        # Feature: irisvoice-backend-integration, Property 9: Agent Response Generation
        **Validates: Requirements 5.3**
        """
        # Setup: Create kernel with failing models
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            # Create mock that raises an exception
            mock_reasoning_model = Mock()
            mock_reasoning_model.model_id = "reasoning"
            mock_reasoning_model.is_loaded.return_value = False
            mock_reasoning_model.load.side_effect = Exception("Model load failed")
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_reasoning_model
            mock_router.get_execution_model.return_value = None
            mock_router.models = {"reasoning": mock_reasoning_model}
            mock_router_class.return_value = mock_router
            
            kernel = AgentKernel(session_id=session_id)
            
            # Execute: Process the message
            response = kernel.process_text_message(message, session_id)
            
            # Verify: Error is handled gracefully
            assert response is not None, "Agent must return a response even on error"
            assert isinstance(response, str), "Error response must be a string"
            assert len(response) > 0, "Error response must not be empty"
            # Error message should indicate the problem
            assert any(keyword in response.lower() for keyword in [
                'error', 'failed', 'unavailable', 'not available', 'issue'
            ]), "Error response should indicate the problem"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        message=user_message(),
        session_id=session_id_generator()
    )
    def test_agent_handles_unavailable_models(self, message, session_id):
        """
        Property: For any message when models are unavailable, the agent 
        returns an appropriate error message.
        
        # Feature: irisvoice-backend-integration, Property 9: Agent Response Generation
        **Validates: Requirements 5.3**
        """
        # Setup: Create kernel with no models available
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = None
            mock_router.get_execution_model.return_value = None
            mock_router.models = {}
            mock_router_class.return_value = mock_router
            
            kernel = AgentKernel(session_id=session_id)
            
            # Execute: Process the message
            response = kernel.process_text_message(message, session_id)
            
            # Verify: Appropriate error message is returned
            assert response is not None
            assert isinstance(response, str)
            assert len(response) > 0
            assert "not available" in response.lower() or "unavailable" in response.lower(), \
                "Error message should indicate models are not available"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        message=user_message(),
        session_id=session_id_generator()
    )
    def test_agent_response_added_to_conversation_memory(self, message, session_id):
        """
        Property: For any message, the agent's response is added to conversation memory.
        
        # Feature: irisvoice-backend-integration, Property 9: Agent Response Generation
        **Validates: Requirements 3.8**
        """
        # Setup: Create kernel with mocked models
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            mock_reasoning_model = Mock()
            mock_reasoning_model.model_id = "reasoning"
            mock_reasoning_model.is_loaded.return_value = False
            mock_reasoning_model.load.return_value = None
            mock_reasoning_model.generate.return_value = json.dumps({
                "analysis": "Test",
                "requires_tools": False,
                "steps": [{
                    "step": 1,
                    "action": "Respond",
                    "tool": None,
                    "parameters": {}
                }]
            })
            
            mock_execution_model = Mock()
            mock_execution_model.model_id = "execution"
            mock_execution_model.is_loaded.return_value = False
            mock_execution_model.load.return_value = None
            mock_execution_model.generate.return_value = "Test response"
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_reasoning_model
            mock_router.get_execution_model.return_value = mock_execution_model
            mock_router.models = {
                "reasoning": mock_reasoning_model,
                "execution": mock_execution_model
            }
            mock_router_class.return_value = mock_router
            
            kernel = AgentKernel(session_id=session_id)
            
            # Clear any existing messages to start fresh
            kernel._conversation_memory.clear()
            
            # Execute: Process the message
            response = kernel.process_text_message(message, session_id)
            
            # Verify: Both user message and assistant response are in memory
            context = kernel._conversation_memory.get_context()
            assert len(context) == 2, \
                "Both user message and assistant response should be in memory"
            
            # Verify the first message is the user's message
            assert context[0]["role"] == "user", \
                "First message should be from user"
            assert context[0]["content"] == message, \
                "First message content should match the input message"
            
            # Verify the second message is the assistant's response
            assert context[1]["role"] == "assistant", \
                "Second message should be from assistant"
            assert context[1]["content"] == response, \
                "Second message content should match the response"
