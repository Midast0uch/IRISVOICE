"""
Property-based tests for dual-LLM model routing.
Tests universal properties that should hold for all message routing scenarios.
"""
import pytest
from hypothesis import given, settings, strategies as st, seed
import sys
import os

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.agent.model_router import ModelRouter


# ============================================================================
# Test Data Generators (Hypothesis Strategies)
# ============================================================================

@st.composite
def messages(draw):
    """Generate various message types."""
    return draw(st.one_of(
        # Simple queries
        st.text(min_size=1, max_size=500),
        # Reasoning queries
        st.sampled_from([
            "What is the best approach to solve this problem?",
            "Can you help me plan a strategy?",
            "I need to think through this carefully",
            "How should I approach this task?",
            "What are the implications of this decision?",
            "Let me analyze this situation",
            "Can you reason about this problem?",
            "Help me understand the logic here",
        ]),
        # Tool execution queries
        st.sampled_from([
            "Execute the file operation",
            "Run the search tool",
            "Call the API function",
            "Invoke the browser automation",
            "Use tool: file_manager",
            "Perform action: click button",
            "Apply the transformation",
            "Execute command: ls -la",
            "Run function get_data()",
            "Call tool browser_navigate",
        ])
    ))


@st.composite
def context_hints(draw):
    """Generate context dictionaries with routing hints."""
    return draw(st.one_of(
        # No hints
        st.just({}),
        st.just(None),
        # Reasoning hint
        st.builds(dict, requires_reasoning=st.just(True)),
        # Tool execution hint
        st.builds(dict, requires_tools=st.just(True)),
        # Both hints (tools takes precedence)
        st.builds(dict, requires_reasoning=st.just(True), requires_tools=st.just(True)),
        # Mixed hints
        st.builds(dict, requires_reasoning=st.booleans(), requires_tools=st.booleans())
    ))


# ============================================================================
# Property 54: Dual-LLM Model Routing
# Feature: irisvoice-backend-integration, Property 54: Dual-LLM Model Routing
# Validates: Requirements 23.1, 23.2, 23.3
# ============================================================================

class TestDualLLMModelRouting:
    """
    Property 54: Dual-LLM Model Routing
    
    For any message that requires reasoning or planning, the Model_Router shall 
    route it to lfm2-8b; for any message that requires tool execution, the 
    Model_Router shall route it to lfm2.5-1.2b-instruct.
    """
    
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        message=messages(),
        context=context_hints()
    )
    def test_model_routing_based_on_context(self, message, context):
        """
        Property: For any message with context hints, the router routes to the 
        appropriate model based on the hints.
        
        # Feature: irisvoice-backend-integration, Property 54: Dual-LLM Model Routing
        **Validates: Requirements 23.1, 23.2, 23.3**
        """
        # Setup
        config_path = os.path.join(os.path.dirname(__file__), '../../backend/agent/agent_config.yaml')
        router = ModelRouter(config_path=config_path)
        
        # Ensure we have both models available
        reasoning_model = router.get_reasoning_model()
        execution_model = router.get_execution_model()
        
        # Skip test if models are not configured
        if reasoning_model is None or execution_model is None:
            pytest.skip("Required models not configured")
        
        # Execute: Route the message
        model_id = router.route_message(message, context)
        
        # Verify: Model ID is valid
        assert model_id in router.models, f"Routed model '{model_id}' should exist in available models"
        
        routed_model = router.models[model_id]
        
        # Verify routing logic based on context
        if context and context.get("requires_tools", False):
            # Tool execution should route to execution model
            assert routed_model.has_capability("tool_execution"), \
                f"Message with requires_tools=True should route to execution model, got {model_id}"
        
        elif context and context.get("requires_reasoning", False):
            # Reasoning should route to reasoning model
            assert routed_model.has_capability("reasoning"), \
                f"Message with requires_reasoning=True should route to reasoning model, got {model_id}"
        
        else:
            # Without explicit hints, routing depends on message content
            # The router should route to a valid model with appropriate capabilities
            assert routed_model.has_capability("reasoning") or \
                   routed_model.has_capability("tool_execution"), \
                f"Routed model should have either reasoning or tool_execution capability"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        message=st.text(min_size=1, max_size=500)
    )
    def test_tool_execution_messages_route_to_execution_model(self, message):
        """
        Property: For any message with tool execution indicators, the router 
        routes to the execution model (lfm2.5-1.2b-instruct).
        
        # Feature: irisvoice-backend-integration, Property 54: Dual-LLM Model Routing
        **Validates: Requirements 23.2**
        """
        # Setup
        config_path = os.path.join(os.path.dirname(__file__), '../../backend/agent/agent_config.yaml')
        router = ModelRouter(config_path=config_path)
        
        execution_model = router.get_execution_model()
        if execution_model is None:
            pytest.skip("Execution model not configured")
        
        # Add tool execution indicators to the message
        tool_indicators = ["execute", "run", "call", "invoke", "use tool", "perform action"]
        
        for indicator in tool_indicators:
            # Create a message with tool execution indicator
            tool_message = f"{indicator} {message}"
            
            # Execute: Route the message
            model_id = router.route_message(tool_message)
            
            # Verify: Should route to execution model
            routed_model = router.models[model_id]
            assert routed_model.has_capability("tool_execution"), \
                f"Message '{tool_message[:50]}...' with indicator '{indicator}' should route to execution model"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        message=st.text(min_size=1, max_size=500)
    )
    def test_reasoning_messages_route_to_reasoning_model(self, message):
        """
        Property: For any message without tool execution indicators, the router 
        defaults to the reasoning model (lfm2-8b).
        
        # Feature: irisvoice-backend-integration, Property 54: Dual-LLM Model Routing
        **Validates: Requirements 23.1**
        """
        # Setup
        config_path = os.path.join(os.path.dirname(__file__), '../../backend/agent/agent_config.yaml')
        router = ModelRouter(config_path=config_path)
        
        reasoning_model = router.get_reasoning_model()
        if reasoning_model is None:
            pytest.skip("Reasoning model not configured")
        
        # Filter out messages that contain tool execution indicators
        tool_indicators = ["execute", "run", "call", "invoke", "use tool", "perform", 
                          "action:", "tool:", "function:", "<tool>", "apply"]
        
        # Skip if message contains tool indicators
        message_lower = message.lower()
        if any(indicator in message_lower for indicator in tool_indicators):
            return  # Skip this example as it would route to execution model
        
        # Execute: Route the message without context
        model_id = router.route_message(message)
        
        # Verify: Should route to reasoning model (default)
        routed_model = router.models[model_id]
        assert routed_model.has_capability("reasoning"), \
            f"Message without tool indicators should route to reasoning model, got {model_id}"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        message=messages()
    )
    def test_explicit_context_overrides_message_content(self, message):
        """
        Property: For any message, explicit context hints take precedence over 
        message content analysis.
        
        # Feature: irisvoice-backend-integration, Property 54: Dual-LLM Model Routing
        **Validates: Requirements 23.3**
        """
        # Setup
        config_path = os.path.join(os.path.dirname(__file__), '../../backend/agent/agent_config.yaml')
        router = ModelRouter(config_path=config_path)
        
        reasoning_model = router.get_reasoning_model()
        execution_model = router.get_execution_model()
        
        if reasoning_model is None or execution_model is None:
            pytest.skip("Required models not configured")
        
        # Test 1: Explicit requires_tools=True should route to execution model
        # even if message doesn't contain tool indicators
        context_tools = {"requires_tools": True}
        model_id_tools = router.route_message(message, context_tools)
        routed_model_tools = router.models[model_id_tools]
        assert routed_model_tools.has_capability("tool_execution"), \
            "Explicit requires_tools=True should route to execution model"
        
        # Test 2: Explicit requires_reasoning=True should route to reasoning model
        # even if message contains tool indicators
        context_reasoning = {"requires_reasoning": True, "requires_tools": False}
        model_id_reasoning = router.route_message(message, context_reasoning)
        routed_model_reasoning = router.models[model_id_reasoning]
        assert routed_model_reasoning.has_capability("reasoning"), \
            "Explicit requires_reasoning=True should route to reasoning model"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        message=messages()
    )
    def test_routing_always_returns_valid_model(self, message):
        """
        Property: For any message, the router always returns a valid model ID 
        that exists in the available models.
        
        # Feature: irisvoice-backend-integration, Property 54: Dual-LLM Model Routing
        **Validates: Requirements 23.1, 23.2, 23.3**
        """
        # Setup
        config_path = os.path.join(os.path.dirname(__file__), '../../backend/agent/agent_config.yaml')
        router = ModelRouter(config_path=config_path)
        
        if not router.is_ready():
            pytest.skip("No models configured")
        
        # Execute: Route the message
        model_id = router.route_message(message)
        
        # Verify: Model ID is valid and exists
        assert model_id is not None, "Router should return a model ID"
        assert model_id in router.models, f"Routed model '{model_id}' should exist in available models"
        
        # Verify: The model has at least one capability
        routed_model = router.models[model_id]
        assert len(routed_model.capabilities) > 0, "Routed model should have at least one capability"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        messages_list=st.lists(messages(), min_size=5, max_size=20)
    )
    def test_routing_consistency_for_similar_messages(self, messages_list):
        """
        Property: For any set of messages with the same routing characteristics, 
        the router routes them consistently to the same model type.
        
        # Feature: irisvoice-backend-integration, Property 54: Dual-LLM Model Routing
        **Validates: Requirements 23.1, 23.2, 23.3**
        """
        # Setup
        config_path = os.path.join(os.path.dirname(__file__), '../../backend/agent/agent_config.yaml')
        router = ModelRouter(config_path=config_path)
        
        if not router.is_ready():
            pytest.skip("No models configured")
        
        # Test consistency with explicit context
        context_tools = {"requires_tools": True}
        model_ids_tools = [router.route_message(msg, context_tools) for msg in messages_list]
        
        # All should route to execution model
        for model_id in model_ids_tools:
            routed_model = router.models[model_id]
            assert routed_model.has_capability("tool_execution"), \
                "All messages with requires_tools=True should route to execution model"
        
        # Test consistency with reasoning context
        context_reasoning = {"requires_reasoning": True}
        model_ids_reasoning = [router.route_message(msg, context_reasoning) for msg in messages_list]
        
        # All should route to reasoning model
        for model_id in model_ids_reasoning:
            routed_model = router.models[model_id]
            assert routed_model.has_capability("reasoning"), \
                "All messages with requires_reasoning=True should route to reasoning model"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        message=st.text(min_size=1, max_size=500)
    )
    def test_both_context_hints_prioritizes_tools(self, message):
        """
        Property: For any message with both requires_reasoning and requires_tools 
        set to True, the router prioritizes tool execution (routes to execution model).
        
        # Feature: irisvoice-backend-integration, Property 54: Dual-LLM Model Routing
        **Validates: Requirements 23.2, 23.3**
        """
        # Setup
        config_path = os.path.join(os.path.dirname(__file__), '../../backend/agent/agent_config.yaml')
        router = ModelRouter(config_path=config_path)
        
        execution_model = router.get_execution_model()
        if execution_model is None:
            pytest.skip("Execution model not configured")
        
        # Context with both hints
        context = {"requires_reasoning": True, "requires_tools": True}
        
        # Execute: Route the message
        model_id = router.route_message(message, context)
        
        # Verify: Should prioritize tool execution
        routed_model = router.models[model_id]
        assert routed_model.has_capability("tool_execution"), \
            "When both hints are present, router should prioritize tool execution"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
