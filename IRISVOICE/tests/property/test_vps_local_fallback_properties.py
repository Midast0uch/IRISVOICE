"""
Property-based tests for VPS Gateway local fallback.
Tests universal properties that should hold for all local fallback scenarios.
"""
import pytest
from hypothesis import given, settings, strategies as st, seed
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os
from datetime import datetime
import httpx

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


# ============================================================================
# Property 63: VPS Gateway Local Fallback
# Feature: irisvoice-backend-integration, Property 63: VPS Gateway Local Fallback
# Validates: Requirements 26.2
# ============================================================================

class TestVPSGatewayLocalFallback:
    """
    Property 63: VPS Gateway Local Fallback
    
    For any model inference request when VPS is unavailable or disabled,
    the VPS_Gateway shall automatically fall back to local model execution.
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
    async def test_fallback_when_vps_disabled(self, model, prompt, context, params):
        """
        Property: For any inference request when VPS is disabled (enabled=False),
        the gateway falls back to local execution.
        
        # Feature: irisvoice-backend-integration, Property 63: VPS Gateway Local Fallback
        **Validates: Requirements 26.2**
        """
        # Setup: Create VPS config with VPS disabled
        config = VPSConfig(
            enabled=False,  # VPS disabled
            endpoints=["https://vps.example.com:8000"],
            auth_token="test-token",
            fallback_to_local=True
        )
        
        # Create mock ModelRouter with local model
        mock_router = MagicMock(spec=ModelRouter)
        mock_model = MagicMock()
        mock_model.model_id = model
        mock_model.generate = MagicMock(return_value="Local model response")
        mock_router.get_reasoning_model.return_value = mock_model
        mock_router.get_execution_model.return_value = mock_model
        mock_router.route_message.return_value = model
        mock_router.models = {model: mock_model}
        
        # Create VPS Gateway
        gateway = VPSGateway(config, mock_router)
        
        # Mock infer_local to track calls
        gateway.infer_local = AsyncMock(return_value="Local response")
        
        # Execute: Call infer
        result = await gateway.infer(
            model=model,
            prompt=prompt,
            context=context,
            params=params,
            session_id="test-session"
        )
        
        # Verify: infer_local was called
        assert gateway.infer_local.called, \
            "Gateway should call infer_local when VPS is disabled"
        
        # Verify: Result is from local execution
        assert result == "Local response", \
            "Gateway should return result from local execution"
        
        # Verify: infer_local was called with correct parameters
        call_args = gateway.infer_local.call_args
        assert call_args[0][0] == model, \
            "infer_local should be called with correct model"
        assert call_args[0][1] == prompt, \
            "infer_local should be called with correct prompt"
        assert call_args[0][2] == context, \
            "infer_local should be called with correct context"
        assert call_args[0][3] == params, \
            "infer_local should be called with correct params"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_fallback_when_endpoints_empty(self, model, prompt, context, params):
        """
        Property: For any inference request when VPS endpoints list is empty,
        the gateway falls back to local execution.
        
        # Feature: irisvoice-backend-integration, Property 63: VPS Gateway Local Fallback
        **Validates: Requirements 26.2**
        """
        # Setup: Create VPS config with empty endpoints
        config = VPSConfig(
            enabled=True,  # VPS enabled but no endpoints
            endpoints=[],  # Empty endpoints list
            auth_token="test-token",
            fallback_to_local=True
        )
        
        # Create mock ModelRouter
        mock_router = MagicMock(spec=ModelRouter)
        mock_model = MagicMock()
        mock_model.model_id = model
        mock_model.generate = MagicMock(return_value="Local model response")
        mock_router.get_reasoning_model.return_value = mock_model
        mock_router.get_execution_model.return_value = mock_model
        mock_router.route_message.return_value = model
        mock_router.models = {model: mock_model}
        
        # Create VPS Gateway
        gateway = VPSGateway(config, mock_router)
        
        # Mock infer_local to track calls
        gateway.infer_local = AsyncMock(return_value="Local response")
        
        # Execute: Call infer
        result = await gateway.infer(
            model=model,
            prompt=prompt,
            context=context,
            params=params
        )
        
        # Verify: infer_local was called
        assert gateway.infer_local.called, \
            "Gateway should call infer_local when endpoints list is empty"
        
        # Verify: Result is from local execution
        assert result == "Local response", \
            "Gateway should return result from local execution"
        
        # Verify: is_vps_available returns False
        assert not gateway.is_vps_available(), \
            "is_vps_available should return False when no endpoints configured"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_fallback_when_health_check_fails(self, model, prompt, context, params):
        """
        Property: For any inference request when VPS health check fails,
        subsequent requests fall back to local execution.
        
        # Feature: irisvoice-backend-integration, Property 63: VPS Gateway Local Fallback
        **Validates: Requirements 26.2**
        """
        # Setup: Create VPS config with VPS enabled
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps.example.com:8000"],
            auth_token="test-token",
            fallback_to_local=True
        )
        
        # Create mock ModelRouter
        mock_router = MagicMock(spec=ModelRouter)
        mock_model = MagicMock()
        mock_model.model_id = model
        mock_model.generate = MagicMock(return_value="Local model response")
        mock_router.get_reasoning_model.return_value = mock_model
        mock_router.get_execution_model.return_value = mock_model
        mock_router.route_message.return_value = model
        mock_router.models = {model: mock_model}
        
        # Create VPS Gateway
        gateway = VPSGateway(config, mock_router)
        
        # Set endpoint as unavailable (health check failed)
        gateway._health_status["https://vps.example.com:8000"] = VPSHealthStatus(
            endpoint="https://vps.example.com:8000",
            available=False,  # Health check failed
            last_check=datetime.now(),
            consecutive_failures=3,
            error_message="Connection timeout"
        )
        
        # Mock infer_local to track calls
        gateway.infer_local = AsyncMock(return_value="Local response")
        
        # Execute: Call infer
        result = await gateway.infer(
            model=model,
            prompt=prompt,
            context=context,
            params=params
        )
        
        # Verify: infer_local was called
        assert gateway.infer_local.called, \
            "Gateway should call infer_local when health check fails"
        
        # Verify: Result is from local execution
        assert result == "Local response", \
            "Gateway should return result from local execution"
        
        # Verify: is_vps_available returns False
        assert not gateway.is_vps_available(), \
            "is_vps_available should return False when health check fails"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_fallback_produces_valid_response(self, model, prompt, context, params):
        """
        Property: For any inference request that falls back to local execution,
        the gateway produces a valid inference response.
        
        # Feature: irisvoice-backend-integration, Property 63: VPS Gateway Local Fallback
        **Validates: Requirements 26.2**
        """
        # Setup: Create VPS config with VPS disabled
        config = VPSConfig(
            enabled=False,
            endpoints=[],
            fallback_to_local=True
        )
        
        # Create mock ModelRouter with real local model behavior
        mock_router = MagicMock(spec=ModelRouter)
        mock_model = MagicMock()
        mock_model.model_id = model
        expected_response = "This is a valid local model response"
        mock_model.generate = MagicMock(return_value=expected_response)
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
        
        # Verify: Result is a valid string
        assert isinstance(result, str), \
            "Local fallback should return a string response"
        
        # Verify: Result is not empty
        assert len(result) > 0, \
            "Local fallback should return a non-empty response"
        
        # Verify: Result matches expected response
        assert result == expected_response, \
            "Local fallback should return the model's generated response"
        
        # Verify: Model's generate method was called
        assert mock_model.generate.called, \
            "Local fallback should call model's generate method"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_fallback_is_transparent(self, model, prompt, context, params):
        """
        Property: For any inference request, local fallback is transparent
        (same response structure as remote execution).
        
        # Feature: irisvoice-backend-integration, Property 63: VPS Gateway Local Fallback
        **Validates: Requirements 26.2**
        """
        # Setup: Create two gateways - one with VPS, one without
        vps_config = VPSConfig(
            enabled=True,
            endpoints=["https://vps.example.com:8000"],
            auth_token="token",
            fallback_to_local=True
        )
        
        local_config = VPSConfig(
            enabled=False,
            endpoints=[],
            fallback_to_local=True
        )
        
        # Create mock ModelRouter
        mock_router = MagicMock(spec=ModelRouter)
        mock_model = MagicMock()
        mock_model.model_id = model
        mock_model.generate = MagicMock(return_value="Model response")
        mock_router.get_reasoning_model.return_value = mock_model
        mock_router.get_execution_model.return_value = mock_model
        mock_router.route_message.return_value = model
        mock_router.models = {model: mock_model}
        
        # Create gateways
        vps_gateway = VPSGateway(vps_config, mock_router)
        local_gateway = VPSGateway(local_config, mock_router)
        
        # Mock VPS gateway to use local fallback
        vps_gateway._health_status["https://vps.example.com:8000"] = VPSHealthStatus(
            endpoint="https://vps.example.com:8000",
            available=False
        )
        
        # Execute: Call infer on both gateways
        vps_result = await vps_gateway.infer(model, prompt, context, params)
        local_result = await local_gateway.infer(model, prompt, context, params)
        
        # Verify: Both results have the same type
        assert type(vps_result) == type(local_result), \
            "VPS fallback and local execution should return same type"
        
        # Verify: Both results are strings
        assert isinstance(vps_result, str), \
            "VPS fallback should return string"
        assert isinstance(local_result, str), \
            "Local execution should return string"
        
        # Verify: Both results are non-empty
        assert len(vps_result) > 0, \
            "VPS fallback should return non-empty response"
        assert len(local_result) > 0, \
            "Local execution should return non-empty response"
        
        # Verify: Results are identical (same local model used)
        assert vps_result == local_result, \
            "VPS fallback and local execution should produce identical results"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_fallback_after_remote_failure(self, model, prompt, context, params):
        """
        Property: For any inference request when remote VPS fails,
        the gateway automatically falls back to local execution.
        
        # Feature: irisvoice-backend-integration, Property 63: VPS Gateway Local Fallback
        **Validates: Requirements 26.2**
        """
        # Setup: Create VPS config with VPS enabled
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps.example.com:8000"],
            auth_token="test-token",
            fallback_to_local=True
        )
        
        # Create mock ModelRouter
        mock_router = MagicMock(spec=ModelRouter)
        mock_model = MagicMock()
        mock_model.model_id = model
        mock_model.generate = MagicMock(return_value="Local fallback response")
        mock_router.get_reasoning_model.return_value = mock_model
        mock_router.get_execution_model.return_value = mock_model
        mock_router.route_message.return_value = model
        mock_router.models = {model: mock_model}
        
        # Create VPS Gateway
        gateway = VPSGateway(config, mock_router)
        
        # Mock HTTP client to simulate failure
        mock_http_client = AsyncMock()
        gateway._http_client = mock_http_client
        
        # Set endpoint as initially available
        gateway._health_status["https://vps.example.com:8000"] = VPSHealthStatus(
            endpoint="https://vps.example.com:8000",
            available=True,
            last_check=datetime.now(),
            last_success=datetime.now()
        )
        
        # Mock HTTP client to raise an exception (simulating VPS failure)
        mock_http_client.post.side_effect = httpx.TimeoutException("Connection timeout")
        
        # Execute: Call infer (should fail on VPS and fall back to local)
        result = await gateway.infer(
            model=model,
            prompt=prompt,
            context=context,
            params=params
        )
        
        # Verify: HTTP client was called (attempted remote)
        assert mock_http_client.post.called, \
            "Gateway should attempt remote inference first"
        
        # Verify: Result is from local execution
        assert result == "Local fallback response", \
            "Gateway should fall back to local execution after remote failure"
        
        # Verify: Endpoint is marked as unavailable
        assert not gateway._health_status["https://vps.example.com:8000"].available, \
            "Failed endpoint should be marked as unavailable"
        
        # Verify: Consecutive failures counter increased
        assert gateway._health_status["https://vps.example.com:8000"].consecutive_failures > 0, \
            "Consecutive failures counter should increase after failure"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        models=st.lists(model_names(), min_size=5, max_size=20),
        prompts_list=st.lists(prompts(), min_size=5, max_size=20)
    )
    @pytest.mark.asyncio
    async def test_fallback_consistency_across_requests(self, models, prompts_list):
        """
        Property: For any sequence of inference requests when VPS is unavailable,
        all requests consistently fall back to local execution.
        
        # Feature: irisvoice-backend-integration, Property 63: VPS Gateway Local Fallback
        **Validates: Requirements 26.2**
        """
        # Setup: Create VPS config with VPS disabled
        config = VPSConfig(
            enabled=False,
            endpoints=[],
            fallback_to_local=True
        )
        
        # Create mock ModelRouter
        mock_router = MagicMock(spec=ModelRouter)
        mock_model = MagicMock()
        mock_model.model_id = "test-model"
        mock_model.generate = MagicMock(return_value="Local response")
        mock_router.get_reasoning_model.return_value = mock_model
        mock_router.get_execution_model.return_value = mock_model
        mock_router.route_message.return_value = "test-model"
        mock_router.models = {"test-model": mock_model}
        
        # Create VPS Gateway
        gateway = VPSGateway(config, mock_router)
        
        # Track local inference calls
        local_call_count = 0
        original_generate = mock_model.generate
        
        def track_generate(*args, **kwargs):
            nonlocal local_call_count
            local_call_count += 1
            return original_generate(*args, **kwargs)
        
        mock_model.generate = MagicMock(side_effect=track_generate)
        
        # Execute: Make multiple requests
        num_requests = min(len(models), len(prompts_list))
        results = []
        for i in range(num_requests):
            result = await gateway.infer(
                model=models[i],
                prompt=prompts_list[i],
                context={},
                params={}
            )
            results.append(result)
        
        # Verify: All requests used local execution
        assert local_call_count == num_requests, \
            f"All {num_requests} requests should use local execution"
        
        # Verify: All results are valid strings
        for result in results:
            assert isinstance(result, str), \
                "All results should be strings"
            assert len(result) > 0, \
                "All results should be non-empty"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_local_only_mode_works_fully(self, model, prompt, context, params):
        """
        Property: For any inference request when VPS is disabled,
        the system works fully in local-only mode.
        
        # Feature: irisvoice-backend-integration, Property 63: VPS Gateway Local Fallback
        **Validates: Requirements 26.2**
        """
        # Setup: Create VPS config with VPS disabled (local-only mode)
        config = VPSConfig(
            enabled=False,
            endpoints=[],
            fallback_to_local=True
        )
        
        # Create mock ModelRouter
        mock_router = MagicMock(spec=ModelRouter)
        mock_model = MagicMock()
        mock_model.model_id = model
        mock_model.generate = MagicMock(return_value="Local-only response")
        mock_router.get_reasoning_model.return_value = mock_model
        mock_router.get_execution_model.return_value = mock_model
        mock_router.route_message.return_value = model
        mock_router.models = {model: mock_model}
        
        # Create VPS Gateway
        gateway = VPSGateway(config, mock_router)
        
        # Execute: Call infer multiple times
        results = []
        for _ in range(3):
            result = await gateway.infer(
                model=model,
                prompt=prompt,
                context=context,
                params=params
            )
            results.append(result)
        
        # Verify: All requests succeeded
        assert len(results) == 3, \
            "All requests should succeed in local-only mode"
        
        # Verify: All results are valid
        for result in results:
            assert isinstance(result, str), \
                "All results should be strings"
            assert len(result) > 0, \
                "All results should be non-empty"
            assert result == "Local-only response", \
                "All results should come from local model"
        
        # Verify: No HTTP client was created
        assert gateway._http_client is None, \
            "HTTP client should not be created when VPS is disabled"
        
        # Verify: No health status tracking
        assert len(gateway._health_status) == 0, \
            "No health status should be tracked when VPS is disabled"
        
        # Verify: is_vps_available returns False
        assert not gateway.is_vps_available(), \
            "is_vps_available should return False in local-only mode"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
