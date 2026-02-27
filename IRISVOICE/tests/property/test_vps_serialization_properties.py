"""
Property-based tests for VPS request/response serialization round-trip.
Tests universal properties that should hold for all serialization scenarios.
"""
import pytest
from hypothesis import given, settings, strategies as st, seed
import sys
import os
import json
from typing import Dict, Any, List, Optional

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.agent.vps_gateway import (
    VPSInferenceRequest,
    VPSInferenceResponse
)


# ============================================================================
# Test Data Generators (Hypothesis Strategies)
# ============================================================================

@st.composite
def model_names(draw):
    """Generate valid model names."""
    return draw(st.sampled_from([
        "lfm2-8b",
        "lfm2.5-1.2b-instruct"
    ]))


@st.composite
def prompts(draw):
    """Generate various prompt types including edge cases."""
    return draw(st.one_of(
        # Empty string
        st.just(""),
        # Short prompts
        st.text(min_size=1, max_size=100),
        # Medium prompts
        st.text(min_size=100, max_size=500),
        # Long prompts
        st.text(min_size=500, max_size=2000),
        # Special characters
        st.text(alphabet=st.characters(blacklist_categories=('Cs',)), min_size=1, max_size=200),
        # Unicode characters
        st.text(alphabet='αβγδεζηθικλμνξοπρστυφχψω', min_size=1, max_size=100),
        # Common queries
        st.sampled_from([
            "What is the weather today?",
            "Help me write a function to sort a list",
            "Explain quantum computing",
            "Special chars: !@#$%^&*()_+-=[]{}|;':\",./<>?",
            "Newlines\nand\ttabs",
        ])
    ))


@st.composite
def contexts(draw):
    """Generate context dictionaries with various structures."""
    return draw(st.one_of(
        # Empty context
        st.just({}),
        # Context with conversation history
        st.builds(
            dict,
            conversation_history=st.lists(
                st.builds(
                    dict,
                    role=st.sampled_from(["user", "assistant"]),
                    content=st.text(min_size=1, max_size=200)
                ),
                min_size=0,
                max_size=10
            )
        ),
        # Context with nested structures
        st.builds(
            dict,
            personality=st.sampled_from(["professional", "friendly", "technical"]),
            settings=st.builds(
                dict,
                temperature=st.floats(min_value=0.0, max_value=2.0),
                max_tokens=st.integers(min_value=1, max_value=4096)
            )
        ),
        # Context with None values
        st.builds(
            dict,
            optional_field=st.none(),
            task_type=st.sampled_from(["reasoning", "execution"])
        ),
        # Context with lists and nested dicts
        st.builds(
            dict,
            tools=st.lists(st.text(min_size=1, max_size=50), min_size=0, max_size=5),
            metadata=st.builds(
                dict,
                timestamp=st.integers(min_value=0, max_value=2000000000),
                user_id=st.text(min_size=1, max_size=50)
            )
        )
    ))


@st.composite
def parameters(draw):
    """Generate model parameters with various types."""
    return draw(st.one_of(
        # Empty parameters
        st.just({}),
        # Standard parameters
        st.builds(
            dict,
            temperature=st.floats(min_value=0.0, max_value=2.0),
            max_tokens=st.integers(min_value=1, max_value=4096),
            top_p=st.floats(min_value=0.0, max_value=1.0),
            do_sample=st.booleans()
        ),
        # Parameters with None values
        st.builds(
            dict,
            temperature=st.floats(min_value=0.0, max_value=2.0),
            max_tokens=st.none(),
            top_p=st.floats(min_value=0.0, max_value=1.0)
        ),
        # Parameters with additional fields
        st.builds(
            dict,
            temperature=st.floats(min_value=0.0, max_value=2.0),
            max_tokens=st.integers(min_value=1, max_value=4096),
            custom_param=st.text(min_size=1, max_size=50)
        )
    ))


@st.composite
def session_ids(draw):
    """Generate session IDs."""
    return draw(st.one_of(
        st.text(min_size=1, max_size=100),
        st.sampled_from([
            "session-123",
            "user-abc-session-456",
            "default",
            "test-session"
        ])
    ))


@st.composite
def tool_calls(draw):
    """Generate optional tool calls."""
    return draw(st.one_of(
        st.none(),
        st.lists(
            st.builds(
                dict,
                tool_name=st.text(min_size=1, max_size=50),
                parameters=st.dictionaries(
                    keys=st.text(min_size=1, max_size=20),
                    values=st.one_of(
                        st.text(min_size=0, max_size=100),
                        st.integers(),
                        st.floats(allow_nan=False, allow_infinity=False),
                        st.booleans()
                    )
                )
            ),
            min_size=0,
            max_size=5
        )
    ))


@st.composite
def response_texts(draw):
    """Generate response text with various content."""
    return draw(st.one_of(
        st.text(min_size=1, max_size=1000),
        st.sampled_from([
            "This is a generated response.",
            "Error: Unable to process request",
            "Response with special chars: !@#$%",
            "Multi-line\nresponse\nwith\nnewlines",
        ])
    ))


@st.composite
def latencies(draw):
    """Generate latency values."""
    return draw(st.floats(min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False))


@st.composite
def metadata_dicts(draw):
    """Generate metadata dictionaries."""
    return draw(st.one_of(
        st.just({}),
        st.builds(
            dict,
            tokens=st.integers(min_value=0, max_value=10000),
            finish_reason=st.sampled_from(["stop", "length", "error"])
        ),
        st.builds(
            dict,
            tokens=st.integers(min_value=0, max_value=10000),
            finish_reason=st.sampled_from(["stop", "length"]),
            model_version=st.text(min_size=1, max_size=50)
        )
    ))


# ============================================================================
# Property 67: VPS Request Serialization Round-Trip
# Feature: irisvoice-backend-integration, Property 67: VPS Request Serialization Round-Trip
# Validates: Requirements 26.10, 26.11
# ============================================================================

class TestVPSSerializationRoundTrip:
    """
    Property 67: VPS Request Serialization Round-Trip
    
    For any VPS inference request or response, serialization to JSON and 
    deserialization back should preserve all data without loss.
    """
    
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters(),
        session_id=session_ids(),
        tool_calls_data=tool_calls()
    )
    def test_request_serialization_round_trip(
        self, model, prompt, context, params, session_id, tool_calls_data
    ):
        """
        Property: For any VPSInferenceRequest, serialization to JSON and 
        deserialization back produces an equivalent request.
        
        # Feature: irisvoice-backend-integration, Property 67: VPS Request Serialization Round-Trip
        **Validates: Requirements 26.10, 26.11**
        """
        # Create original request
        original_request = VPSInferenceRequest(
            model=model,
            prompt=prompt,
            context=context,
            parameters=params,
            session_id=session_id,
            tool_calls=tool_calls_data
        )
        
        # Serialize to JSON
        json_str = json.dumps(original_request.model_dump())
        
        # Deserialize back
        json_dict = json.loads(json_str)
        deserialized_request = VPSInferenceRequest(**json_dict)
        
        # Verify: All fields are preserved
        assert deserialized_request.model == original_request.model, \
            "Model field should be preserved after round-trip"
        assert deserialized_request.prompt == original_request.prompt, \
            "Prompt field should be preserved after round-trip"
        assert deserialized_request.context == original_request.context, \
            "Context field should be preserved after round-trip"
        assert deserialized_request.parameters == original_request.parameters, \
            "Parameters field should be preserved after round-trip"
        assert deserialized_request.session_id == original_request.session_id, \
            "Session ID field should be preserved after round-trip"
        assert deserialized_request.tool_calls == original_request.tool_calls, \
            "Tool calls field should be preserved after round-trip"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        text=response_texts(),
        model=model_names(),
        latency=latencies(),
        tool_calls_data=tool_calls(),
        tool_results_data=tool_calls(),  # Reuse tool_calls strategy for tool_results
        metadata=metadata_dicts()
    )
    def test_response_serialization_round_trip(
        self, text, model, latency, tool_calls_data, tool_results_data, metadata
    ):
        """
        Property: For any VPSInferenceResponse, serialization to JSON and 
        deserialization back produces an equivalent response.
        
        # Feature: irisvoice-backend-integration, Property 67: VPS Request Serialization Round-Trip
        **Validates: Requirements 26.10, 26.11**
        """
        # Create original response
        original_response = VPSInferenceResponse(
            text=text,
            model=model,
            latency_ms=latency,
            tool_calls=tool_calls_data,
            tool_results=tool_results_data,
            metadata=metadata
        )
        
        # Serialize to JSON
        json_str = json.dumps(original_response.model_dump())
        
        # Deserialize back
        json_dict = json.loads(json_str)
        deserialized_response = VPSInferenceResponse(**json_dict)
        
        # Verify: All fields are preserved
        assert deserialized_response.text == original_response.text, \
            "Text field should be preserved after round-trip"
        assert deserialized_response.model == original_response.model, \
            "Model field should be preserved after round-trip"
        assert deserialized_response.latency_ms == original_response.latency_ms, \
            "Latency field should be preserved after round-trip"
        assert deserialized_response.tool_calls == original_response.tool_calls, \
            "Tool calls field should be preserved after round-trip"
        assert deserialized_response.tool_results == original_response.tool_results, \
            "Tool results field should be preserved after round-trip"
        assert deserialized_response.metadata == original_response.metadata, \
            "Metadata field should be preserved after round-trip"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters(),
        session_id=session_ids()
    )
    def test_request_serialization_idempotent(
        self, model, prompt, context, params, session_id
    ):
        """
        Property: For any VPSInferenceRequest, serializing twice produces 
        the same JSON output (idempotent).
        
        # Feature: irisvoice-backend-integration, Property 67: VPS Request Serialization Round-Trip
        **Validates: Requirements 26.10, 26.11**
        """
        # Create request
        request = VPSInferenceRequest(
            model=model,
            prompt=prompt,
            context=context,
            parameters=params,
            session_id=session_id
        )
        
        # Serialize twice
        json_str_1 = json.dumps(request.model_dump(), sort_keys=True)
        json_str_2 = json.dumps(request.model_dump(), sort_keys=True)
        
        # Verify: Both serializations are identical
        assert json_str_1 == json_str_2, \
            "Serialization should be idempotent (produce same output)"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters(),
        session_id=session_ids()
    )
    def test_request_double_round_trip(
        self, model, prompt, context, params, session_id
    ):
        """
        Property: For any VPSInferenceRequest, double round-trip 
        (serialize → deserialize → serialize → deserialize) preserves data.
        
        # Feature: irisvoice-backend-integration, Property 67: VPS Request Serialization Round-Trip
        **Validates: Requirements 26.10, 26.11**
        """
        # Create original request
        original_request = VPSInferenceRequest(
            model=model,
            prompt=prompt,
            context=context,
            parameters=params,
            session_id=session_id
        )
        
        # First round-trip
        json_str_1 = json.dumps(original_request.model_dump())
        intermediate_request = VPSInferenceRequest(**json.loads(json_str_1))
        
        # Second round-trip
        json_str_2 = json.dumps(intermediate_request.model_dump())
        final_request = VPSInferenceRequest(**json.loads(json_str_2))
        
        # Verify: Final request equals original
        assert final_request.model == original_request.model
        assert final_request.prompt == original_request.prompt
        assert final_request.context == original_request.context
        assert final_request.parameters == original_request.parameters
        assert final_request.session_id == original_request.session_id
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters(),
        session_id=session_ids()
    )
    def test_request_preserves_field_types(
        self, model, prompt, context, params, session_id
    ):
        """
        Property: For any VPSInferenceRequest, serialization preserves 
        field types (strings remain strings, dicts remain dicts, etc.).
        
        # Feature: irisvoice-backend-integration, Property 67: VPS Request Serialization Round-Trip
        **Validates: Requirements 26.10, 26.11**
        """
        # Create request
        original_request = VPSInferenceRequest(
            model=model,
            prompt=prompt,
            context=context,
            parameters=params,
            session_id=session_id
        )
        
        # Serialize and deserialize
        json_str = json.dumps(original_request.model_dump())
        deserialized_request = VPSInferenceRequest(**json.loads(json_str))
        
        # Verify: Field types are preserved
        assert isinstance(deserialized_request.model, str), \
            "Model should be a string"
        assert isinstance(deserialized_request.prompt, str), \
            "Prompt should be a string"
        assert isinstance(deserialized_request.context, dict), \
            "Context should be a dict"
        assert isinstance(deserialized_request.parameters, dict), \
            "Parameters should be a dict"
        assert isinstance(deserialized_request.session_id, str), \
            "Session ID should be a string"
        
        # Verify: Optional field type
        if deserialized_request.tool_calls is not None:
            assert isinstance(deserialized_request.tool_calls, list), \
                "Tool calls should be a list when present"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        text=response_texts(),
        model=model_names(),
        latency=latencies(),
        metadata=metadata_dicts()
    )
    def test_response_preserves_field_types(
        self, text, model, latency, metadata
    ):
        """
        Property: For any VPSInferenceResponse, serialization preserves 
        field types.
        
        # Feature: irisvoice-backend-integration, Property 67: VPS Request Serialization Round-Trip
        **Validates: Requirements 26.10, 26.11**
        """
        # Create response
        original_response = VPSInferenceResponse(
            text=text,
            model=model,
            latency_ms=latency,
            metadata=metadata
        )
        
        # Serialize and deserialize
        json_str = json.dumps(original_response.model_dump())
        deserialized_response = VPSInferenceResponse(**json.loads(json_str))
        
        # Verify: Field types are preserved
        assert isinstance(deserialized_response.text, str), \
            "Text should be a string"
        assert isinstance(deserialized_response.model, str), \
            "Model should be a string"
        assert isinstance(deserialized_response.latency_ms, (int, float)), \
            "Latency should be a number"
        assert isinstance(deserialized_response.metadata, dict), \
            "Metadata should be a dict"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=st.text(alphabet='αβγδεζηθικλμνξοπρστυφχψω', min_size=1, max_size=100),
        session_id=session_ids()
    )
    def test_request_handles_unicode_characters(
        self, model, prompt, session_id
    ):
        """
        Property: For any VPSInferenceRequest with Unicode characters, 
        serialization preserves the characters correctly.
        
        # Feature: irisvoice-backend-integration, Property 67: VPS Request Serialization Round-Trip
        **Validates: Requirements 26.10, 26.11**
        """
        # Create request with Unicode prompt
        original_request = VPSInferenceRequest(
            model=model,
            prompt=prompt,
            context={},
            parameters={},
            session_id=session_id
        )
        
        # Serialize and deserialize
        json_str = json.dumps(original_request.model_dump(), ensure_ascii=False)
        deserialized_request = VPSInferenceRequest(**json.loads(json_str))
        
        # Verify: Unicode characters are preserved
        assert deserialized_request.prompt == original_request.prompt, \
            "Unicode characters in prompt should be preserved"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        session_id=session_ids()
    )
    def test_request_handles_empty_dicts(
        self, model, prompt, session_id
    ):
        """
        Property: For any VPSInferenceRequest with empty context/parameters, 
        serialization preserves empty dicts correctly.
        
        # Feature: irisvoice-backend-integration, Property 67: VPS Request Serialization Round-Trip
        **Validates: Requirements 26.10, 26.11**
        """
        # Create request with empty dicts
        original_request = VPSInferenceRequest(
            model=model,
            prompt=prompt,
            context={},
            parameters={},
            session_id=session_id
        )
        
        # Serialize and deserialize
        json_str = json.dumps(original_request.model_dump())
        deserialized_request = VPSInferenceRequest(**json.loads(json_str))
        
        # Verify: Empty dicts are preserved
        assert deserialized_request.context == {}, \
            "Empty context dict should be preserved"
        assert deserialized_request.parameters == {}, \
            "Empty parameters dict should be preserved"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        session_id=session_ids()
    )
    def test_request_handles_none_values(
        self, model, prompt, session_id
    ):
        """
        Property: For any VPSInferenceRequest with None in optional fields, 
        serialization preserves None values correctly.
        
        # Feature: irisvoice-backend-integration, Property 67: VPS Request Serialization Round-Trip
        **Validates: Requirements 26.10, 26.11**
        """
        # Create request with None tool_calls
        original_request = VPSInferenceRequest(
            model=model,
            prompt=prompt,
            context={},
            parameters={},
            session_id=session_id,
            tool_calls=None
        )
        
        # Serialize and deserialize
        json_str = json.dumps(original_request.model_dump())
        deserialized_request = VPSInferenceRequest(**json.loads(json_str))
        
        # Verify: None value is preserved
        assert deserialized_request.tool_calls is None, \
            "None value in optional field should be preserved"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=st.builds(
            dict,
            nested=st.builds(
                dict,
                deep=st.builds(
                    dict,
                    value=st.text(min_size=1, max_size=50)
                )
            )
        ),
        session_id=session_ids()
    )
    def test_request_handles_nested_structures(
        self, model, prompt, context, session_id
    ):
        """
        Property: For any VPSInferenceRequest with deeply nested structures 
        in context, serialization preserves the nested structure.
        
        # Feature: irisvoice-backend-integration, Property 67: VPS Request Serialization Round-Trip
        **Validates: Requirements 26.10, 26.11**
        """
        # Create request with nested context
        original_request = VPSInferenceRequest(
            model=model,
            prompt=prompt,
            context=context,
            parameters={},
            session_id=session_id
        )
        
        # Serialize and deserialize
        json_str = json.dumps(original_request.model_dump())
        deserialized_request = VPSInferenceRequest(**json.loads(json_str))
        
        # Verify: Nested structure is preserved
        assert deserialized_request.context == original_request.context, \
            "Nested context structure should be preserved"
        
        # Verify: Can access nested values
        if "nested" in context and "deep" in context["nested"]:
            assert deserialized_request.context["nested"]["deep"] == context["nested"]["deep"], \
                "Deeply nested values should be accessible and correct"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
