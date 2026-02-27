"""
Integration tests for IRISGateway and AgentKernel.

Tests the integration between IRISGateway message routing and AgentKernel processing.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch
import json

from backend.iris_gateway import IRISGateway


@pytest.fixture
def mock_ws_manager():
    """Create a mock WebSocket manager."""
    manager = MagicMock()
    manager.send_to_client = AsyncMock()
    manager.broadcast_to_session = AsyncMock()
    manager.get_session_id_for_client = MagicMock(return_value="test-session-123")
    return manager


@pytest.fixture
def mock_state_manager():
    """Create a mock State manager."""
    manager = MagicMock()
    manager.get_state = AsyncMock()
    manager.set_category = AsyncMock()
    manager.set_subnode = AsyncMock()
    manager.update_field = AsyncMock(return_value=True)
    manager.update_theme = AsyncMock()
    return manager


@pytest.fixture
def gateway(mock_ws_manager, mock_state_manager):
    """Create IRISGateway with mocked dependencies."""
    return IRISGateway(mock_ws_manager, mock_state_manager)


class TestChatHandling:
    """Test chat message handling with AgentKernel integration."""
    
    @pytest.mark.asyncio
    async def test_text_message_routes_to_agent_kernel(self, gateway, mock_ws_manager):
        """Test that text_message is routed to AgentKernel and response is sent."""
        client_id = "test_client_1"
        
        # Send text message
        message = {
            "type": "text_message",
            "payload": {
                "text": "Hello, agent!"
            }
        }
        
        await gateway.handle_message(client_id, message)
        
        # Wait a bit for async processing
        await asyncio.sleep(0.5)
        
        # Verify response was sent
        assert mock_ws_manager.send_to_client.called
        
        # Get the last call
        calls = mock_ws_manager.send_to_client.call_args_list
        assert len(calls) > 0
        
        # Check that a text_response was sent
        last_call = calls[-1]
        response_data = last_call[0][1]  # Second argument is the message dict
        
        assert response_data["type"] == "text_response"
        assert "payload" in response_data
        assert "text" in response_data["payload"]
        assert response_data["payload"]["sender"] == "assistant"
    
    @pytest.mark.asyncio
    async def test_text_message_missing_text(self, gateway, mock_ws_manager):
        """Test that text_message without text sends validation error."""
        client_id = "test_client_1"
        
        # Send text message without text
        message = {
            "type": "text_message",
            "payload": {}
        }
        
        await gateway.handle_message(client_id, message)
        
        # Verify validation error was sent
        assert mock_ws_manager.send_to_client.called
        
        last_call = mock_ws_manager.send_to_client.call_args_list[-1]
        response_data = last_call[0][1]
        
        assert response_data["type"] == "validation_error"
        assert response_data["payload"]["field_id"] == "text"
    
    @pytest.mark.asyncio
    async def test_clear_chat_clears_conversation(self, gateway, mock_ws_manager):
        """Test that clear_chat sends chat_cleared response."""
        client_id = "test_client_1"
        
        # Clear chat
        message = {
            "type": "clear_chat",
            "payload": {}
        }
        await gateway.handle_message(client_id, message)
        
        # Verify chat_cleared response was sent
        assert mock_ws_manager.send_to_client.called
        calls = mock_ws_manager.send_to_client.call_args_list
        last_call = calls[-1]
        response_data = last_call[0][1]
        
        assert response_data["type"] == "chat_cleared"


class TestStatusHandling:
    """Test status message handling with AgentKernel integration."""
    
    @pytest.mark.asyncio
    async def test_get_agent_status_returns_status(self, gateway, mock_ws_manager):
        """Test that get_agent_status returns agent status."""
        client_id = "test_client_1"
        
        # Request agent status
        message = {
            "type": "get_agent_status",
            "payload": {}
        }
        
        await gateway.handle_message(client_id, message)
        
        # Verify status response was sent
        assert mock_ws_manager.send_to_client.called
        
        last_call = mock_ws_manager.send_to_client.call_args_list[-1]
        response_data = last_call[0][1]
        
        assert response_data["type"] == "agent_status"
        assert "payload" in response_data
        
        payload = response_data["payload"]
        # Check required fields from Requirements 18.2-18.6
        assert "ready" in payload
        assert "models_loaded" in payload
        assert "total_models" in payload
        assert "tool_bridge_available" in payload
        assert "model_status" in payload
    
    @pytest.mark.asyncio
    async def test_get_agent_tools_returns_empty_list(self, gateway, mock_ws_manager):
        """Test that get_agent_tools returns empty list (tool bridge not yet integrated)."""
        client_id = "test_client_1"
        
        # Request agent tools
        message = {
            "type": "get_agent_tools",
            "payload": {}
        }
        
        await gateway.handle_message(client_id, message)
        
        # Verify tools response was sent
        assert mock_ws_manager.send_to_client.called
        
        last_call = mock_ws_manager.send_to_client.call_args_list[-1]
        response_data = last_call[0][1]
        
        assert response_data["type"] == "agent_tools"
        assert "payload" in response_data
        assert "tools" in response_data["payload"]
        assert response_data["payload"]["tools"] == []
