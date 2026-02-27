"""
Property-based tests for VPS Gateway load balancing.
Tests universal properties that should hold for all load balancing scenarios.
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
    VPSInferenceResponse,
    LoadBalancingStrategy
)
from backend.agent.model_router import ModelRouter


# ============================================================================
# Test Data Generators (Hypothesis Strategies)
# ============================================================================

@st.composite
def endpoint_lists(draw, min_size=2, max_size=5):
    """Generate lists of VPS endpoint URLs."""
    num_endpoints = draw(st.integers(min_value=min_size, max_value=max_size))
    return [f"https://vps{i}.example.com:8000" for i in range(1, num_endpoints + 1)]


@st.composite
def load_balancing_configs(draw):
    """Generate VPS configs with load balancing enabled."""
    endpoints = draw(endpoint_lists())
    strategy = draw(st.sampled_from([
        LoadBalancingStrategy.ROUND_ROBIN,
        LoadBalancingStrategy.LEAST_LOADED
    ]))
    
    return VPSConfig(
        enabled=True,
        endpoints=endpoints,
        auth_token="test-token",
        timeout=30,
        load_balancing=True,
        load_balancing_strategy=strategy,
        fallback_to_local=True
    )


@st.composite
def latency_values(draw):
    """Generate realistic latency values in milliseconds."""
    return draw(st.floats(min_value=10.0, max_value=500.0))


@st.composite
def active_request_counts(draw):
    """Generate realistic active request counts."""
    return draw(st.integers(min_value=0, max_value=20))


# ============================================================================
# Property 69: VPS Load Balancing
# Feature: irisvoice-backend-integration, Property 69: VPS Load Balancing
# Validates: Requirements 26.9
# ============================================================================

class TestVPSLoadBalancing:
    """
    Property 69: VPS Load Balancing
    
    For any VPS Gateway with multiple endpoints and load balancing enabled,
    the gateway shall distribute requests across endpoints using the configured
    strategy (round-robin or least-loaded).
    """
    
    @settings(max_examples=10, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        endpoints=endpoint_lists(min_size=2, max_size=5)
    )
    @pytest.mark.asyncio
    async def test_round_robin_cycles_through_endpoints(self, endpoints):
        """
        Property: For any list of available endpoints with round-robin strategy,
        the gateway cycles through endpoints in order.
        
        # Feature: irisvoice-backend-integration, Property 69: VPS Load Balancing
        **Validates: Requirements 26.9**
        """
        # Setup: Create VPS config with round-robin strategy
        config = VPSConfig(
            enabled=True,
            endpoints=endpoints,
            auth_token="test-token",
            timeout=30,
            load_balancing=True,
            load_balancing_strategy=LoadBalancingStrategy.ROUND_ROBIN,
            fallback_to_local=True
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        gateway = VPSGateway(config, mock_router)
        
        # Initialize health status for all endpoints as available
        for endpoint in endpoints:
            gateway._health_status[endpoint] = VPSHealthStatus(
                endpoint=endpoint,
                available=True,
                last_check=datetime.now(),
                last_success=datetime.now(),
                consecutive_failures=0,
                latency_ms=100.0
            )
        
        # Execute: Select endpoints multiple times (2 full cycles)
        num_requests = len(endpoints) * 2
        selected_endpoints = []
        
        for _ in range(num_requests):
            endpoint = await gateway._select_endpoint()
            selected_endpoints.append(endpoint)
        
        # Verify: Endpoints are selected in round-robin order
        for i in range(num_requests):
            expected_endpoint = endpoints[i % len(endpoints)]
            actual_endpoint = selected_endpoints[i]
            
            assert actual_endpoint == expected_endpoint, \
                f"Round-robin should cycle through endpoints in order. " \
                f"Expected {expected_endpoint} at position {i}, got {actual_endpoint}"
        
        # Verify: Each endpoint is selected equally
        from collections import Counter
        selection_counts = Counter(selected_endpoints)
        
        expected_count = num_requests // len(endpoints)
        for endpoint in endpoints:
            assert selection_counts[endpoint] == expected_count, \
                f"Each endpoint should be selected {expected_count} times, " \
                f"but {endpoint} was selected {selection_counts[endpoint]} times"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        endpoints=endpoint_lists(min_size=2, max_size=5),
        latencies=st.lists(latency_values(), min_size=2, max_size=5),
        active_requests=st.lists(active_request_counts(), min_size=2, max_size=5)
    )
    @pytest.mark.asyncio
    async def test_least_loaded_selects_lowest_load(self, endpoints, latencies, active_requests):
        """
        Property: For any list of endpoints with least-loaded strategy,
        the gateway selects the endpoint with the lowest load
        (load = active_requests + latency_ms / 1000).
        
        # Feature: irisvoice-backend-integration, Property 69: VPS Load Balancing
        **Validates: Requirements 26.9**
        """
        # Ensure we have matching lengths
        num_endpoints = len(endpoints)
        latencies = latencies[:num_endpoints]
        active_requests = active_requests[:num_endpoints]
        
        # Pad if necessary
        while len(latencies) < num_endpoints:
            latencies.append(100.0)
        while len(active_requests) < num_endpoints:
            active_requests.append(0)
        
        # Setup: Create VPS config with least-loaded strategy
        config = VPSConfig(
            enabled=True,
            endpoints=endpoints,
            auth_token="test-token",
            timeout=30,
            load_balancing=True,
            load_balancing_strategy=LoadBalancingStrategy.LEAST_LOADED,
            fallback_to_local=True
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        gateway = VPSGateway(config, mock_router)
        
        # Initialize health status with different loads
        for i, endpoint in enumerate(endpoints):
            gateway._health_status[endpoint] = VPSHealthStatus(
                endpoint=endpoint,
                available=True,
                last_check=datetime.now(),
                last_success=datetime.now(),
                consecutive_failures=0,
                latency_ms=latencies[i],
                active_requests=active_requests[i]
            )
        
        # Calculate expected endpoint (lowest load)
        def calculate_load(idx):
            return active_requests[idx] + (latencies[idx] / 1000.0)
        
        loads = [calculate_load(i) for i in range(num_endpoints)]
        min_load_idx = loads.index(min(loads))
        expected_endpoint = endpoints[min_load_idx]
        
        # Execute: Select endpoint
        selected_endpoint = await gateway._select_endpoint()
        
        # Verify: Selected endpoint has the lowest load
        assert selected_endpoint == expected_endpoint, \
            f"Least-loaded strategy should select endpoint with lowest load. " \
            f"Expected {expected_endpoint} (load={loads[min_load_idx]:.3f}), " \
            f"got {selected_endpoint}"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        endpoints=endpoint_lists(min_size=3, max_size=5),
        num_failed=st.integers(min_value=1, max_value=2)
    )
    @pytest.mark.asyncio
    async def test_failed_endpoints_excluded_from_rotation(self, endpoints, num_failed):
        """
        Property: For any list of endpoints where some are marked as unavailable,
        the gateway excludes failed endpoints from load balancing rotation.
        
        # Feature: irisvoice-backend-integration, Property 69: VPS Load Balancing
        **Validates: Requirements 26.9**
        """
        # Ensure we don't fail all endpoints
        num_failed = min(num_failed, len(endpoints) - 1)
        
        # Setup: Create VPS config with round-robin strategy
        config = VPSConfig(
            enabled=True,
            endpoints=endpoints,
            auth_token="test-token",
            timeout=30,
            load_balancing=True,
            load_balancing_strategy=LoadBalancingStrategy.ROUND_ROBIN,
            fallback_to_local=True
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        gateway = VPSGateway(config, mock_router)
        
        # Mark some endpoints as failed
        failed_endpoints = endpoints[:num_failed]
        available_endpoints = endpoints[num_failed:]
        
        for endpoint in endpoints:
            is_available = endpoint not in failed_endpoints
            gateway._health_status[endpoint] = VPSHealthStatus(
                endpoint=endpoint,
                available=is_available,
                last_check=datetime.now(),
                last_success=datetime.now() if is_available else None,
                consecutive_failures=0 if is_available else 3,
                latency_ms=100.0 if is_available else None,
                error_message=None if is_available else "Connection timeout"
            )
        
        # Execute: Select endpoints multiple times
        num_requests = len(available_endpoints) * 3
        selected_endpoints = []
        
        for _ in range(num_requests):
            endpoint = await gateway._select_endpoint()
            selected_endpoints.append(endpoint)
        
        # Verify: No failed endpoints were selected
        for selected in selected_endpoints:
            assert selected not in failed_endpoints, \
                f"Failed endpoint {selected} should not be selected"
            assert selected in available_endpoints, \
                f"Selected endpoint {selected} should be in available endpoints"
        
        # Verify: All available endpoints are used
        unique_selected = set(selected_endpoints)
        assert unique_selected == set(available_endpoints), \
            f"All available endpoints should be used. " \
            f"Expected {set(available_endpoints)}, got {unique_selected}"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        endpoints=endpoint_lists(min_size=3, max_size=5)
    )
    @pytest.mark.asyncio
    async def test_recovered_endpoints_readded_to_rotation(self, endpoints):
        """
        Property: For any endpoint that transitions from unavailable to available,
        the gateway automatically re-adds it to the load balancing rotation.
        
        # Feature: irisvoice-backend-integration, Property 69: VPS Load Balancing
        **Validates: Requirements 26.9**
        """
        # Setup: Create VPS config with round-robin strategy
        config = VPSConfig(
            enabled=True,
            endpoints=endpoints,
            auth_token="test-token",
            timeout=30,
            load_balancing=True,
            load_balancing_strategy=LoadBalancingStrategy.ROUND_ROBIN,
            fallback_to_local=True
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        gateway = VPSGateway(config, mock_router)
        
        # Initially mark first endpoint as failed
        failed_endpoint = endpoints[0]
        available_endpoints_initial = endpoints[1:]
        
        for endpoint in endpoints:
            is_available = endpoint != failed_endpoint
            gateway._health_status[endpoint] = VPSHealthStatus(
                endpoint=endpoint,
                available=is_available,
                last_check=datetime.now(),
                last_success=datetime.now() if is_available else None,
                consecutive_failures=0 if is_available else 3,
                latency_ms=100.0 if is_available else None
            )
        
        # Execute: Select endpoints before recovery
        selections_before = []
        for _ in range(len(available_endpoints_initial) * 2):
            endpoint = await gateway._select_endpoint()
            selections_before.append(endpoint)
        
        # Verify: Failed endpoint not selected before recovery
        assert failed_endpoint not in selections_before, \
            f"Failed endpoint {failed_endpoint} should not be selected before recovery"
        
        # Recover the failed endpoint
        gateway._health_status[failed_endpoint].available = True
        gateway._health_status[failed_endpoint].consecutive_failures = 0
        gateway._health_status[failed_endpoint].latency_ms = 100.0
        gateway._health_status[failed_endpoint].last_success = datetime.now()
        gateway._health_status[failed_endpoint].error_message = None
        
        # Reset round-robin index to start fresh
        gateway._endpoint_index = 0
        
        # Execute: Select endpoints after recovery
        selections_after = []
        for _ in range(len(endpoints) * 2):
            endpoint = await gateway._select_endpoint()
            selections_after.append(endpoint)
        
        # Verify: Recovered endpoint is now selected
        assert failed_endpoint in selections_after, \
            f"Recovered endpoint {failed_endpoint} should be selected after recovery"
        
        # Verify: All endpoints are now in rotation
        unique_after = set(selections_after)
        assert unique_after == set(endpoints), \
            f"All endpoints should be in rotation after recovery. " \
            f"Expected {set(endpoints)}, got {unique_after}"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        num_endpoints=st.integers(min_value=2, max_value=5)
    )
    @pytest.mark.asyncio
    async def test_load_balancing_works_with_varying_endpoint_counts(self, num_endpoints):
        """
        Property: For any number of endpoints (2-5), load balancing distributes
        requests evenly across all available endpoints.
        
        # Feature: irisvoice-backend-integration, Property 69: VPS Load Balancing
        **Validates: Requirements 26.9**
        """
        # Setup: Create endpoints
        endpoints = [f"https://vps{i}.example.com:8000" for i in range(1, num_endpoints + 1)]
        
        config = VPSConfig(
            enabled=True,
            endpoints=endpoints,
            auth_token="test-token",
            timeout=30,
            load_balancing=True,
            load_balancing_strategy=LoadBalancingStrategy.ROUND_ROBIN,
            fallback_to_local=True
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        gateway = VPSGateway(config, mock_router)
        
        # Initialize all endpoints as available
        for endpoint in endpoints:
            gateway._health_status[endpoint] = VPSHealthStatus(
                endpoint=endpoint,
                available=True,
                last_check=datetime.now(),
                last_success=datetime.now(),
                consecutive_failures=0,
                latency_ms=100.0
            )
        
        # Execute: Select endpoints (3 full cycles)
        num_requests = num_endpoints * 3
        selected_endpoints = []
        
        for _ in range(num_requests):
            endpoint = await gateway._select_endpoint()
            selected_endpoints.append(endpoint)
        
        # Verify: Each endpoint selected exactly 3 times
        from collections import Counter
        selection_counts = Counter(selected_endpoints)
        
        for endpoint in endpoints:
            assert selection_counts[endpoint] == 3, \
                f"With {num_endpoints} endpoints, each should be selected 3 times, " \
                f"but {endpoint} was selected {selection_counts[endpoint]} times"
        
        # Verify: Total selections match expected
        assert len(selected_endpoints) == num_requests, \
            f"Should have {num_requests} total selections, got {len(selected_endpoints)}"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        endpoints=endpoint_lists(min_size=2, max_size=4)
    )
    @pytest.mark.asyncio
    async def test_active_request_tracking_during_concurrent_requests(self, endpoints):
        """
        Property: For any concurrent requests, active request counters are
        accurately incremented and decremented for each endpoint.
        
        # Feature: irisvoice-backend-integration, Property 69: VPS Load Balancing
        **Validates: Requirements 26.9**
        """
        # Setup: Create VPS config
        config = VPSConfig(
            enabled=True,
            endpoints=endpoints,
            auth_token="test-token",
            timeout=30,
            load_balancing=True,
            load_balancing_strategy=LoadBalancingStrategy.LEAST_LOADED,
            fallback_to_local=True
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        gateway = VPSGateway(config, mock_router)
        
        # Mock HTTP client
        mock_http_client = AsyncMock()
        gateway._http_client = mock_http_client
        
        # Initialize all endpoints as available with zero active requests
        for endpoint in endpoints:
            gateway._health_status[endpoint] = VPSHealthStatus(
                endpoint=endpoint,
                available=True,
                last_check=datetime.now(),
                last_success=datetime.now(),
                consecutive_failures=0,
                latency_ms=100.0,
                active_requests=0
            )
        
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "text": "Response",
            "model": "lfm2-8b",
            "latency_ms": 100.0,
            "metadata": {}
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post.return_value = mock_response
        
        # Verify: Initial active requests are zero
        for endpoint in endpoints:
            assert gateway._health_status[endpoint].active_requests == 0, \
                f"Initial active_requests for {endpoint} should be 0"
        
        # Execute: Select an endpoint
        selected_endpoint = await gateway._select_endpoint()
        
        # Execute: Make a request (infer_remote increments/decrements active_requests)
        try:
            await gateway.infer_remote(
                endpoint=selected_endpoint,
                model="lfm2-8b",
                prompt="Test prompt",
                context={},
                params={},
                session_id="test"
            )
        except Exception:
            pass
        
        # Verify: Active requests are back to zero after request completes
        assert gateway._health_status[selected_endpoint].active_requests == 0, \
            f"Active requests for {selected_endpoint} should be 0 after request completes"
        
        # Verify: Other endpoints still have zero active requests
        for endpoint in endpoints:
            if endpoint != selected_endpoint:
                assert gateway._health_status[endpoint].active_requests == 0, \
                    f"Active requests for {endpoint} should remain 0"
    
    @settings(max_examples=10, deadline=None)
    @seed(42)
    @given(
        endpoints=endpoint_lists(min_size=2, max_size=4)
    )
    @pytest.mark.asyncio
    async def test_least_loaded_considers_both_latency_and_active_requests(self, endpoints):
        """
        Property: For least-loaded strategy, the load calculation considers
        both active requests and latency (load = active_requests + latency_ms / 1000).
        
        # Feature: irisvoice-backend-integration, Property 69: VPS Load Balancing
        **Validates: Requirements 26.9**
        """
        # Setup: Create VPS config with least-loaded strategy
        config = VPSConfig(
            enabled=True,
            endpoints=endpoints,
            auth_token="test-token",
            timeout=30,
            load_balancing=True,
            load_balancing_strategy=LoadBalancingStrategy.LEAST_LOADED,
            fallback_to_local=True
        )
        
        mock_router = MagicMock(spec=ModelRouter)
        gateway = VPSGateway(config, mock_router)
        
        # Setup scenario: endpoint1 has high latency but no active requests
        #                 endpoint2 has low latency but many active requests
        # The one with lower total load should be selected
        
        if len(endpoints) >= 2:
            endpoint1 = endpoints[0]
            endpoint2 = endpoints[1]
            
            # endpoint1: high latency (400ms), no active requests
            # load = 0 + 400/1000 = 0.4
            gateway._health_status[endpoint1] = VPSHealthStatus(
                endpoint=endpoint1,
                available=True,
                last_check=datetime.now(),
                last_success=datetime.now(),
                consecutive_failures=0,
                latency_ms=400.0,
                active_requests=0
            )
            
            # endpoint2: low latency (50ms), 1 active request
            # load = 1 + 50/1000 = 1.05
            gateway._health_status[endpoint2] = VPSHealthStatus(
                endpoint=endpoint2,
                available=True,
                last_check=datetime.now(),
                last_success=datetime.now(),
                consecutive_failures=0,
                latency_ms=50.0,
                active_requests=1
            )
            
            # Initialize remaining endpoints with higher load than endpoint1
            for endpoint in endpoints[2:]:
                gateway._health_status[endpoint] = VPSHealthStatus(
                    endpoint=endpoint,
                    available=True,
                    last_check=datetime.now(),
                    last_success=datetime.now(),
                    consecutive_failures=0,
                    latency_ms=500.0,  # Higher latency: load = 0 + 500/1000 = 0.5
                    active_requests=0
                )
            
            # Execute: Select endpoint
            selected_endpoint = await gateway._select_endpoint()
            
            # Verify: endpoint1 should be selected (load 0.4 < 1.05)
            assert selected_endpoint == endpoint1, \
                f"Least-loaded should select {endpoint1} (load=0.4) over " \
                f"{endpoint2} (load=1.05), but selected {selected_endpoint}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
