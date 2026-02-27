#!/usr/bin/env python3
"""
Integration tests for AgentKernel with VPSGateway.

Tests the integration between AgentKernel and VPSGateway to ensure:
- VPSGateway is properly initialized
- VPS configuration can be loaded from settings
- VPS status is included in agent status
- VPS logging is working
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch, AsyncMock
import json

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.agent.agent_kernel import AgentKernel
from backend.agent.vps_gateway import VPSConfig


class TestAgentKernelVPSIntegration:
    """Test suite for AgentKernel VPS Gateway integration."""
    
    def test_vps_gateway_initialized_on_startup(self):
        """Test that VPS Gateway is initialized when AgentKernel starts."""
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            # Mock ModelRouter
            mock_model = Mock()
            mock_model.model_id = "test-model"
            mock_model.is_loaded.return_value = True
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_model
            mock_router.get_execution_model.return_value = mock_model
            mock_router.models = {"test-model": mock_model}
            mock_router.get_all_models_status.return_value = {"test-model": {}}
            mock_router.get_loaded_models.return_value = {}
            mock_router_class.return_value = mock_router
            
            # Create AgentKernel
            kernel = AgentKernel(session_id="test_vps_init")
            
            # Verify VPS Gateway is initialized
            assert kernel._vps_gateway is not None
            assert kernel._vps_config is not None
            assert kernel._vps_config.enabled is False  # Default disabled
    
    def test_configure_vps_updates_gateway(self):
        """Test that configure_vps updates VPS Gateway configuration."""
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            # Mock ModelRouter
            mock_model = Mock()
            mock_model.model_id = "test-model"
            mock_model.is_loaded.return_value = True
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_model
            mock_router.get_execution_model.return_value = mock_model
            mock_router.models = {"test-model": mock_model}
            mock_router.get_all_models_status.return_value = {"test-model": {}}
            mock_router.get_loaded_models.return_value = {}
            mock_router_class.return_value = mock_router
            
            # Create AgentKernel
            kernel = AgentKernel(session_id="test_vps_config")
            
            # Configure VPS
            vps_config = {
                "enabled": True,
                "endpoints": ["https://vps1.example.com:8000", "https://vps2.example.com:8000"],
                "auth_token": "test-token",
                "timeout": 45,
                "health_check_interval": 90,
                "fallback_to_local": True,
                "load_balancing": True,
                "load_balancing_strategy": "least_loaded",
                "protocol": "rest",
                "offload_tools": False
            }
            
            kernel.configure_vps(vps_config)
            
            # Verify configuration applied
            assert kernel._vps_config.enabled is True
            assert len(kernel._vps_config.endpoints) == 2
            assert kernel._vps_config.endpoints[0] == "https://vps1.example.com:8000"
            assert kernel._vps_config.auth_token == "test-token"
            assert kernel._vps_config.timeout == 45
            assert kernel._vps_config.health_check_interval == 90
            assert kernel._vps_config.load_balancing is True
            assert kernel._vps_config.load_balancing_strategy == "least_loaded"
    
    def test_get_status_includes_vps_gateway_status(self):
        """Test that get_status includes VPS Gateway status."""
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            # Mock ModelRouter
            mock_model = Mock()
            mock_model.model_id = "test-model"
            mock_model.is_loaded.return_value = True
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_model
            mock_router.get_execution_model.return_value = mock_model
            mock_router.models = {"test-model": mock_model}
            mock_router.get_all_models_status.return_value = {"test-model": {}}
            mock_router.get_loaded_models.return_value = {}
            mock_router_class.return_value = mock_router
            
            # Create AgentKernel
            kernel = AgentKernel(session_id="test_vps_status")
            
            # Get status
            status = kernel.get_status()
            
            # Verify VPS Gateway status is included
            assert "vps_gateway" in status
            assert "enabled" in status["vps_gateway"]
            assert status["vps_gateway"]["enabled"] is False
            assert "available_endpoints" in status["vps_gateway"]
    
    def test_vps_gateway_status_with_enabled_config(self):
        """Test VPS Gateway status when VPS is enabled."""
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            # Mock ModelRouter
            mock_model = Mock()
            mock_model.model_id = "test-model"
            mock_model.is_loaded.return_value = True
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_model
            mock_router.get_execution_model.return_value = mock_model
            mock_router.models = {"test-model": mock_model}
            mock_router.get_all_models_status.return_value = {"test-model": {}}
            mock_router.get_loaded_models.return_value = {}
            mock_router_class.return_value = mock_router
            
            # Create AgentKernel
            kernel = AgentKernel(session_id="test_vps_enabled_status")
            
            # Configure VPS
            vps_config = {
                "enabled": True,
                "endpoints": ["https://vps1.example.com:8000"],
                "auth_token": "test-token"
            }
            kernel.configure_vps(vps_config)
            
            # Get status
            status = kernel.get_status()
            
            # Verify VPS Gateway status
            assert status["vps_gateway"]["enabled"] is True
            assert status["vps_gateway"]["endpoints"] == 1
            assert "health_status" in status["vps_gateway"]
    
    @pytest.mark.asyncio
    async def test_initialize_vps_gateway_async(self):
        """Test async initialization of VPS Gateway."""
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            # Mock ModelRouter
            mock_model = Mock()
            mock_model.model_id = "test-model"
            mock_model.is_loaded.return_value = True
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_model
            mock_router.get_execution_model.return_value = mock_model
            mock_router.models = {"test-model": mock_model}
            mock_router.get_all_models_status.return_value = {"test-model": {}}
            mock_router.get_loaded_models.return_value = {}
            mock_router_class.return_value = mock_router
            
            # Create AgentKernel
            kernel = AgentKernel(session_id="test_vps_async_init")
            
            # Configure VPS
            vps_config = {
                "enabled": True,
                "endpoints": ["https://vps1.example.com:8000"],
                "auth_token": "test-token"
            }
            kernel.configure_vps(vps_config)
            
            # Mock VPS Gateway initialize method
            with patch.object(kernel._vps_gateway, 'initialize', new_callable=AsyncMock) as mock_init:
                # Initialize VPS Gateway
                await kernel.initialize_vps_gateway()
                
                # Verify initialize was called
                mock_init.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_shutdown_vps_gateway_async(self):
        """Test async shutdown of VPS Gateway."""
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            # Mock ModelRouter
            mock_model = Mock()
            mock_model.model_id = "test-model"
            mock_model.is_loaded.return_value = True
            
            mock_router = Mock()
            mock_router.get_reasoning_model.return_value = mock_model
            mock_router.get_execution_model.return_value = mock_model
            mock_router.models = {"test-model": mock_model}
            mock_router.get_all_models_status.return_value = {"test-model": {}}
            mock_router.get_loaded_models.return_value = {}
            mock_router_class.return_value = mock_router
            
            # Create AgentKernel
            kernel = AgentKernel(session_id="test_vps_async_shutdown")
            
            # Mock VPS Gateway shutdown method
            with patch.object(kernel._vps_gateway, 'shutdown', new_callable=AsyncMock) as mock_shutdown:
                # Shutdown VPS Gateway
                await kernel.shutdown_vps_gateway()
                
                # Verify shutdown was called
                mock_shutdown.assert_called_once()
    
    def test_vps_logging_on_configuration(self):
        """Test that VPS configuration changes are logged."""
        with patch('backend.agent.agent_kernel.ModelRouter') as mock_router_class:
            with patch('backend.agent.agent_kernel.logger') as mock_logger:
                # Mock ModelRouter
                mock_model = Mock()
                mock_model.model_id = "test-model"
                mock_model.is_loaded.return_value = True
                
                mock_router = Mock()
                mock_router.get_reasoning_model.return_value = mock_model
                mock_router.get_execution_model.return_value = mock_model
                mock_router.models = {"test-model": mock_model}
                mock_router.get_all_models_status.return_value = {"test-model": {}}
                mock_router.get_loaded_models.return_value = {}
                mock_router_class.return_value = mock_router
                
                # Create AgentKernel
                kernel = AgentKernel(session_id="test_vps_logging")
                
                # Reset mock to clear initialization logs
                mock_logger.reset_mock()
                
                # Configure VPS
                vps_config = {
                    "enabled": True,
                    "endpoints": ["https://vps1.example.com:8000"],
                    "auth_token": "test-token"
                }
                kernel.configure_vps(vps_config)
                
                # Verify logging occurred
                assert mock_logger.info.called
                # Check that configuration was logged
                log_calls = [str(call) for call in mock_logger.info.call_args_list]
                assert any("Configuring VPS Gateway" in str(call) for call in log_calls)
                assert any("VPS Gateway reconfigured" in str(call) for call in log_calls)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
