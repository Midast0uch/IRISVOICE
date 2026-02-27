"""
Property-based tests for VPS Gateway authentication.
Tests universal properties that should hold for all VPS authentication scenarios.
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
def auth_tokens(draw):
    """Generate various authentication token formats."""
    return draw(st.one_of(
        # Simple tokens
        st.text(min_size=10, max_size=50, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))),
        # UUID-like tokens
        st.from_regex(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', fullmatch=True),
        # JWT-like tokens (simplified)
        st.from_regex(r'^[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}$', fullmatch=True),
        # Common test tokens
        st.sampled_from([
            "test-token-12345",
            "secret-auth-token",
            "bearer-token-abc123",
            "api-key-xyz789",
        ])
    ))


# ============================================================================
# Property 64: VPS Gateway Authentication
# Feature: irisvoice-backend-integration, Property 64: VPS Gateway Authentication
# Validates: Requirements 26.4
# ============================================================================

class TestVPSGatewayAuthentication:
    """
    Property 64: VPS Gateway Authentication
    
    For any remote inference request to VPS, the VPS_Gateway shall include 
    authentication credentials in the request headers.
    
    Requirements 26.4:
    - All VPS requests must include authentication headers with the configured auth token
    - Authentication must be transparent to the caller
    - Requests without proper authentication should be rejected by the VPS server
    """
    
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters(),
        auth_token=auth_tokens()
    )
    @pytest.mark.asyncio
    async def test_all_vps_requests_include_auth_header(self, model, prompt, context, params, auth_token):
        """
        Property: For any VPS request with configured auth token, 
        the Authorization header is included in the request.
        
        # Feature: irisvoice-backend-integration, Property 64: VPS Gateway Authentication
        **Validates: Requirements 26.4**
        """
        # Setup: Create VPS config with auth token
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
        
        # Verify: HTTP client was called
        assert mock_http_client.post.called, \
            "HTTP client should be called for VPS request"
        
        # Verify: Authorization header is present
        call_args = mock_http_client.post.call_args
        headers = call_args[1]["headers"]
        
        assert "Authorization" in headers, \
            "All VPS requests must include Authorization header"
        
        # Verify: Authorization header contains the auth token
        assert auth_token in headers["Authorization"], \
            f"Authorization header must contain the configured auth token: {auth_token}"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters(),
        auth_token=auth_tokens()
    )
    @pytest.mark.asyncio
    async def test_auth_token_properly_formatted_as_bearer(self, model, prompt, context, params, auth_token):
        """
        Property: For any VPS request, the auth token is properly formatted 
        as "Bearer {token}" in the Authorization header.
        
        # Feature: irisvoice-backend-integration, Property 64: VPS Gateway Authentication
        **Validates: Requirements 26.4**
        """
        # Setup
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
        
        # Verify: Authorization header format
        call_args = mock_http_client.post.call_args
        headers = call_args[1]["headers"]
        
        assert headers["Authorization"] == f"Bearer {auth_token}", \
            f"Authorization header must be formatted as 'Bearer {auth_token}'"
        
        # Verify: Header starts with "Bearer "
        assert headers["Authorization"].startswith("Bearer "), \
            "Authorization header must start with 'Bearer '"
        
        # Verify: Token follows "Bearer " prefix
        token_part = headers["Authorization"][7:]  # Skip "Bearer "
        assert token_part == auth_token, \
            f"Token part must match configured auth token: {auth_token}"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        auth_token=auth_tokens()
    )
    @pytest.mark.asyncio
    async def test_auth_included_for_all_request_types(self, model, prompt, auth_token):
        """
        Property: For any type of VPS request (inference, health checks), 
        authentication headers are included.
        
        # Feature: irisvoice-backend-integration, Property 64: VPS Gateway Authentication
        **Validates: Requirements 26.4**
        """
        # Setup
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
        
        # Mock response for inference
        mock_inference_response = MagicMock()
        mock_inference_response.status_code = 200
        mock_inference_response.json.return_value = {
            "text": "Response",
            "model": model,
            "latency_ms": 100.0,
            "metadata": {}
        }
        mock_inference_response.raise_for_status = MagicMock()
        
        # Mock response for health check
        mock_health_response = MagicMock()
        mock_health_response.status_code = 200
        mock_health_response.json.return_value = {"status": "healthy"}
        mock_health_response.raise_for_status = MagicMock()
        
        # Configure mock to return different responses based on URL
        def mock_request(url, *args, **kwargs):
            if "health" in url:
                return mock_health_response
            else:
                return mock_inference_response
        
        mock_http_client.post.side_effect = mock_request
        mock_http_client.get.side_effect = mock_request
        
        # Execute: Inference request
        await gateway.infer(model, prompt, {}, {})
        
        # Verify: Inference request includes auth
        inference_call = mock_http_client.post.call_args
        inference_headers = inference_call[1]["headers"]
        assert "Authorization" in inference_headers, \
            "Inference requests must include Authorization header"
        assert inference_headers["Authorization"] == f"Bearer {auth_token}", \
            "Inference request auth header must be properly formatted"
        
        # Execute: Health check request
        await gateway.check_vps_health("https://vps.example.com:8000")
        
        # Verify: Health check request includes auth
        health_call = mock_http_client.get.call_args
        health_headers = health_call[1]["headers"]
        assert "Authorization" in health_headers, \
            "Health check requests must include Authorization header"
        assert health_headers["Authorization"] == f"Bearer {auth_token}", \
            "Health check request auth header must be properly formatted"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters(),
        auth_token=auth_tokens()
    )
    @pytest.mark.asyncio
    async def test_authentication_transparent_to_caller(self, model, prompt, context, params, auth_token):
        """
        Property: For any VPS request, authentication is transparent to the caller
        (caller doesn't need to provide auth headers).
        
        # Feature: irisvoice-backend-integration, Property 64: VPS Gateway Authentication
        **Validates: Requirements 26.4**
        """
        # Setup
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
        
        # Execute: Call infer WITHOUT providing any auth headers
        # (caller should not need to know about authentication)
        result = await gateway.infer(
            model=model,
            prompt=prompt,
            context=context,
            params=params
        )
        
        # Verify: Request succeeded
        assert result == "Response", \
            "Request should succeed without caller providing auth"
        
        # Verify: Gateway automatically added auth headers
        call_args = mock_http_client.post.call_args
        headers = call_args[1]["headers"]
        assert "Authorization" in headers, \
            "Gateway should automatically add Authorization header"
        assert headers["Authorization"] == f"Bearer {auth_token}", \
            "Gateway should use configured auth token"
        
        # Verify: Caller's parameters were not modified
        request_json = call_args[1]["json"]
        assert request_json["model"] == model, \
            "Caller's model parameter should be preserved"
        assert request_json["prompt"] == prompt, \
            "Caller's prompt parameter should be preserved"
        assert request_json["context"] == context, \
            "Caller's context parameter should be preserved"
        assert request_json["parameters"] == params, \
            "Caller's params parameter should be preserved"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_local_fallback_does_not_include_auth(self, model, prompt, context, params):
        """
        Property: For any local fallback request, authentication headers 
        are NOT included (not needed for local execution).
        
        # Feature: irisvoice-backend-integration, Property 64: VPS Gateway Authentication
        **Validates: Requirements 26.4**
        """
        # Setup: Create VPS config with VPS disabled (local-only mode)
        config = VPSConfig(
            enabled=False,
            endpoints=[],
            auth_token="test-token-should-not-be-used",
            fallback_to_local=True
        )
        
        # Create mock ModelRouter
        mock_router = MagicMock(spec=ModelRouter)
        mock_model = MagicMock()
        mock_model.model_id = model
        mock_model.generate = MagicMock(return_value="Local response")
        mock_router.get_reasoning_model.return_value = mock_model
        mock_router.get_execution_model.return_value = mock_model
        mock_router.route_message.return_value = model
        mock_router.models = {model: mock_model}
        
        # Create VPS Gateway
        gateway = VPSGateway(config, mock_router)
        
        # Execute: Call infer (will use local fallback)
        result = await gateway.infer(
            model=model,
            prompt=prompt,
            context=context,
            params=params
        )
        
        # Verify: Result is from local execution
        assert result == "Local response", \
            "Request should use local execution"
        
        # Verify: No HTTP client was created
        assert gateway._http_client is None, \
            "HTTP client should not be created for local-only mode"
        
        # Verify: Local model's generate was called
        assert mock_model.generate.called, \
            "Local model should be used for inference"
        
        # Verify: No authentication headers were used
        # (local execution doesn't use HTTP requests, so no headers)
        call_args = mock_model.generate.call_args
        # Local model.generate doesn't receive headers
        assert "headers" not in call_args[1], \
            "Local execution should not use HTTP headers"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        models=st.lists(model_names(), min_size=5, max_size=20),
        prompts_list=st.lists(prompts(), min_size=5, max_size=20),
        auth_token=auth_tokens()
    )
    @pytest.mark.asyncio
    async def test_auth_consistency_across_multiple_requests(self, models, prompts_list, auth_token):
        """
        Property: For any sequence of VPS requests, authentication headers 
        are consistently included with the same auth token.
        
        # Feature: irisvoice-backend-integration, Property 64: VPS Gateway Authentication
        **Validates: Requirements 26.4**
        """
        # Setup
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
        
        # Verify: All requests included auth header
        assert mock_http_client.post.call_count == num_requests, \
            f"All {num_requests} requests should be made"
        
        # Verify: All requests used the same auth token
        for call in mock_http_client.post.call_args_list:
            headers = call[1]["headers"]
            assert "Authorization" in headers, \
                "All requests must include Authorization header"
            assert headers["Authorization"] == f"Bearer {auth_token}", \
                f"All requests must use the same auth token: {auth_token}"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters(),
        auth_token=auth_tokens()
    )
    @pytest.mark.asyncio
    async def test_content_type_header_included_with_auth(self, model, prompt, context, params, auth_token):
        """
        Property: For any VPS request, both Authorization and Content-Type 
        headers are included.
        
        # Feature: irisvoice-backend-integration, Property 64: VPS Gateway Authentication
        **Validates: Requirements 26.4**
        """
        # Setup
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
        
        # Verify: Both headers are present
        call_args = mock_http_client.post.call_args
        headers = call_args[1]["headers"]
        
        assert "Authorization" in headers, \
            "Request must include Authorization header"
        assert "Content-Type" in headers, \
            "Request must include Content-Type header"
        
        # Verify: Header values are correct
        assert headers["Authorization"] == f"Bearer {auth_token}", \
            "Authorization header must be properly formatted"
        assert headers["Content-Type"] == "application/json", \
            "Content-Type must be application/json"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
