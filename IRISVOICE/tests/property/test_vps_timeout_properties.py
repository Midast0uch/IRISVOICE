"""
Property-based tests for VPS Gateway timeout handling.
Tests universal properties that should hold for all VPS timeout scenarios.
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
                max_size=5
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
def timeout_values(draw):
    """Generate timeout values in seconds."""
    return draw(st.integers(min_value=1, max_value=60))


# ============================================================================
# Property 65: VPS Gateway Timeout
# Feature: irisvoice-backend-integration, Property 65: VPS Gateway Timeout
# Validates: Requirements 26.5
# ============================================================================

class TestVPSGatewayTimeout:
    """
    Property 65: VPS Gateway Timeout
    
    For any remote inference request that exceeds the configured timeout duration,
    the VPS_Gateway shall cancel the request and fall back to local execution.
    """
    
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters(),
        timeout=timeout_values()
    )
    @pytest.mark.asyncio
    async def test_timeout_detected_and_handled(self, model, prompt, context, params, timeout):
        """
        Property: For any VPS request that times out, the timeout is detected
        and handled appropriately.
        
        # Feature: irisvoice-backend-integration, Property 65: VPS Gateway Timeout
        **Validates: Requirements 26.5**
        """
        # Setup: Create VPS config with specific timeout
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps.example.com:8000"],
            auth_token="test-token",
            timeout=timeout,
            fallback_to_local=True
        )
        
        # Create mock ModelRouter for local fallback
        mock_router = MagicMock(spec=ModelRouter)
        mock_model = MagicMock()
        mock_model.model_id = model
        mock_model.generate.return_value = "Local fallback response"
        mock_router.get_reasoning_model.return_value = mock_model
        mock_router.get_execution_model.return_value = mock_model
        mock_router.models = {model: mock_model}
        
        # Create VPS Gateway
        gateway = VPSGateway(config, mock_router)
        
        # Mock the HTTP client to raise TimeoutException
        mock_http_client = AsyncMock()
        gateway._http_client = mock_http_client
        
        # Set endpoint as initially available
        gateway._health_status["https://vps.example.com:8000"] = VPSHealthStatus(
            endpoint="https://vps.example.com:8000",
            available=True,
            last_check=datetime.now(),
            last_success=datetime.now(),
            consecutive_failures=0,
            latency_ms=50.0
        )
        
        # Mock HTTP client to raise TimeoutException
        mock_http_client.post.side_effect = httpx.TimeoutException(
            f"Request timed out after {timeout}s"
        )
        
        # Execute: Call infer (should timeout and fallback to local)
        result = await gateway.infer(
            model=model,
            prompt=prompt,
            context=context,
            params=params,
            session_id="test-session"
        )
        
        # Verify: HTTP client was called (VPS was attempted)
        assert mock_http_client.post.called, \
            "VPS Gateway should attempt VPS request before timeout"
        
        # Verify: Health status was updated to reflect timeout
        health = gateway._health_status["https://vps.example.com:8000"]
        assert not health.available, \
            "Endpoint should be marked as unavailable after timeout"
        assert health.consecutive_failures > 0, \
            "Consecutive failures should be incremented after timeout"
        assert "Timeout" in health.error_message or "timeout" in health.error_message.lower(), \
            f"Error message should mention timeout, got: {health.error_message}"
        
        # Verify: Local fallback was used
        assert result == "Local fallback response", \
            "Gateway should fall back to local execution on timeout"
        assert mock_model.generate.called, \
            "Local model should be used for fallback"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters(),
        timeout=timeout_values()
    )
    @pytest.mark.asyncio
    async def test_timeout_fallback_to_local_when_enabled(self, model, prompt, context, params, timeout):
        """
        Property: For any VPS timeout when fallback_to_local is enabled,
        the gateway automatically falls back to local execution.
        
        # Feature: irisvoice-backend-integration, Property 65: VPS Gateway Timeout
        **Validates: Requirements 26.5**
        """
        # Setup: Create VPS config with fallback enabled
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps.example.com:8000"],
            auth_token="test-token",
            timeout=timeout,
            fallback_to_local=True  # Explicitly enable fallback
        )
        
        # Create mock ModelRouter
        mock_router = MagicMock(spec=ModelRouter)
        mock_model = MagicMock()
        mock_model.model_id = model
        mock_model.generate.return_value = "Local execution result"
        mock_router.get_reasoning_model.return_value = mock_model
        mock_router.get_execution_model.return_value = mock_model
        mock_router.models = {model: mock_model}
        
        # Create VPS Gateway
        gateway = VPSGateway(config, mock_router)
        
        # Mock HTTP client to timeout
        mock_http_client = AsyncMock()
        gateway._http_client = mock_http_client
        gateway._health_status["https://vps.example.com:8000"] = VPSHealthStatus(
            endpoint="https://vps.example.com:8000",
            available=True
        )
        
        mock_http_client.post.side_effect = httpx.TimeoutException("Timeout")
        
        # Execute: Call infer
        result = await gateway.infer(model, prompt, context, params)
        
        # Verify: No exception was raised (fallback succeeded)
        assert result is not None, \
            "Gateway should return a result even after timeout"
        
        # Verify: Local model was used
        assert mock_model.generate.called, \
            "Local model should be invoked for fallback"
        assert result == "Local execution result", \
            "Result should come from local execution"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_timeout_updates_health_status(self, model, prompt, context, params):
        """
        Property: For any VPS timeout, the health status is updated to reflect
        the timeout failure.
        
        # Feature: irisvoice-backend-integration, Property 65: VPS Gateway Timeout
        **Validates: Requirements 26.5**
        """
        # Setup
        endpoint = "https://vps.example.com:8000"
        config = VPSConfig(
            enabled=True,
            endpoints=[endpoint],
            auth_token="test-token",
            timeout=30,
            fallback_to_local=True
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        mock_model = MagicMock()
        mock_model.generate.return_value = "Fallback"
        mock_router.get_reasoning_model.return_value = mock_model
        mock_router.get_execution_model.return_value = mock_model
        mock_router.models = {model: mock_model}
        
        gateway = VPSGateway(config, mock_router)
        
        # Set initial health status
        initial_failures = 0
        gateway._health_status[endpoint] = VPSHealthStatus(
            endpoint=endpoint,
            available=True,
            consecutive_failures=initial_failures
        )
        
        # Mock timeout
        mock_http_client = AsyncMock()
        gateway._http_client = mock_http_client
        mock_http_client.post.side_effect = httpx.TimeoutException("Timeout")
        
        # Execute
        await gateway.infer(model, prompt, context, params)
        
        # Verify: Health status reflects timeout
        health = gateway._health_status[endpoint]
        assert not health.available, \
            "Endpoint should be marked unavailable after timeout"
        assert health.consecutive_failures == initial_failures + 1, \
            "Consecutive failures should increment by 1"
        assert health.error_message is not None, \
            "Error message should be set"
        assert "timeout" in health.error_message.lower() or str(config.timeout) in health.error_message, \
            f"Error message should reference timeout, got: {health.error_message}"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_timeout_logged_with_monitoring_context(self, model, prompt, context, params):
        """
        Property: For any VPS timeout, the event is logged with monitoring context
        including endpoint, model, timeout value, and session ID.
        
        # Feature: irisvoice-backend-integration, Property 65: VPS Gateway Timeout
        **Validates: Requirements 26.5**
        """
        # Setup
        endpoint = "https://vps.example.com:8000"
        timeout = 30
        session_id = "test-session-123"
        
        config = VPSConfig(
            enabled=True,
            endpoints=[endpoint],
            timeout=timeout,
            fallback_to_local=True
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        mock_model = MagicMock()
        mock_model.generate.return_value = "Fallback"
        mock_router.get_reasoning_model.return_value = mock_model
        mock_router.get_execution_model.return_value = mock_model
        mock_router.models = {model: mock_model}
        
        gateway = VPSGateway(config, mock_router)
        gateway._health_status[endpoint] = VPSHealthStatus(endpoint=endpoint, available=True)
        
        # Mock HTTP client
        mock_http_client = AsyncMock()
        gateway._http_client = mock_http_client
        mock_http_client.post.side_effect = httpx.TimeoutException("Timeout")
        
        # Patch logger to capture log calls
        with patch('backend.agent.vps_gateway.logger') as mock_logger:
            # Execute
            await gateway.infer(model, prompt, context, params, session_id)
            
            # Verify: Logger was called with error level
            assert mock_logger.error.called, \
                "Timeout should be logged as error"
            
            # Verify: Log contains monitoring context
            # Convert all log calls to string for easier checking
            all_log_calls = str(mock_logger.error.call_args_list)
            
            # Check that key monitoring context is present in logs
            assert endpoint in all_log_calls or 'endpoint' in all_log_calls, \
                "Log should include endpoint information"
            assert model in all_log_calls or 'model' in all_log_calls, \
                "Log should include model information"
            assert str(timeout) in all_log_calls or 'timeout' in all_log_calls.lower(), \
                "Log should include timeout information"
            assert session_id in all_log_calls or 'session_id' in all_log_calls, \
                "Log should include session_id information"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_consecutive_timeouts_increment_failure_counter(self, model, prompt, context, params):
        """
        Property: For any sequence of consecutive VPS timeouts, the failure
        counter increments with each timeout.
        
        # Feature: irisvoice-backend-integration, Property 65: VPS Gateway Timeout
        **Validates: Requirements 26.5**
        """
        # Setup
        endpoint = "https://vps.example.com:8000"
        config = VPSConfig(
            enabled=True,
            endpoints=[endpoint],
            timeout=30,
            fallback_to_local=True
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        mock_model = MagicMock()
        mock_model.generate.return_value = "Fallback"
        mock_router.get_reasoning_model.return_value = mock_model
        mock_router.get_execution_model.return_value = mock_model
        mock_router.models = {model: mock_model}
        
        gateway = VPSGateway(config, mock_router)
        
        # Mock HTTP client to always timeout
        mock_http_client = AsyncMock()
        gateway._http_client = mock_http_client
        mock_http_client.post.side_effect = httpx.TimeoutException("Timeout")
        
        # Execute: Multiple consecutive requests that timeout
        # Reset endpoint to available before each request to simulate consecutive attempts
        num_requests = 3
        for i in range(num_requests):
            # Reset endpoint as available to force VPS attempt
            gateway._health_status[endpoint] = VPSHealthStatus(
                endpoint=endpoint,
                available=True,
                consecutive_failures=i  # Start with current failure count
            )
            
            await gateway.infer(model, prompt, context, params)
            
            # Verify: Failure counter increments
            health = gateway._health_status[endpoint]
            assert health.consecutive_failures == i + 1, \
                f"After {i+1} timeouts, consecutive_failures should be {i+1}, got {health.consecutive_failures}"
            assert not health.available, \
                f"Endpoint should be marked unavailable after timeout {i+1}"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        model=model_names(),
        prompt=prompts(),
        context=contexts(),
        params=parameters(),
        timeout=timeout_values()
    )
    @pytest.mark.asyncio
    async def test_configured_timeout_value_respected(self, model, prompt, context, params, timeout):
        """
        Property: For any VPS request, the configured timeout value is respected
        and passed to the HTTP client.
        
        # Feature: irisvoice-backend-integration, Property 65: VPS Gateway Timeout
        **Validates: Requirements 26.5**
        """
        # Setup: Create VPS config with specific timeout
        endpoint = "https://vps.example.com:8000"
        config = VPSConfig(
            enabled=True,
            endpoints=[endpoint],
            timeout=timeout,  # Use the generated timeout value
            fallback_to_local=True
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        mock_model = MagicMock()
        mock_model.generate.return_value = "Fallback"
        mock_router.get_reasoning_model.return_value = mock_model
        mock_router.get_execution_model.return_value = mock_model
        mock_router.models = {model: mock_model}
        
        gateway = VPSGateway(config, mock_router)
        
        # Initialize with HTTP client that has the configured timeout
        await gateway.initialize()
        
        # Verify: HTTP client was created with correct timeout
        assert gateway._http_client is not None, \
            "HTTP client should be initialized"
        assert gateway._http_client.timeout.read == timeout, \
            f"HTTP client timeout should be {timeout}s, got {gateway._http_client.timeout.read}s"
        
        # Cleanup
        await gateway.shutdown()
