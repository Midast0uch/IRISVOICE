"""
Property-based tests for VPS Gateway health check recovery.
Tests universal properties that should hold for VPS health monitoring and recovery.
"""
import pytest
from hypothesis import given, settings, strategies as st, seed
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os
from datetime import datetime, timedelta
import asyncio

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.agent.vps_gateway import (
    VPSGateway,
    VPSConfig,
    VPSHealthStatus,
    VPSProtocol
)
from backend.agent.model_router import ModelRouter


# ============================================================================
# Test Data Generators (Hypothesis Strategies)
# ============================================================================

@st.composite
def vps_endpoints(draw):
    """Generate VPS endpoint URLs."""
    return draw(st.sampled_from([
        "https://vps1.example.com:8000",
        "https://vps2.example.com:8000",
        "https://vps3.example.com:8000",
        "http://localhost:9000",
        "https://inference.example.org",
    ]))


@st.composite
def endpoint_lists(draw):
    """Generate lists of VPS endpoints."""
    num_endpoints = draw(st.integers(min_value=1, max_value=5))
    endpoints = []
    for i in range(num_endpoints):
        endpoints.append(f"https://vps{i+1}.example.com:8000")
    return endpoints


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
        st.text(min_size=1, max_size=100),
        st.sampled_from([
            "What is the weather today?",
            "Help me write a function",
            "Explain this concept",
        ])
    ))


# ============================================================================
# Property 66: VPS Health Check Recovery
# Feature: irisvoice-backend-integration, Property 66: VPS Health Check Recovery
# Validates: Requirements 26.7, 26.8
# ============================================================================

class TestVPSHealthCheckRecovery:
    """
    Property 66: VPS Health Check Recovery
    
    For any VPS endpoint that transitions from unavailable to available, 
    the VPS_Gateway shall automatically resume routing requests to that endpoint.
    
    This property verifies:
    1. When an endpoint fails health checks, it is marked as unavailable
    2. Unavailable endpoints are excluded from endpoint selection
    3. When a failed endpoint recovers (health check passes), it is marked as available
    4. Recovered endpoints are included in endpoint selection
    5. The recovery process is automatic (no manual intervention needed)
    6. Multiple endpoints can fail and recover independently
    """
    
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        endpoint=vps_endpoints()
    )
    @pytest.mark.asyncio
    async def test_failed_endpoint_marked_unavailable(self, endpoint):
        """
        Property: When an endpoint fails health checks, it is marked as unavailable.
        
        # Feature: irisvoice-backend-integration, Property 66: VPS Health Check Recovery
        **Validates: Requirements 26.7**
        """
        # Setup: Create VPS config with endpoint
        config = VPSConfig(
            enabled=True,
            endpoints=[endpoint],
            auth_token="test-token",
            timeout=30
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        gateway = VPSGateway(config, mock_router)
        
        # Initialize HTTP client
        mock_http_client = AsyncMock()
        gateway._http_client = mock_http_client
        
        # Initialize health status
        gateway._health_status[endpoint] = VPSHealthStatus(
            endpoint=endpoint,
            available=True,  # Start as available
            last_check=datetime.now(),
            last_success=datetime.now(),
            consecutive_failures=0
        )
        
        # Mock health check to fail
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("Connection refused")
        mock_http_client.get.side_effect = Exception("Connection refused")
        
        # Execute: Perform health check
        result = await gateway.check_vps_health(endpoint)
        
        # Verify: Health check failed
        assert result is False, \
            "Health check should return False when endpoint fails"
        
        # Verify: Endpoint is marked as unavailable
        assert gateway._health_status[endpoint].available is False, \
            "Failed endpoint should be marked as unavailable"
        
        # Verify: Consecutive failures incremented
        assert gateway._health_status[endpoint].consecutive_failures > 0, \
            "Consecutive failures should be incremented"
        
        # Verify: Error message is recorded
        assert gateway._health_status[endpoint].error_message is not None, \
            "Error message should be recorded"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        endpoint=vps_endpoints(),
        model=model_names(),
        prompt=prompts()
    )
    @pytest.mark.asyncio
    async def test_unavailable_endpoints_excluded_from_selection(self, endpoint, model, prompt):
        """
        Property: Unavailable endpoints are excluded from endpoint selection.
        
        # Feature: irisvoice-backend-integration, Property 66: VPS Health Check Recovery
        **Validates: Requirements 26.7**
        """
        # Setup: Create VPS config with endpoint
        config = VPSConfig(
            enabled=True,
            endpoints=[endpoint],
            auth_token="test-token",
            fallback_to_local=True
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        mock_router.get_reasoning_model.return_value = MagicMock(
            generate=MagicMock(return_value="Local response")
        )
        gateway = VPSGateway(config, mock_router)
        
        # Initialize HTTP client
        gateway._http_client = AsyncMock()
        
        # Mark endpoint as unavailable
        gateway._health_status[endpoint] = VPSHealthStatus(
            endpoint=endpoint,
            available=False,  # Unavailable
            last_check=datetime.now(),
            consecutive_failures=3,
            error_message="Connection timeout"
        )
        
        # Execute: Try to select endpoint
        selected = await gateway._select_endpoint()
        
        # Verify: No endpoint selected (unavailable endpoint excluded)
        assert selected is None, \
            "Unavailable endpoint should not be selected"
        
        # Verify: is_vps_available returns False
        assert gateway.is_vps_available() is False, \
            "is_vps_available() should return False when all endpoints unavailable"
        
        # Execute: Try to infer (should fall back to local)
        gateway.infer_local = AsyncMock(return_value="Local fallback response")
        result = await gateway.infer(model, prompt, {}, {})
        
        # Verify: Local inference was used (fallback occurred)
        assert gateway.infer_local.called, \
            "Should fall back to local inference when no endpoints available"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        endpoint=vps_endpoints()
    )
    @pytest.mark.asyncio
    async def test_recovered_endpoint_marked_available(self, endpoint):
        """
        Property: When a failed endpoint recovers (health check passes), 
        it is marked as available.
        
        # Feature: irisvoice-backend-integration, Property 66: VPS Health Check Recovery
        **Validates: Requirements 26.8**
        """
        # Setup: Create VPS config with endpoint
        config = VPSConfig(
            enabled=True,
            endpoints=[endpoint],
            auth_token="test-token"
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        gateway = VPSGateway(config, mock_router)
        
        # Initialize HTTP client
        mock_http_client = AsyncMock()
        gateway._http_client = mock_http_client
        
        # Start with endpoint marked as unavailable (failed state)
        gateway._health_status[endpoint] = VPSHealthStatus(
            endpoint=endpoint,
            available=False,  # Failed
            last_check=datetime.now() - timedelta(seconds=60),
            last_success=datetime.now() - timedelta(seconds=120),
            consecutive_failures=5,
            error_message="Previous connection failure"
        )
        
        # Mock health check to succeed
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_http_client.get.return_value = mock_response
        
        # Execute: Perform health check
        result = await gateway.check_vps_health(endpoint)
        
        # Verify: Health check succeeded
        assert result is True, \
            "Health check should return True when endpoint recovers"
        
        # Verify: Endpoint is marked as available
        assert gateway._health_status[endpoint].available is True, \
            "Recovered endpoint should be marked as available"
        
        # Verify: Consecutive failures reset to 0
        assert gateway._health_status[endpoint].consecutive_failures == 0, \
            "Consecutive failures should be reset to 0 on recovery"
        
        # Verify: Error message cleared
        assert gateway._health_status[endpoint].error_message is None, \
            "Error message should be cleared on recovery"
        
        # Verify: Last success timestamp updated
        assert gateway._health_status[endpoint].last_success is not None, \
            "Last success timestamp should be updated"
        
        # Verify: Latency recorded
        assert gateway._health_status[endpoint].latency_ms is not None, \
            "Latency should be recorded on successful health check"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        endpoint=vps_endpoints(),
        model=model_names(),
        prompt=prompts()
    )
    @pytest.mark.asyncio
    async def test_recovered_endpoints_included_in_selection(self, endpoint, model, prompt):
        """
        Property: Recovered endpoints are included in endpoint selection.
        
        # Feature: irisvoice-backend-integration, Property 66: VPS Health Check Recovery
        **Validates: Requirements 26.8**
        """
        # Setup: Create VPS config with endpoint
        config = VPSConfig(
            enabled=True,
            endpoints=[endpoint],
            auth_token="test-token"
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        gateway = VPSGateway(config, mock_router)
        
        # Initialize HTTP client
        gateway._http_client = AsyncMock()
        
        # Start with endpoint unavailable
        gateway._health_status[endpoint] = VPSHealthStatus(
            endpoint=endpoint,
            available=False,
            consecutive_failures=3
        )
        
        # Verify: Endpoint not selected when unavailable
        selected_before = await gateway._select_endpoint()
        assert selected_before is None, \
            "Unavailable endpoint should not be selected"
        
        # Simulate recovery: Mark endpoint as available
        gateway._health_status[endpoint].available = True
        gateway._health_status[endpoint].consecutive_failures = 0
        gateway._health_status[endpoint].last_success = datetime.now()
        
        # Execute: Try to select endpoint after recovery
        selected_after = await gateway._select_endpoint()
        
        # Verify: Endpoint is now selected
        assert selected_after == endpoint, \
            "Recovered endpoint should be selected"
        
        # Verify: is_vps_available returns True
        assert gateway.is_vps_available() is True, \
            "is_vps_available() should return True after recovery"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        endpoint=vps_endpoints(),
        model=model_names(),
        prompt=prompts()
    )
    @pytest.mark.asyncio
    async def test_automatic_recovery_no_manual_intervention(self, endpoint, model, prompt):
        """
        Property: The recovery process is automatic (no manual intervention needed).
        
        # Feature: irisvoice-backend-integration, Property 66: VPS Health Check Recovery
        **Validates: Requirements 26.8**
        """
        # Setup: Create VPS config with endpoint
        config = VPSConfig(
            enabled=True,
            endpoints=[endpoint],
            auth_token="test-token"
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        gateway = VPSGateway(config, mock_router)
        
        # Initialize HTTP client
        mock_http_client = AsyncMock()
        gateway._http_client = mock_http_client
        
        # Start with endpoint unavailable
        gateway._health_status[endpoint] = VPSHealthStatus(
            endpoint=endpoint,
            available=False,
            consecutive_failures=2
        )
        
        # Mock health check to succeed (simulating automatic recovery)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_http_client.get.return_value = mock_response
        
        # Execute: Perform health check (automatic, no manual intervention)
        result = await gateway.check_vps_health(endpoint)
        
        # Verify: Health check succeeded automatically
        assert result is True, \
            "Health check should succeed automatically"
        
        # Verify: Endpoint automatically marked as available
        assert gateway._health_status[endpoint].available is True, \
            "Endpoint should be automatically marked as available"
        
        # Verify: No manual reset required - consecutive failures reset automatically
        assert gateway._health_status[endpoint].consecutive_failures == 0, \
            "Consecutive failures should reset automatically"
        
        # Execute: Verify endpoint is now used for inference (automatic routing)
        mock_http_client.post = AsyncMock()
        mock_infer_response = MagicMock()
        mock_infer_response.status_code = 200
        mock_infer_response.json.return_value = {
            "text": "VPS response",
            "model": model,
            "latency_ms": 100.0,
            "metadata": {}
        }
        mock_infer_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_infer_response
        
        result = await gateway.infer(model, prompt, {}, {})
        
        # Verify: Request automatically routed to recovered endpoint
        assert mock_http_client.post.called, \
            "Requests should automatically route to recovered endpoint"
        assert result == "VPS response", \
            "Should receive response from recovered VPS endpoint"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        endpoints=endpoint_lists()
    )
    @pytest.mark.asyncio
    async def test_multiple_endpoints_fail_and_recover_independently(self, endpoints):
        """
        Property: Multiple endpoints can fail and recover independently.
        
        # Feature: irisvoice-backend-integration, Property 66: VPS Health Check Recovery
        **Validates: Requirements 26.7, 26.8**
        """
        # Setup: Create VPS config with multiple endpoints
        config = VPSConfig(
            enabled=True,
            endpoints=endpoints,
            auth_token="test-token",
            load_balancing=True
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        gateway = VPSGateway(config, mock_router)
        
        # Initialize HTTP client
        mock_http_client = AsyncMock()
        gateway._http_client = mock_http_client
        
        # Initialize all endpoints as available
        for endpoint in endpoints:
            gateway._health_status[endpoint] = VPSHealthStatus(
                endpoint=endpoint,
                available=True,
                consecutive_failures=0
            )
        
        # Verify: All endpoints initially available
        assert gateway.is_vps_available() is True
        available_count = sum(1 for s in gateway._health_status.values() if s.available)
        assert available_count == len(endpoints), \
            "All endpoints should initially be available"
        
        # Simulate: First endpoint fails
        first_endpoint = endpoints[0]
        gateway._health_status[first_endpoint].available = False
        gateway._health_status[first_endpoint].consecutive_failures = 1
        
        # Verify: Other endpoints still available (if there are multiple endpoints)
        if len(endpoints) > 1:
            assert gateway.is_vps_available() is True, \
                "VPS should still be available with other endpoints"
        else:
            assert gateway.is_vps_available() is False, \
                "VPS should be unavailable when only endpoint fails"
        
        # Verify: Failed endpoint excluded from selection
        selected = await gateway._select_endpoint()
        if len(endpoints) > 1:
            assert selected != first_endpoint, \
                "Failed endpoint should not be selected"
            assert selected in endpoints, \
                "Should select from remaining available endpoints"
        else:
            assert selected is None, \
                "No endpoint should be selected when only endpoint fails"
        
        # Simulate: Second endpoint fails (if exists)
        if len(endpoints) > 1:
            second_endpoint = endpoints[1]
            gateway._health_status[second_endpoint].available = False
            gateway._health_status[second_endpoint].consecutive_failures = 1
            
            # Verify: Both failed endpoints excluded
            if len(endpoints) > 2:
                selected = await gateway._select_endpoint()
                assert selected not in [first_endpoint, second_endpoint], \
                    "Both failed endpoints should be excluded"
        
        # Simulate: First endpoint recovers independently
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_http_client.get.return_value = mock_response
        
        result = await gateway.check_vps_health(first_endpoint)
        
        # Verify: First endpoint recovered
        assert result is True
        assert gateway._health_status[first_endpoint].available is True, \
            "First endpoint should recover independently"
        assert gateway._health_status[first_endpoint].consecutive_failures == 0
        
        # Verify: Second endpoint still failed (if exists)
        if len(endpoints) > 1:
            assert gateway._health_status[second_endpoint].available is False, \
                "Second endpoint should remain failed (independent recovery)"
        
        # Verify: Recovered endpoint now included in selection
        selected = await gateway._select_endpoint()
        assert selected is not None, \
            "Should be able to select recovered endpoint"
        
        # Simulate: Second endpoint also recovers (if exists)
        if len(endpoints) > 1:
            result = await gateway.check_vps_health(second_endpoint)
            assert result is True
            assert gateway._health_status[second_endpoint].available is True, \
                "Second endpoint should also recover independently"
        
        # Verify: All endpoints recovered and available
        available_count = sum(1 for s in gateway._health_status.values() if s.available)
        assert available_count == len(endpoints), \
            "All endpoints should be available after recovery"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        endpoint=vps_endpoints(),
        model=model_names(),
        prompt=prompts()
    )
    @pytest.mark.asyncio
    async def test_inference_fails_then_succeeds_after_recovery(self, endpoint, model, prompt):
        """
        Property: Inference requests fail when endpoint is unavailable, 
        then succeed after endpoint recovers.
        
        # Feature: irisvoice-backend-integration, Property 66: VPS Health Check Recovery
        **Validates: Requirements 26.7, 26.8**
        """
        # Setup: Create VPS config with endpoint
        config = VPSConfig(
            enabled=True,
            endpoints=[endpoint],
            auth_token="test-token",
            fallback_to_local=True
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        mock_model = MagicMock()
        mock_model.generate.return_value = "Local fallback response"
        mock_router.get_reasoning_model.return_value = mock_model
        mock_router.get_execution_model.return_value = mock_model  # Also mock execution model
        gateway = VPSGateway(config, mock_router)
        
        # Initialize HTTP client
        mock_http_client = AsyncMock()
        gateway._http_client = mock_http_client
        
        # Phase 1: Endpoint unavailable
        gateway._health_status[endpoint] = VPSHealthStatus(
            endpoint=endpoint,
            available=False,
            consecutive_failures=2
        )
        
        # Execute: Try inference when unavailable (should fall back to local)
        result1 = await gateway.infer(model, prompt, {}, {})
        
        # Verify: Fell back to local (VPS not called)
        assert not mock_http_client.post.called, \
            "VPS should not be called when unavailable"
        assert result1 == "Local fallback response", \
            "Should use local fallback when VPS unavailable"
        
        # Phase 2: Endpoint recovers
        gateway._health_status[endpoint].available = True
        gateway._health_status[endpoint].consecutive_failures = 0
        gateway._health_status[endpoint].last_success = datetime.now()
        
        # Mock VPS inference response
        mock_infer_response = MagicMock()
        mock_infer_response.status_code = 200
        mock_infer_response.json.return_value = {
            "text": "VPS response after recovery",
            "model": model,
            "latency_ms": 100.0,
            "metadata": {}
        }
        mock_infer_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_infer_response
        
        # Execute: Try inference after recovery (should use VPS)
        result2 = await gateway.infer(model, prompt, {}, {})
        
        # Verify: VPS was called after recovery
        assert mock_http_client.post.called, \
            "VPS should be called after recovery"
        assert result2 == "VPS response after recovery", \
            "Should receive response from recovered VPS"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        endpoint=vps_endpoints()
    )
    @pytest.mark.asyncio
    async def test_health_status_tracks_recovery_metrics(self, endpoint):
        """
        Property: Health status correctly tracks recovery metrics 
        (last_success, consecutive_failures, latency).
        
        # Feature: irisvoice-backend-integration, Property 66: VPS Health Check Recovery
        **Validates: Requirements 26.7, 26.8**
        """
        # Setup: Create VPS config with endpoint
        config = VPSConfig(
            enabled=True,
            endpoints=[endpoint],
            auth_token="test-token"
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        gateway = VPSGateway(config, mock_router)
        
        # Initialize HTTP client
        mock_http_client = AsyncMock()
        gateway._http_client = mock_http_client
        
        # Initialize endpoint as available
        initial_time = datetime.now() - timedelta(minutes=5)
        gateway._health_status[endpoint] = VPSHealthStatus(
            endpoint=endpoint,
            available=True,
            last_check=initial_time,
            last_success=initial_time,
            consecutive_failures=0,
            latency_ms=50.0
        )
        
        # Phase 1: Simulate failure
        mock_http_client.get.side_effect = Exception("Connection timeout")
        
        result = await gateway.check_vps_health(endpoint)
        
        # Verify: Failure metrics updated
        assert result is False
        assert gateway._health_status[endpoint].available is False
        assert gateway._health_status[endpoint].consecutive_failures == 1
        assert gateway._health_status[endpoint].error_message is not None
        assert gateway._health_status[endpoint].last_check > initial_time
        
        # Phase 2: Simulate another failure
        result = await gateway.check_vps_health(endpoint)
        
        # Verify: Consecutive failures incremented
        assert gateway._health_status[endpoint].consecutive_failures == 2
        
        # Phase 3: Simulate recovery
        mock_http_client.get.side_effect = None
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_http_client.get.return_value = mock_response
        
        recovery_time_before = datetime.now()
        result = await gateway.check_vps_health(endpoint)
        recovery_time_after = datetime.now()
        
        # Verify: Recovery metrics updated correctly
        assert result is True
        assert gateway._health_status[endpoint].available is True
        assert gateway._health_status[endpoint].consecutive_failures == 0, \
            "Consecutive failures should reset to 0"
        assert gateway._health_status[endpoint].error_message is None, \
            "Error message should be cleared"
        assert gateway._health_status[endpoint].last_success is not None
        assert recovery_time_before <= gateway._health_status[endpoint].last_success <= recovery_time_after, \
            "Last success should be updated to current time"
        assert gateway._health_status[endpoint].latency_ms is not None, \
            "Latency should be recorded"
        assert gateway._health_status[endpoint].latency_ms >= 0, \
            "Latency should be non-negative"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
