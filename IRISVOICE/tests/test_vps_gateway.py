#!/usr/bin/env python3
"""
Unit tests for VPS Gateway health monitoring functionality.

Tests verify:
- Health check execution and status tracking
- Automatic fallback on health check failure
- Automatic resume on health check success
- Background health check task operation
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from backend.agent.vps_gateway import (
    VPSGateway,
    VPSConfig,
    VPSHealthStatus,
    VPSProtocol
)


@pytest.fixture
def mock_model_router():
    """Create a mock ModelRouter for testing."""
    router = MagicMock()
    router.get_reasoning_model = MagicMock()
    router.get_execution_model = MagicMock()
    return router


@pytest.fixture
def vps_config():
    """Create a VPS configuration for testing."""
    return VPSConfig(
        enabled=True,
        endpoints=["https://vps1.example.com:8000", "https://vps2.example.com:8000"],
        auth_token="test-token",
        timeout=30,
        health_check_interval=1,  # Short interval for testing
        fallback_to_local=True,
        load_balancing=True,
        protocol=VPSProtocol.REST
    )


@pytest.fixture
def vps_gateway(vps_config, mock_model_router):
    """Create a VPS Gateway instance for testing."""
    gateway = VPSGateway(vps_config, mock_model_router)
    return gateway


class TestVPSHealthMonitoring:
    """Test suite for VPS health monitoring functionality."""
    
    @pytest.mark.asyncio
    async def test_health_check_success(self, vps_gateway, vps_config):
        """Test that successful health check marks endpoint as available."""
        endpoint = vps_config.endpoints[0]
        
        # Mock HTTP client
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        
        with patch.object(vps_gateway, '_http_client') as mock_client:
            mock_client.get = AsyncMock(return_value=mock_response)
            
            # Initialize health status
            vps_gateway._health_status[endpoint] = VPSHealthStatus(
                endpoint=endpoint,
                available=False,
                consecutive_failures=3
            )
            
            # Perform health check
            result = await vps_gateway.check_vps_health(endpoint)
            
            # Verify success
            assert result is True
            assert vps_gateway._health_status[endpoint].available is True
            assert vps_gateway._health_status[endpoint].consecutive_failures == 0
            assert vps_gateway._health_status[endpoint].last_success is not None
            assert vps_gateway._health_status[endpoint].error_message is None
    
    @pytest.mark.asyncio
    async def test_health_check_failure(self, vps_gateway, vps_config):
        """Test that failed health check marks endpoint as unavailable."""
        endpoint = vps_config.endpoints[0]
        
        # Mock HTTP client to raise exception
        with patch.object(vps_gateway, '_http_client') as mock_client:
            mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
            
            # Initialize health status
            vps_gateway._health_status[endpoint] = VPSHealthStatus(
                endpoint=endpoint,
                available=True,
                consecutive_failures=0
            )
            
            # Perform health check
            result = await vps_gateway.check_vps_health(endpoint)
            
            # Verify failure
            assert result is False
            assert vps_gateway._health_status[endpoint].available is False
            assert vps_gateway._health_status[endpoint].consecutive_failures == 1
            assert vps_gateway._health_status[endpoint].error_message == "Connection refused"
    
    @pytest.mark.asyncio
    async def test_consecutive_failures_tracking(self, vps_gateway, vps_config):
        """Test that consecutive failures are tracked correctly."""
        endpoint = vps_config.endpoints[0]
        
        # Mock HTTP client to raise exception
        with patch.object(vps_gateway, '_http_client') as mock_client:
            mock_client.get = AsyncMock(side_effect=Exception("Timeout"))
            
            # Initialize health status
            vps_gateway._health_status[endpoint] = VPSHealthStatus(
                endpoint=endpoint,
                available=True,
                consecutive_failures=0
            )
            
            # Perform multiple health checks
            for i in range(3):
                await vps_gateway.check_vps_health(endpoint)
                assert vps_gateway._health_status[endpoint].consecutive_failures == i + 1
    
    @pytest.mark.asyncio
    async def test_automatic_fallback_on_failure(self, vps_gateway, vps_config, mock_model_router):
        """Test that gateway falls back to local execution when VPS fails."""
        # Initialize gateway
        await vps_gateway.initialize()
        
        # Mock all endpoints as unavailable
        for endpoint in vps_config.endpoints:
            vps_gateway._health_status[endpoint].available = False
        
        # Mock local inference
        mock_model = MagicMock()
        mock_model.generate = MagicMock(return_value="Local response")
        mock_model.model_id = "lfm2-8b"
        mock_model_router.get_reasoning_model.return_value = mock_model
        
        # Perform inference
        result = await vps_gateway.infer(
            model="lfm2-8b",
            prompt="Test prompt",
            context={},
            params={},
            session_id="test"
        )
        
        # Verify local execution was used
        assert result == "Local response"
        mock_model_router.get_reasoning_model.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_automatic_resume_on_recovery(self, vps_gateway, vps_config):
        """Test that gateway resumes using VPS when it becomes available."""
        endpoint = vps_config.endpoints[0]
        
        # Initialize gateway
        await vps_gateway.initialize()
        
        # Start with endpoint unavailable
        vps_gateway._health_status[endpoint].available = False
        vps_gateway._health_status[endpoint].consecutive_failures = 5
        
        # Mock successful health check
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        
        with patch.object(vps_gateway, '_http_client') as mock_client:
            mock_client.get = AsyncMock(return_value=mock_response)
            
            # Perform health check
            result = await vps_gateway.check_vps_health(endpoint)
            
            # Verify endpoint is now available
            assert result is True
            assert vps_gateway._health_status[endpoint].available is True
            assert vps_gateway._health_status[endpoint].consecutive_failures == 0
            
            # Verify endpoint is included in selection
            selected = await vps_gateway._select_endpoint()
            assert selected in vps_config.endpoints
    
    @pytest.mark.asyncio
    async def test_health_check_all_endpoints(self, vps_gateway, vps_config):
        """Test that all endpoints are checked during periodic health checks."""
        # Initialize gateway
        await vps_gateway.initialize()
        
        # Mock HTTP client
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        
        with patch.object(vps_gateway, '_http_client') as mock_client:
            mock_client.get = AsyncMock(return_value=mock_response)
            
            # Perform health check on all endpoints
            await vps_gateway._check_all_endpoints_health()
            
            # Verify all endpoints were checked
            assert mock_client.get.call_count == len(vps_config.endpoints)
            
            # Verify all endpoints are marked as available
            for endpoint in vps_config.endpoints:
                assert vps_gateway._health_status[endpoint].available is True
    
    @pytest.mark.asyncio
    async def test_health_check_loop_runs_periodically(self, vps_gateway, vps_config):
        """Test that health check loop runs at configured interval."""
        # Initialize gateway
        await vps_gateway.initialize()
        
        # Mock health check method
        check_count = 0
        original_check = vps_gateway._check_all_endpoints_health
        
        async def mock_check():
            nonlocal check_count
            check_count += 1
            await original_check()
        
        vps_gateway._check_all_endpoints_health = mock_check
        
        # Wait for at least 2 health check cycles
        await asyncio.sleep(vps_config.health_check_interval * 2.5)
        
        # Verify health checks ran multiple times
        assert check_count >= 2
    
    @pytest.mark.asyncio
    async def test_endpoint_selection_excludes_unavailable(self, vps_gateway, vps_config):
        """Test that endpoint selection excludes unavailable endpoints."""
        # Initialize gateway
        await vps_gateway.initialize()
        
        # Mark first endpoint as unavailable
        vps_gateway._health_status[vps_config.endpoints[0]].available = False
        vps_gateway._health_status[vps_config.endpoints[1]].available = True
        
        # Select endpoint
        selected = await vps_gateway._select_endpoint()
        
        # Verify only available endpoint is selected
        assert selected == vps_config.endpoints[1]
    
    @pytest.mark.asyncio
    async def test_no_available_endpoints_returns_none(self, vps_gateway, vps_config):
        """Test that endpoint selection returns None when no endpoints available."""
        # Initialize gateway
        await vps_gateway.initialize()
        
        # Mark all endpoints as unavailable
        for endpoint in vps_config.endpoints:
            vps_gateway._health_status[endpoint].available = False
        
        # Select endpoint
        selected = await vps_gateway._select_endpoint()
        
        # Verify None is returned
        assert selected is None
    
    @pytest.mark.asyncio
    async def test_health_check_updates_latency(self, vps_gateway, vps_config):
        """Test that health check updates latency measurement."""
        endpoint = vps_config.endpoints[0]
        
        # Mock HTTP client with delay
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        
        async def delayed_get(*args, **kwargs):
            await asyncio.sleep(0.1)  # 100ms delay
            return mock_response
        
        with patch.object(vps_gateway, '_http_client') as mock_client:
            mock_client.get = delayed_get
            
            # Initialize health status
            vps_gateway._health_status[endpoint] = VPSHealthStatus(endpoint=endpoint)
            
            # Perform health check
            await vps_gateway.check_vps_health(endpoint)
            
            # Verify latency was measured
            assert vps_gateway._health_status[endpoint].latency_ms is not None
            assert vps_gateway._health_status[endpoint].latency_ms >= 100
    
    @pytest.mark.asyncio
    async def test_is_vps_available(self, vps_gateway, vps_config):
        """Test is_vps_available returns correct status."""
        # Initialize gateway
        await vps_gateway.initialize()
        
        # All endpoints unavailable
        for endpoint in vps_config.endpoints:
            vps_gateway._health_status[endpoint].available = False
        assert vps_gateway.is_vps_available() is False
        
        # One endpoint available
        vps_gateway._health_status[vps_config.endpoints[0]].available = True
        assert vps_gateway.is_vps_available() is True
        
        # All endpoints available
        for endpoint in vps_config.endpoints:
            vps_gateway._health_status[endpoint].available = True
        assert vps_gateway.is_vps_available() is True
    
    @pytest.mark.asyncio
    async def test_get_status_includes_health_info(self, vps_gateway, vps_config):
        """Test that get_status includes health information."""
        # Initialize gateway
        await vps_gateway.initialize()
        
        # Set some health status
        vps_gateway._health_status[vps_config.endpoints[0]].available = True
        vps_gateway._health_status[vps_config.endpoints[0]].latency_ms = 50.0
        vps_gateway._health_status[vps_config.endpoints[1]].available = False
        vps_gateway._health_status[vps_config.endpoints[1]].error_message = "Connection timeout"
        
        # Get status
        status = vps_gateway.get_status()
        
        # Verify status includes health information
        assert status["enabled"] is True
        assert status["endpoints"] == 2
        assert status["available_endpoints"] == 1
        assert vps_config.endpoints[0] in status["health_status"]
        assert status["health_status"][vps_config.endpoints[0]]["available"] is True
        assert status["health_status"][vps_config.endpoints[0]]["latency_ms"] == 50.0
        assert status["health_status"][vps_config.endpoints[1]]["available"] is False
        assert status["health_status"][vps_config.endpoints[1]]["error_message"] == "Connection timeout"
    
    @pytest.mark.asyncio
    async def test_timeout_handling_updates_health_status(self, vps_config, mock_model_router):
        """Test that timeout exceptions update health status and fall back to local execution."""
        import httpx
        
        # Create gateway
        gateway = VPSGateway(vps_config, mock_model_router)
        
        # Mock HTTP client before initialization
        mock_http_client = MagicMock()
        mock_http_client.get = AsyncMock(return_value=MagicMock(raise_for_status=MagicMock()))
        mock_http_client.post = AsyncMock(side_effect=httpx.TimeoutException("Request timeout"))
        mock_http_client.aclose = AsyncMock()
        
        with patch('httpx.AsyncClient', return_value=mock_http_client):
            # Initialize gateway
            await gateway.initialize()
            
            endpoint = vps_config.endpoints[0]
            
            # Mock local inference
            mock_model = MagicMock()
            mock_model.generate = MagicMock(return_value="Local fallback response")
            mock_model.model_id = "lfm2-8b"
            mock_model_router.get_reasoning_model.return_value = mock_model
            
            # Perform inference (should timeout and fall back to local)
            result = await gateway.infer(
                model="lfm2-8b",
                prompt="Test prompt",
                context={},
                params={},
                session_id="test"
            )
            
            # Verify fallback to local execution occurred
            assert result == "Local fallback response"
            mock_model_router.get_reasoning_model.assert_called_once()
            
            # Verify health status was updated
            assert gateway._health_status[endpoint].available is False
            assert gateway._health_status[endpoint].consecutive_failures >= 1
            assert "Timeout after 30s" in gateway._health_status[endpoint].error_message
            
            # Cleanup
            await gateway.shutdown()
    
    @pytest.mark.asyncio
    async def test_timeout_logging_includes_monitoring_context(self, vps_config, mock_model_router):
        """Test that timeout events are logged with sufficient context for monitoring."""
        import httpx
        
        # Create gateway
        gateway = VPSGateway(vps_config, mock_model_router)
        
        # Mock HTTP client before initialization
        mock_http_client = MagicMock()
        mock_http_client.get = AsyncMock(return_value=MagicMock(raise_for_status=MagicMock()))
        mock_http_client.post = AsyncMock(side_effect=httpx.TimeoutException("Request timeout"))
        mock_http_client.aclose = AsyncMock()
        
        with patch('httpx.AsyncClient', return_value=mock_http_client):
            # Initialize gateway
            await gateway.initialize()
            
            # Mock local inference
            mock_model = MagicMock()
            mock_model.generate = MagicMock(return_value="Local fallback response")
            mock_model.model_id = "lfm2-8b"
            mock_model_router.get_reasoning_model.return_value = mock_model
            
            # Capture log output
            with patch('backend.agent.vps_gateway.logger') as mock_logger:
                # Perform inference
                await gateway.infer(
                    model="lfm2-8b",
                    prompt="Test prompt",
                    context={},
                    params={},
                    session_id="test-session"
                )
                
                # Verify timeout was logged with monitoring context
                error_calls = [call for call in mock_logger.error.call_args_list 
                              if "timeout" in str(call).lower()]
                assert len(error_calls) > 0
                
                # Verify log includes key monitoring fields
                timeout_call = error_calls[0]
                call_kwargs = timeout_call[1] if len(timeout_call) > 1 else {}
                assert "endpoint" in call_kwargs
                assert "model" in call_kwargs
                assert "timeout" in call_kwargs
                assert "session_id" in call_kwargs
                assert call_kwargs["session_id"] == "test-session"
            
            # Cleanup
            await gateway.shutdown()
    
    @pytest.mark.asyncio
    async def test_timeout_with_fallback_disabled_raises_exception(self, mock_model_router):
        """Test that timeout raises exception when fallback is disabled."""
        import httpx
        
        # Create config with fallback disabled
        config_no_fallback = VPSConfig(
            enabled=True,
            endpoints=["https://vps1.example.com:8000"],
            auth_token="test-token",
            timeout=30,
            health_check_interval=60,
            fallback_to_local=False,  # Disable fallback
            load_balancing=False,
            protocol=VPSProtocol.REST
        )
        
        gateway = VPSGateway(config_no_fallback, mock_model_router)
        
        # Mock HTTP client before initialization
        mock_http_client = MagicMock()
        mock_http_client.get = AsyncMock(return_value=MagicMock(raise_for_status=MagicMock()))
        mock_http_client.post = AsyncMock(side_effect=httpx.TimeoutException("Request timeout"))
        mock_http_client.aclose = AsyncMock()
        
        with patch('httpx.AsyncClient', return_value=mock_http_client):
            # Initialize gateway
            await gateway.initialize()
            
            endpoint = config_no_fallback.endpoints[0]
            
            # Perform inference (should raise exception)
            with pytest.raises(httpx.TimeoutException):
                await gateway.infer(
                    model="lfm2-8b",
                    prompt="Test prompt",
                    context={},
                    params={},
                    session_id="test"
                )
            
            # Verify health status was still updated
            assert gateway._health_status[endpoint].available is False
            assert gateway._health_status[endpoint].consecutive_failures >= 1
            
            # Cleanup
            await gateway.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestVPSLoadBalancing:
    """Test suite for VPS load balancing functionality."""
    
    @pytest.mark.asyncio
    async def test_round_robin_strategy_cycles_endpoints(self, mock_model_router):
        """Test that round-robin strategy cycles through available endpoints."""
        from backend.agent.vps_gateway import LoadBalancingStrategy
        
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps1.example.com:8000", "https://vps2.example.com:8000", "https://vps3.example.com:8000"],
            auth_token="test-token",
            timeout=30,
            health_check_interval=60,
            fallback_to_local=True,
            load_balancing=True,
            load_balancing_strategy=LoadBalancingStrategy.ROUND_ROBIN,
            protocol=VPSProtocol.REST
        )
        
        gateway = VPSGateway(config, mock_model_router)
        await gateway.initialize()
        
        # Mark all endpoints as available
        for endpoint in config.endpoints:
            gateway._health_status[endpoint].available = True
        
        # Select endpoints multiple times
        selected_endpoints = []
        for _ in range(6):
            endpoint = await gateway._select_endpoint()
            selected_endpoints.append(endpoint)
        
        # Verify round-robin cycling
        assert selected_endpoints[0] == config.endpoints[0]
        assert selected_endpoints[1] == config.endpoints[1]
        assert selected_endpoints[2] == config.endpoints[2]
        assert selected_endpoints[3] == config.endpoints[0]  # Cycle back
        assert selected_endpoints[4] == config.endpoints[1]
        assert selected_endpoints[5] == config.endpoints[2]
        
        await gateway.shutdown()
    
    @pytest.mark.asyncio
    async def test_least_loaded_strategy_selects_lowest_latency(self, mock_model_router):
        """Test that least-loaded strategy selects endpoint with lowest latency."""
        from backend.agent.vps_gateway import LoadBalancingStrategy
        
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps1.example.com:8000", "https://vps2.example.com:8000", "https://vps3.example.com:8000"],
            auth_token="test-token",
            timeout=30,
            health_check_interval=60,
            fallback_to_local=True,
            load_balancing=True,
            load_balancing_strategy=LoadBalancingStrategy.LEAST_LOADED,
            protocol=VPSProtocol.REST
        )
        
        gateway = VPSGateway(config, mock_model_router)
        await gateway.initialize()
        
        # Mark all endpoints as available with different latencies
        gateway._health_status[config.endpoints[0]].available = True
        gateway._health_status[config.endpoints[0]].latency_ms = 100.0
        gateway._health_status[config.endpoints[0]].active_requests = 0
        
        gateway._health_status[config.endpoints[1]].available = True
        gateway._health_status[config.endpoints[1]].latency_ms = 50.0  # Lowest latency
        gateway._health_status[config.endpoints[1]].active_requests = 0
        
        gateway._health_status[config.endpoints[2]].available = True
        gateway._health_status[config.endpoints[2]].latency_ms = 150.0
        gateway._health_status[config.endpoints[2]].active_requests = 0
        
        # Select endpoint
        selected = await gateway._select_endpoint()
        
        # Verify endpoint with lowest latency is selected
        assert selected == config.endpoints[1]
        
        await gateway.shutdown()
    
    @pytest.mark.asyncio
    async def test_least_loaded_strategy_considers_active_requests(self, mock_model_router):
        """Test that least-loaded strategy considers active requests."""
        from backend.agent.vps_gateway import LoadBalancingStrategy
        
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps1.example.com:8000", "https://vps2.example.com:8000"],
            auth_token="test-token",
            timeout=30,
            health_check_interval=60,
            fallback_to_local=True,
            load_balancing=True,
            load_balancing_strategy=LoadBalancingStrategy.LEAST_LOADED,
            protocol=VPSProtocol.REST
        )
        
        gateway = VPSGateway(config, mock_model_router)
        await gateway.initialize()
        
        # Mark endpoints as available with same latency but different active requests
        gateway._health_status[config.endpoints[0]].available = True
        gateway._health_status[config.endpoints[0]].latency_ms = 50.0
        gateway._health_status[config.endpoints[0]].active_requests = 5  # More requests
        
        gateway._health_status[config.endpoints[1]].available = True
        gateway._health_status[config.endpoints[1]].latency_ms = 50.0
        gateway._health_status[config.endpoints[1]].active_requests = 1  # Fewer requests
        
        # Select endpoint
        selected = await gateway._select_endpoint()
        
        # Verify endpoint with fewer active requests is selected
        assert selected == config.endpoints[1]
        
        await gateway.shutdown()
    
    @pytest.mark.asyncio
    async def test_active_requests_tracking(self, mock_model_router):
        """Test that active requests are tracked correctly during inference."""
        import httpx
        
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps1.example.com:8000"],
            auth_token="test-token",
            timeout=30,
            health_check_interval=60,
            fallback_to_local=True,
            load_balancing=False,
            protocol=VPSProtocol.REST
        )
        
        gateway = VPSGateway(config, mock_model_router)
        
        # Mock HTTP client
        mock_http_client = MagicMock()
        mock_http_client.get = AsyncMock(return_value=MagicMock(raise_for_status=MagicMock()))
        
        # Track active requests during POST
        active_requests_during_call = []
        
        async def mock_post(*args, **kwargs):
            # Record active requests during the call
            endpoint = config.endpoints[0]
            active_requests_during_call.append(gateway._health_status[endpoint].active_requests)
            
            # Simulate successful response
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(return_value={
                "text": "Test response",
                "model": "lfm2-8b",
                "latency_ms": 100.0,
                "metadata": {}
            })
            return mock_response
        
        mock_http_client.post = mock_post
        mock_http_client.aclose = AsyncMock()
        
        with patch('httpx.AsyncClient', return_value=mock_http_client):
            await gateway.initialize()
            
            endpoint = config.endpoints[0]
            
            # Verify initial active requests is 0
            assert gateway._health_status[endpoint].active_requests == 0
            
            # Perform inference
            result = await gateway.infer(
                model="lfm2-8b",
                prompt="Test prompt",
                context={},
                params={},
                session_id="test"
            )
            
            # Verify active requests was incremented during call
            assert len(active_requests_during_call) > 0
            assert active_requests_during_call[0] == 1
            
            # Verify active requests is back to 0 after call
            assert gateway._health_status[endpoint].active_requests == 0
            
            await gateway.shutdown()
    
    @pytest.mark.asyncio
    async def test_active_requests_decremented_on_error(self, mock_model_router):
        """Test that active requests are decremented even when inference fails."""
        import httpx
        
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps1.example.com:8000"],
            auth_token="test-token",
            timeout=30,
            health_check_interval=60,
            fallback_to_local=True,
            load_balancing=False,
            protocol=VPSProtocol.REST
        )
        
        gateway = VPSGateway(config, mock_model_router)
        
        # Mock HTTP client to raise error
        mock_http_client = MagicMock()
        mock_http_client.get = AsyncMock(return_value=MagicMock(raise_for_status=MagicMock()))
        mock_http_client.post = AsyncMock(side_effect=httpx.HTTPError("Server error"))
        mock_http_client.aclose = AsyncMock()
        
        with patch('httpx.AsyncClient', return_value=mock_http_client):
            await gateway.initialize()
            
            endpoint = config.endpoints[0]
            
            # Mock local inference for fallback
            mock_model = MagicMock()
            mock_model.generate = MagicMock(return_value="Local response")
            mock_model.model_id = "lfm2-8b"
            mock_model_router.get_reasoning_model.return_value = mock_model
            
            # Verify initial active requests is 0
            assert gateway._health_status[endpoint].active_requests == 0
            
            # Perform inference (will fail and fall back to local)
            result = await gateway.infer(
                model="lfm2-8b",
                prompt="Test prompt",
                context={},
                params={},
                session_id="test"
            )
            
            # Verify active requests is back to 0 even after error
            assert gateway._health_status[endpoint].active_requests == 0
            
            await gateway.shutdown()
    
    @pytest.mark.asyncio
    async def test_load_balancing_excludes_failed_endpoints(self, mock_model_router):
        """Test that load balancing automatically excludes failed endpoints."""
        from backend.agent.vps_gateway import LoadBalancingStrategy
        
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps1.example.com:8000", "https://vps2.example.com:8000", "https://vps3.example.com:8000"],
            auth_token="test-token",
            timeout=30,
            health_check_interval=60,
            fallback_to_local=True,
            load_balancing=True,
            load_balancing_strategy=LoadBalancingStrategy.ROUND_ROBIN,
            protocol=VPSProtocol.REST
        )
        
        gateway = VPSGateway(config, mock_model_router)
        await gateway.initialize()
        
        # Mark first endpoint as unavailable
        gateway._health_status[config.endpoints[0]].available = False
        gateway._health_status[config.endpoints[1]].available = True
        gateway._health_status[config.endpoints[2]].available = True
        
        # Select endpoints multiple times
        selected_endpoints = []
        for _ in range(4):
            endpoint = await gateway._select_endpoint()
            selected_endpoints.append(endpoint)
        
        # Verify failed endpoint is excluded
        assert config.endpoints[0] not in selected_endpoints
        # Verify only available endpoints are selected
        assert all(ep in [config.endpoints[1], config.endpoints[2]] for ep in selected_endpoints)
        # Verify round-robin among available endpoints
        assert selected_endpoints[0] == config.endpoints[1]
        assert selected_endpoints[1] == config.endpoints[2]
        assert selected_endpoints[2] == config.endpoints[1]
        assert selected_endpoints[3] == config.endpoints[2]
        
        await gateway.shutdown()
    
    @pytest.mark.asyncio
    async def test_recovered_endpoint_added_back_to_rotation(self, mock_model_router):
        """Test that recovered endpoints are automatically added back to rotation."""
        from backend.agent.vps_gateway import LoadBalancingStrategy
        
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps1.example.com:8000", "https://vps2.example.com:8000"],
            auth_token="test-token",
            timeout=30,
            health_check_interval=60,
            fallback_to_local=True,
            load_balancing=True,
            load_balancing_strategy=LoadBalancingStrategy.ROUND_ROBIN,
            protocol=VPSProtocol.REST
        )
        
        gateway = VPSGateway(config, mock_model_router)
        await gateway.initialize()
        
        # Start with first endpoint unavailable
        gateway._health_status[config.endpoints[0]].available = False
        gateway._health_status[config.endpoints[1]].available = True
        
        # Select endpoint - should only get endpoint 1
        selected = await gateway._select_endpoint()
        assert selected == config.endpoints[1]
        
        # Simulate endpoint 0 recovery
        gateway._health_status[config.endpoints[0]].available = True
        
        # Select endpoints multiple times
        selected_endpoints = []
        for _ in range(4):
            endpoint = await gateway._select_endpoint()
            selected_endpoints.append(endpoint)
        
        # Verify recovered endpoint is now included in rotation
        assert config.endpoints[0] in selected_endpoints
        assert config.endpoints[1] in selected_endpoints
        
        await gateway.shutdown()
    
    @pytest.mark.asyncio
    async def test_get_status_includes_load_balancing_info(self, mock_model_router):
        """Test that get_status includes load balancing configuration."""
        from backend.agent.vps_gateway import LoadBalancingStrategy
        
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps1.example.com:8000", "https://vps2.example.com:8000"],
            auth_token="test-token",
            timeout=30,
            health_check_interval=60,
            fallback_to_local=True,
            load_balancing=True,
            load_balancing_strategy=LoadBalancingStrategy.LEAST_LOADED,
            protocol=VPSProtocol.REST
        )
        
        gateway = VPSGateway(config, mock_model_router)
        await gateway.initialize()
        
        # Set some active requests
        gateway._health_status[config.endpoints[0]].available = True
        gateway._health_status[config.endpoints[0]].active_requests = 3
        gateway._health_status[config.endpoints[1]].available = True
        gateway._health_status[config.endpoints[1]].active_requests = 1
        
        # Get status
        status = gateway.get_status()
        
        # Verify load balancing info is included
        assert status["load_balancing"] is True
        assert status["load_balancing_strategy"] == LoadBalancingStrategy.LEAST_LOADED
        assert status["health_status"][config.endpoints[0]]["active_requests"] == 3
        assert status["health_status"][config.endpoints[1]]["active_requests"] == 1
        
        await gateway.shutdown()
    
    @pytest.mark.asyncio
    async def test_single_endpoint_no_load_balancing(self, mock_model_router):
        """Test that single endpoint doesn't use load balancing logic."""
        from backend.agent.vps_gateway import LoadBalancingStrategy
        
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps1.example.com:8000"],
            auth_token="test-token",
            timeout=30,
            health_check_interval=60,
            fallback_to_local=True,
            load_balancing=True,
            load_balancing_strategy=LoadBalancingStrategy.ROUND_ROBIN,
            protocol=VPSProtocol.REST
        )
        
        gateway = VPSGateway(config, mock_model_router)
        await gateway.initialize()
        
        # Mark endpoint as available
        gateway._health_status[config.endpoints[0]].available = True
        
        # Select endpoint multiple times
        for _ in range(5):
            selected = await gateway._select_endpoint()
            assert selected == config.endpoints[0]
        
        await gateway.shutdown()
    
    @pytest.mark.asyncio
    async def test_load_balancing_disabled_returns_first_available(self, mock_model_router):
        """Test that when load balancing is disabled, first available endpoint is always returned."""
        config = VPSConfig(
            enabled=True,
            endpoints=["https://vps1.example.com:8000", "https://vps2.example.com:8000", "https://vps3.example.com:8000"],
            auth_token="test-token",
            timeout=30,
            health_check_interval=60,
            fallback_to_local=True,
            load_balancing=False,  # Disabled
            protocol=VPSProtocol.REST
        )
        
        gateway = VPSGateway(config, mock_model_router)
        await gateway.initialize()
        
        # Mark all endpoints as available
        for endpoint in config.endpoints:
            gateway._health_status[endpoint].available = True
        
        # Select endpoint multiple times
        for _ in range(5):
            selected = await gateway._select_endpoint()
            assert selected == config.endpoints[0]  # Always first
        
        await gateway.shutdown()
