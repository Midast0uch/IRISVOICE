"""
Property-based tests for VPS Gateway remote routing.
Tests universal properties that should hold for all VPS routing scenarios.
"""
import pytest
from hypothesis import given, settings, strategies as st, seed
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os
from datetime import datetime

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.agent.vps_gateway import (
    VPSGateway,
    VPSConfig,
    VPSHealthStatus,
    VPSInferenceRequest,
    VPSInferenceResponse,
    VPSProtocol
)
from backend.agent.model_router import ModelRouter


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
    """Generate various prompt types."""
    return draw(st.one_of(
        # Short prompts
        st.text(min_size=1, max_size=100),
        # Medium prompts
        st.text(min_size=100, max_size=500),
        # Long prompts
        st.text(min_size=500, max_size=2000),
        # Common queries
        st.sampled_from([
            "What is the weather today?",
            "Help me write a function to sort a list",
            "Explain quantum computing",
            "How do I fix this error?",
            "What are the best practices for testing?",
        ])
    ))


@st.composite
def contexts(draw):
    """Generate context dictionaries."""
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
        # Context with personality
        st.builds(
            dict,
            personality=st.sampled_from(["professional", "friendly", "technical", "casual"])
        ),
        # Context with task type
        st.builds(
            dict,
            task_type=st.sampled_from(["reasoning", "execution", "general"])
        )
    ))


@st.composite
def parameters(draw):
    """Generate model parameters."""
    return draw(st.builds(
        dict,
        temperature=st.floats(min_value=0.0, max_value=2.0),
        max_tokens=st.integers(min_value=1, max_value=4096),
        top_p=st.floats(min_value=0.0, max_value=1.0),
        do_sample=st.booleans()
    ))


@st.composite
def vps_endpoints(draw):
    """Generate VPS endpoint URLs."""
    return draw(st.sampled_from([
        "https://vps1.example.com:8000",
        "https://vps2.example.com:8000",
        "http://localhost:9000",
        "https://inference.example.org",
    ]))


# ============================================================================
# Property 62: VPS Gateway Remote Routing
# Feature: irisvoice-backend-integration, Property 62: VPS Gateway Remote Routing
# Validates: Requirements 26.1
# ============================================================================

class TestVPSGatewayRemoteRouting:
    """
    Property 62: VPS Gateway Remote Routing
    
    For any model inference request when VPS is configured and available, 
    the VPS_Gateway shall route the request to the remote VPS endpoint.
    """
    
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_vps_routes_to_remote_when_available(self, model, prompt, context, params):
        """
        Property: For any model inference request when VPS is configured and 
        available, the gateway routes to the remote VPS endpoint.
        
        # Feature: irisvoice-backend-integration, Property 62: VPS Gateway Remote Routing
        **Validates: Requirements 26.1**
        """
        # Setup: Create VPS config with enabled VPS
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps.example.com:8000"],
            auth_token="test-token",
            timeout=30,
            fallback_to_local=True
        )
        
        # Create mock ModelRouter
        mock_router = MagicMock(spec=ModelRouter)
        
        # Create VPS Gateway
        gateway = VPSGateway(config, mock_router)
        
        # Mock the HTTP client and health status
        mock_http_client = AsyncMock()
        gateway._http_client = mock_http_client
        
        # Set endpoint as available
        gateway._health_status["https://vps.example.com:8000"] = VPSHealthStatus(
            endpoint="https://vps.example.com:8000",
            available=True,
            last_check=datetime.now(),
            last_success=datetime.now(),
            consecutive_failures=0,
            latency_ms=50.0
        )
        
        # Mock the HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "text": "Generated response text",
            "model": model,
            "latency_ms": 100.0,
            "tool_calls": None,
            "tool_results": None,
            "metadata": {}
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_response
        
        # Execute: Call infer
        result = await gateway.infer(
            model=model,
            prompt=prompt,
            context=context,
            params=params,
            session_id="test-session"
        )
        
        # Verify: HTTP client was called (remote routing occurred)
        assert mock_http_client.post.called, \
            "VPS Gateway should call HTTP client when VPS is available"
        
        # Verify: Request was sent to correct endpoint
        call_args = mock_http_client.post.call_args
        assert "https://vps.example.com:8000/api/v1/infer" in call_args[0][0], \
            "Request should be sent to VPS endpoint"
        
        # Verify: Authentication header was included
        headers = call_args[1]["headers"]
        assert "Authorization" in headers, \
            "Request should include Authorization header"
        assert headers["Authorization"] == "Bearer test-token", \
            "Authorization header should contain correct token"
        
        # Verify: Request payload is correct
        request_json = call_args[1]["json"]
        assert request_json["model"] == model, \
            "Request should include correct model"
        assert request_json["prompt"] == prompt, \
            "Request should include correct prompt"
        assert request_json["context"] == context, \
            "Request should include correct context"
        assert request_json["parameters"] == params, \
            "Request should include correct parameters"
        assert request_json["session_id"] == "test-session", \
            "Request should include session ID"
        
        # Verify: Result is returned
        assert result == "Generated response text", \
            "Gateway should return generated text from VPS"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_vps_includes_authentication_headers(self, model, prompt, context, params):
        """
        Property: For any VPS request, authentication headers are included 
        when auth_token is configured.
        
        # Feature: irisvoice-backend-integration, Property 62: VPS Gateway Remote Routing
        **Validates: Requirements 26.1**
        """
        # Setup: Create VPS config with auth token
        auth_token = "secret-auth-token-12345"
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps.example.com:8000"],
            auth_token=auth_token,
            timeout=30
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        gateway = VPSGateway(config, mock_router)
        
        # Mock HTTP client
        mock_http_client = AsyncMock()
        gateway._http_client = mock_http_client
        
        # Set endpoint as available
        gateway._health_status["https://vps.example.com:8000"] = VPSHealthStatus(
            endpoint="https://vps.example.com:8000",
            available=True
        )
        
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "text": "Response",
            "model": model,
            "latency_ms": 100.0,
            "metadata": {}
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_response
        
        # Execute
        await gateway.infer(model, prompt, context, params)
        
        # Verify: Authorization header is present and correct
        call_args = mock_http_client.post.call_args
        headers = call_args[1]["headers"]
        
        assert "Authorization" in headers, \
            "Request must include Authorization header"
        assert headers["Authorization"] == f"Bearer {auth_token}", \
            f"Authorization header should be 'Bearer {auth_token}'"
        assert "Content-Type" in headers, \
            "Request must include Content-Type header"
        assert headers["Content-Type"] == "application/json", \
            "Content-Type should be application/json"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_vps_request_serialization_is_correct(self, model, prompt, context, params):
        """
        Property: For any inference request, the VPS Gateway correctly serializes 
        the request payload with all required fields.
        
        # Feature: irisvoice-backend-integration, Property 62: VPS Gateway Remote Routing
        **Validates: Requirements 26.1**
        """
        # Setup
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps.example.com:8000"],
            auth_token="token"
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        gateway = VPSGateway(config, mock_router)
        
        # Mock HTTP client
        mock_http_client = AsyncMock()
        gateway._http_client = mock_http_client
        
        # Set endpoint as available
        gateway._health_status["https://vps.example.com:8000"] = VPSHealthStatus(
            endpoint="https://vps.example.com:8000",
            available=True
        )
        
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "text": "Response",
            "model": model,
            "latency_ms": 100.0,
            "metadata": {}
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_response
        
        # Execute
        session_id = "test-session-123"
        await gateway.infer(model, prompt, context, params, session_id)
        
        # Verify: Request payload structure
        call_args = mock_http_client.post.call_args
        request_json = call_args[1]["json"]
        
        # Check all required fields are present
        assert "model" in request_json, \
            "Request must include 'model' field"
        assert "prompt" in request_json, \
            "Request must include 'prompt' field"
        assert "context" in request_json, \
            "Request must include 'context' field"
        assert "parameters" in request_json, \
            "Request must include 'parameters' field"
        assert "session_id" in request_json, \
            "Request must include 'session_id' field"
        
        # Check field values are correct
        assert request_json["model"] == model, \
            "Model field should match input"
        assert request_json["prompt"] == prompt, \
            "Prompt field should match input"
        assert request_json["context"] == context, \
            "Context field should match input"
        assert request_json["parameters"] == params, \
            "Parameters field should match input"
        assert request_json["session_id"] == session_id, \
            "Session ID field should match input"
        
        # Verify: Request can be deserialized to VPSInferenceRequest
        try:
            inference_request = VPSInferenceRequest(**request_json)
            assert inference_request.model == model
            assert inference_request.prompt == prompt
            assert inference_request.context == context
            assert inference_request.parameters == params
            assert inference_request.session_id == session_id
        except Exception as e:
            pytest.fail(f"Request payload should be valid VPSInferenceRequest: {e}")
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts()
    )
    @pytest.mark.asyncio
    async def test_vps_calls_infer_remote_when_available(self, model, prompt):
        """
        Property: For any inference request when VPS is available, 
        infer_remote() is called instead of infer_local().
        
        # Feature: irisvoice-backend-integration, Property 62: VPS Gateway Remote Routing
        **Validates: Requirements 26.1**
        """
        # Setup
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps.example.com:8000"],
            auth_token="token"
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        gateway = VPSGateway(config, mock_router)
        
        # Set endpoint as available
        gateway._health_status["https://vps.example.com:8000"] = VPSHealthStatus(
            endpoint="https://vps.example.com:8000",
            available=True
        )
        
        # Mock infer_remote and infer_local
        gateway.infer_remote = AsyncMock(return_value="Remote response")
        gateway.infer_local = AsyncMock(return_value="Local response")
        
        # Execute
        result = await gateway.infer(
            model=model,
            prompt=prompt,
            context={},
            params={}
        )
        
        # Verify: infer_remote was called
        assert gateway.infer_remote.called, \
            "infer_remote() should be called when VPS is available"
        
        # Verify: infer_local was NOT called
        assert not gateway.infer_local.called, \
            "infer_local() should NOT be called when VPS is available"
        
        # Verify: Result is from remote
        assert result == "Remote response", \
            "Result should be from remote inference"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        models=st.lists(model_names(), min_size=5, max_size=20),
        prompts_list=st.lists(prompts(), min_size=5, max_size=20)
    )
    @pytest.mark.asyncio
    async def test_vps_routing_consistency_across_requests(self, models, prompts_list):
        """
        Property: For any sequence of inference requests when VPS is available, 
        all requests are consistently routed to the remote VPS endpoint.
        
        # Feature: irisvoice-backend-integration, Property 62: VPS Gateway Remote Routing
        **Validates: Requirements 26.1**
        """
        # Setup
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps.example.com:8000"],
            auth_token="token"
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        gateway = VPSGateway(config, mock_router)
        
        # Mock HTTP client
        mock_http_client = AsyncMock()
        gateway._http_client = mock_http_client
        
        # Set endpoint as available
        gateway._health_status["https://vps.example.com:8000"] = VPSHealthStatus(
            endpoint="https://vps.example.com:8000",
            available=True
        )
        
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "text": "Response",
            "model": "test-model",
            "latency_ms": 100.0,
            "metadata": {}
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_response
        
        # Execute: Make multiple requests
        num_requests = min(len(models), len(prompts_list))
        for i in range(num_requests):
            await gateway.infer(
                model=models[i],
                prompt=prompts_list[i],
                context={},
                params={}
            )
        
        # Verify: All requests went to remote VPS
        assert mock_http_client.post.call_count == num_requests, \
            f"All {num_requests} requests should be routed to VPS"
        
        # Verify: All requests went to the correct endpoint
        for call in mock_http_client.post.call_args_list:
            endpoint_url = call[0][0]
            assert "https://vps.example.com:8000/api/v1/infer" in endpoint_url, \
                "All requests should go to VPS endpoint"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_vps_response_deserialization(self, model, prompt, context, params):
        """
        Property: For any VPS response, the gateway correctly deserializes 
        the response and extracts the generated text.
        
        # Feature: irisvoice-backend-integration, Property 62: VPS Gateway Remote Routing
        **Validates: Requirements 26.1**
        """
        # Setup
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps.example.com:8000"],
            auth_token="token"
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        gateway = VPSGateway(config, mock_router)
        
        # Mock HTTP client
        mock_http_client = AsyncMock()
        gateway._http_client = mock_http_client
        
        # Set endpoint as available
        gateway._health_status["https://vps.example.com:8000"] = VPSHealthStatus(
            endpoint="https://vps.example.com:8000",
            available=True
        )
        
        # Create a valid VPS response
        expected_text = "This is the generated response text"
        vps_response = VPSInferenceResponse(
            text=expected_text,
            model=model,
            latency_ms=150.0,
            tool_calls=None,
            tool_results=None,
            metadata={"tokens": 50, "finish_reason": "stop"}
        )
        
        # Mock HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = vps_response.dict()
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_response
        
        # Execute
        result = await gateway.infer(model, prompt, context, params)
        
        # Verify: Result matches the text field from VPS response
        assert result == expected_text, \
            "Gateway should return the 'text' field from VPS response"
        
        # Verify: Response was properly deserialized
        # (if deserialization failed, an exception would have been raised)
        assert isinstance(result, str), \
            "Result should be a string"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
