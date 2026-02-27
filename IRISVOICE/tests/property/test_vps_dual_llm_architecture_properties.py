"""
Property-based tests for VPS Gateway dual-LLM architecture preservation.
Tests universal properties that should hold for VPS dual-LLM routing scenarios.
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
def reasoning_contexts(draw):
    """Generate contexts that should route to reasoning model (lfm2-8b)."""
    return draw(st.one_of(
        # Explicit reasoning task type
        st.builds(
            dict,
            task_type=st.just("reasoning")
        ),
        # Context with planning indicators
        st.builds(
            dict,
            task_type=st.just("reasoning"),
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
        # Empty context (defaults to reasoning)
        st.just({})
    ))


@st.composite
def execution_contexts(draw):
    """Generate contexts that should route to execution model (lfm2.5-1.2b-instruct)."""
    return draw(st.one_of(
        # Explicit execution task type
        st.builds(
            dict,
            task_type=st.just("execution")
        ),
        # Context with tool execution indicators
        st.builds(
            dict,
            task_type=st.just("execution"),
            tool_calls=st.lists(
                st.builds(
                    dict,
                    tool_name=st.sampled_from(["web_search", "file_read", "calculator"]),
                    parameters=st.dictionaries(st.text(), st.text())
                ),
                min_size=1,
                max_size=3
            )
        )
    ))


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
# Property 68: VPS Dual-LLM Architecture Preservation
# Feature: irisvoice-backend-integration, Property 68: VPS Dual-LLM Architecture Preservation
# Validates: Requirements 26.12
# ============================================================================

class TestVPSDualLLMArchitecturePreservation:
    """
    Property 68: VPS Dual-LLM Architecture Preservation
    
    For any model inference request routed to VPS, the VPS_Gateway shall maintain 
    the same dual-LLM architecture (reasoning with lfm2-8b, execution with 
    lfm2.5-1.2b-instruct) as local execution.
    """
    
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        prompt=prompts(),
        context=reasoning_contexts(),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_vps_routes_reasoning_to_lfm2_8b(self, prompt, context, params):
        """
        Property: For any inference request with reasoning task type,
        VPS Gateway routes to lfm2-8b model.
        
        # Feature: irisvoice-backend-integration, Property 68: VPS Dual-LLM Architecture Preservation
        **Validates: Requirements 26.12**
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
            "text": "Reasoning response from lfm2-8b",
            "model": "lfm2-8b",
            "latency_ms": 100.0,
            "tool_calls": None,
            "tool_results": None,
            "metadata": {}
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_response
        
        # Execute: Call infer with reasoning context
        result = await gateway.infer(
            model="lfm2-8b",  # Explicitly request reasoning model
            prompt=prompt,
            context=context,
            params=params,
            session_id="test-session"
        )
        
        # Verify: HTTP client was called (remote routing occurred)
        assert mock_http_client.post.called, \
            "VPS Gateway should call HTTP client for reasoning tasks"
        
        # Verify: Request specifies lfm2-8b model
        call_args = mock_http_client.post.call_args
        request_json = call_args[1]["json"]
        assert request_json["model"] == "lfm2-8b", \
            "Reasoning tasks should route to lfm2-8b model"
        
        # Verify: Context is preserved
        assert request_json["context"] == context, \
            "Context should be preserved in VPS request"
        
        # Verify: Result is returned
        assert result == "Reasoning response from lfm2-8b", \
            "Gateway should return response from lfm2-8b"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        prompt=prompts(),
        context=execution_contexts(),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_vps_routes_execution_to_lfm2_5_1_2b(self, prompt, context, params):
        """
        Property: For any inference request with execution task type,
        VPS Gateway routes to lfm2.5-1.2b-instruct model.
        
        # Feature: irisvoice-backend-integration, Property 68: VPS Dual-LLM Architecture Preservation
        **Validates: Requirements 26.12**
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
            "text": "Execution response from lfm2.5-1.2b-instruct",
            "model": "lfm2.5-1.2b-instruct",
            "latency_ms": 100.0,
            "tool_calls": None,
            "tool_results": None,
            "metadata": {}
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_response
        
        # Execute: Call infer with execution context
        result = await gateway.infer(
            model="lfm2.5-1.2b-instruct",  # Explicitly request execution model
            prompt=prompt,
            context=context,
            params=params,
            session_id="test-session"
        )
        
        # Verify: HTTP client was called (remote routing occurred)
        assert mock_http_client.post.called, \
            "VPS Gateway should call HTTP client for execution tasks"
        
        # Verify: Request specifies lfm2.5-1.2b-instruct model
        call_args = mock_http_client.post.call_args
        request_json = call_args[1]["json"]
        assert request_json["model"] == "lfm2.5-1.2b-instruct", \
            "Execution tasks should route to lfm2.5-1.2b-instruct model"
        
        # Verify: Context is preserved
        assert request_json["context"] == context, \
            "Context should be preserved in VPS request"
        
        # Verify: Result is returned
        assert result == "Execution response from lfm2.5-1.2b-instruct", \
            "Gateway should return response from lfm2.5-1.2b-instruct"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        prompt=prompts(),
        reasoning_context=reasoning_contexts(),
        execution_context=execution_contexts(),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_vps_model_routing_consistency(self, prompt, reasoning_context, execution_context, params):
        """
        Property: For any sequence of reasoning and execution requests,
        VPS Gateway consistently routes to the correct model.
        
        # Feature: irisvoice-backend-integration, Property 68: VPS Dual-LLM Architecture Preservation
        **Validates: Requirements 26.12**
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
        
        # Mock the HTTP response to return different responses based on model
        def mock_post_response(*args, **kwargs):
            request_json = kwargs.get("json", {})
            model = request_json.get("model", "")
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "text": f"Response from {model}",
                "model": model,
                "latency_ms": 100.0,
                "tool_calls": None,
                "tool_results": None,
                "metadata": {}
            }
            mock_response.raise_for_status = MagicMock()
            return mock_response
        
        mock_http_client.post = AsyncMock(side_effect=mock_post_response)
        
        # Execute: Make reasoning request
        reasoning_result = await gateway.infer(
            model="lfm2-8b",
            prompt=prompt,
            context=reasoning_context,
            params=params,
            session_id="test-session"
        )
        
        # Execute: Make execution request
        execution_result = await gateway.infer(
            model="lfm2.5-1.2b-instruct",
            prompt=prompt,
            context=execution_context,
            params=params,
            session_id="test-session"
        )
        
        # Verify: Both requests were made
        assert mock_http_client.post.call_count == 2, \
            "Both reasoning and execution requests should be made"
        
        # Verify: First request used lfm2-8b
        first_call = mock_http_client.post.call_args_list[0]
        first_request = first_call[1]["json"]
        assert first_request["model"] == "lfm2-8b", \
            "First request should use lfm2-8b for reasoning"
        
        # Verify: Second request used lfm2.5-1.2b-instruct
        second_call = mock_http_client.post.call_args_list[1]
        second_request = second_call[1]["json"]
        assert second_request["model"] == "lfm2.5-1.2b-instruct", \
            "Second request should use lfm2.5-1.2b-instruct for execution"
        
        # Verify: Results match expected models
        assert "lfm2-8b" in reasoning_result, \
            "Reasoning result should come from lfm2-8b"
        assert "lfm2.5-1.2b-instruct" in execution_result, \
            "Execution result should come from lfm2.5-1.2b-instruct"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        prompt=prompts(),
        context=reasoning_contexts(),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_vps_and_local_use_same_model_for_reasoning(self, prompt, context, params):
        """
        Property: For any reasoning request, VPS and local execution
        use the same model (lfm2-8b).
        
        # Feature: irisvoice-backend-integration, Property 68: VPS Dual-LLM Architecture Preservation
        **Validates: Requirements 26.12**
        """
        # Setup: Create VPS config
        vps_config = VPSConfig(
            enabled=True,
            endpoints=["https://vps.example.com:8000"],
            auth_token="test-token",
            fallback_to_local=True
        )
        
        local_config = VPSConfig(
            enabled=False,
            endpoints=[],
            fallback_to_local=True
        )
        
        # Create mock ModelRouter
        mock_router = MagicMock(spec=ModelRouter)
        mock_reasoning_model = MagicMock()
        mock_reasoning_model.model_id = "lfm2-8b"
        mock_reasoning_model.generate = MagicMock(return_value="Local reasoning response")
        mock_router.get_reasoning_model.return_value = mock_reasoning_model
        mock_router.models = {"lfm2-8b": mock_reasoning_model}
        
        # Create gateways
        vps_gateway = VPSGateway(vps_config, mock_router)
        local_gateway = VPSGateway(local_config, mock_router)
        
        # Mock VPS HTTP client
        mock_http_client = AsyncMock()
        vps_gateway._http_client = mock_http_client
        
        # Set VPS endpoint as available
        vps_gateway._health_status["https://vps.example.com:8000"] = VPSHealthStatus(
            endpoint="https://vps.example.com:8000",
            available=True
        )
        
        # Mock VPS response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "text": "VPS reasoning response",
            "model": "lfm2-8b",
            "latency_ms": 100.0,
            "metadata": {}
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_response
        
        # Execute: Make VPS request
        await vps_gateway.infer(
            model="lfm2-8b",
            prompt=prompt,
            context=context,
            params=params
        )
        
        # Execute: Make local request
        await local_gateway.infer(
            model="lfm2-8b",
            prompt=prompt,
            context=context,
            params=params
        )
        
        # Verify: VPS request used lfm2-8b
        vps_call = mock_http_client.post.call_args
        vps_request = vps_call[1]["json"]
        assert vps_request["model"] == "lfm2-8b", \
            "VPS should use lfm2-8b for reasoning"
        
        # Verify: Local request used lfm2-8b
        assert mock_router.get_reasoning_model.called, \
            "Local execution should use reasoning model"
        assert mock_reasoning_model.model_id == "lfm2-8b", \
            "Local reasoning model should be lfm2-8b"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        prompt=prompts(),
        context=execution_contexts(),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_vps_and_local_use_same_model_for_execution(self, prompt, context, params):
        """
        Property: For any execution request, VPS and local execution
        use the same model (lfm2.5-1.2b-instruct).
        
        # Feature: irisvoice-backend-integration, Property 68: VPS Dual-LLM Architecture Preservation
        **Validates: Requirements 26.12**
        """
        # Setup: Create VPS config
        vps_config = VPSConfig(
            enabled=True,
            endpoints=["https://vps.example.com:8000"],
            auth_token="test-token",
            fallback_to_local=True
        )
        
        local_config = VPSConfig(
            enabled=False,
            endpoints=[],
            fallback_to_local=True
        )
        
        # Create mock ModelRouter
        mock_router = MagicMock(spec=ModelRouter)
        mock_execution_model = MagicMock()
        mock_execution_model.model_id = "lfm2.5-1.2b-instruct"
        mock_execution_model.generate = MagicMock(return_value="Local execution response")
        mock_router.get_execution_model.return_value = mock_execution_model
        mock_router.models = {"lfm2.5-1.2b-instruct": mock_execution_model}
        
        # Create gateways
        vps_gateway = VPSGateway(vps_config, mock_router)
        local_gateway = VPSGateway(local_config, mock_router)
        
        # Mock VPS HTTP client
        mock_http_client = AsyncMock()
        vps_gateway._http_client = mock_http_client
        
        # Set VPS endpoint as available
        vps_gateway._health_status["https://vps.example.com:8000"] = VPSHealthStatus(
            endpoint="https://vps.example.com:8000",
            available=True
        )
        
        # Mock VPS response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "text": "VPS execution response",
            "model": "lfm2.5-1.2b-instruct",
            "latency_ms": 100.0,
            "metadata": {}
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_response
        
        # Execute: Make VPS request
        await vps_gateway.infer(
            model="lfm2.5-1.2b-instruct",
            prompt=prompt,
            context=context,
            params=params
        )
        
        # Execute: Make local request
        await local_gateway.infer(
            model="lfm2.5-1.2b-instruct",
            prompt=prompt,
            context=context,
            params=params
        )
        
        # Verify: VPS request used lfm2.5-1.2b-instruct
        vps_call = mock_http_client.post.call_args
        vps_request = vps_call[1]["json"]
        assert vps_request["model"] == "lfm2.5-1.2b-instruct", \
            "VPS should use lfm2.5-1.2b-instruct for execution"
        
        # Verify: Local request used lfm2.5-1.2b-instruct
        assert mock_router.get_execution_model.called, \
            "Local execution should use execution model"
        assert mock_execution_model.model_id == "lfm2.5-1.2b-instruct", \
            "Local execution model should be lfm2.5-1.2b-instruct"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        reasoning_prompts=st.lists(prompts(), min_size=3, max_size=10),
        execution_prompts=st.lists(prompts(), min_size=3, max_size=10),
        params=parameters()
    )
    @pytest.mark.asyncio
    async def test_vps_model_selection_consistency_across_multiple_requests(
        self, reasoning_prompts, execution_prompts, params
    ):
        """
        Property: For any sequence of reasoning and execution requests,
        VPS Gateway consistently selects the correct model for each task type.
        
        # Feature: irisvoice-backend-integration, Property 68: VPS Dual-LLM Architecture Preservation
        **Validates: Requirements 26.12**
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
        def mock_post_response(*args, **kwargs):
            request_json = kwargs.get("json", {})
            model = request_json.get("model", "")
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "text": f"Response from {model}",
                "model": model,
                "latency_ms": 100.0,
                "tool_calls": None,
                "tool_results": None,
                "metadata": {}
            }
            mock_response.raise_for_status = MagicMock()
            return mock_response
        
        mock_http_client.post = AsyncMock(side_effect=mock_post_response)
        
        # Execute: Make multiple reasoning requests
        for prompt in reasoning_prompts:
            await gateway.infer(
                model="lfm2-8b",
                prompt=prompt,
                context={"task_type": "reasoning"},
                params=params
            )
        
        # Execute: Make multiple execution requests
        for prompt in execution_prompts:
            await gateway.infer(
                model="lfm2.5-1.2b-instruct",
                prompt=prompt,
                context={"task_type": "execution"},
                params=params
            )
        
        # Verify: Total number of requests
        total_requests = len(reasoning_prompts) + len(execution_prompts)
        assert mock_http_client.post.call_count == total_requests, \
            f"Should have made {total_requests} requests"
        
        # Verify: First N requests used lfm2-8b
        for i in range(len(reasoning_prompts)):
            call = mock_http_client.post.call_args_list[i]
            request = call[1]["json"]
            assert request["model"] == "lfm2-8b", \
                f"Reasoning request {i} should use lfm2-8b"
            assert request["context"]["task_type"] == "reasoning", \
                f"Reasoning request {i} should have reasoning task type"
        
        # Verify: Remaining requests used lfm2.5-1.2b-instruct
        for i in range(len(reasoning_prompts), total_requests):
            call = mock_http_client.post.call_args_list[i]
            request = call[1]["json"]
            assert request["model"] == "lfm2.5-1.2b-instruct", \
                f"Execution request {i} should use lfm2.5-1.2b-instruct"
            assert request["context"]["task_type"] == "execution", \
                f"Execution request {i} should have execution task type"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
