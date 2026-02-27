"""
Unit tests for IRISGateway message routing
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.iris_gateway import IRISGateway
from backend.core_models import Category, IRISState, ColorTheme, AppState


@pytest.fixture
def mock_ws_manager():
    """Create a mock WebSocket manager"""
    manager = MagicMock()
    manager.send_to_client = AsyncMock()
    manager.broadcast_to_session = AsyncMock()
    manager.handle_pong = AsyncMock()
    manager.get_session_id_for_client = MagicMock(return_value="test-session-123")
    return manager


@pytest.fixture
def mock_state_manager():
    """Create a mock State manager"""
    manager = MagicMock()
    manager.set_category = AsyncMock()
    manager.set_subnode = AsyncMock()
    manager.update_field = AsyncMock(return_value=True)
    manager.update_theme = AsyncMock()
    manager.confirm_subnode = AsyncMock(return_value=45.0)
    manager.go_back = AsyncMock()
    
    # Mock state
    mock_state = IRISState(
        current_category=Category.VOICE,
        current_subnode=None,
        field_values={},
        active_theme=ColorTheme(
            primary="#00ff00",
            glow="#00ff00",
            font="#ffffff",
            state_colors_enabled=False,
            idle_color="#00ff00",
            listening_color="#00ff00",
            processing_color="#7000ff",
            error_color="#ff0000"
        ),
        confirmed_nodes=[],
        app_state=AppState.READY
    )
    manager.get_state = AsyncMock(return_value=mock_state)
    
    return manager


@pytest.fixture
def gateway(mock_ws_manager, mock_state_manager):
    """Create an IRISGateway instance with mocked dependencies"""
    return IRISGateway(
        ws_manager=mock_ws_manager,
        state_manager=mock_state_manager
    )


class TestMessageValidation:
    """Test message validation"""
    
    @pytest.mark.asyncio
    async def test_invalid_message_format_not_dict(self, gateway, mock_ws_manager):
        """Test handling of non-dict message"""
        await gateway.handle_message("client-1", "not a dict")
        
        # Should send error
        mock_ws_manager.send_to_client.assert_called_once()
        call_args = mock_ws_manager.send_to_client.call_args[0]
        assert call_args[0] == "client-1"
        assert call_args[1]["type"] == "error"
    
    @pytest.mark.asyncio
    async def test_missing_message_type(self, gateway, mock_ws_manager):
        """Test handling of message without type field"""
        await gateway.handle_message("client-1", {"payload": {}})
        
        # Should send error
        mock_ws_manager.send_to_client.assert_called_once()
        call_args = mock_ws_manager.send_to_client.call_args[0]
        assert call_args[0] == "client-1"
        assert call_args[1]["type"] == "error"
    
    @pytest.mark.asyncio
    async def test_no_session_for_client(self, gateway, mock_ws_manager):
        """Test handling when client has no session"""
        mock_ws_manager.get_session_id_for_client.return_value = None
        
        await gateway.handle_message("client-1", {"type": "select_category"})
        
        # Should send error
        mock_ws_manager.send_to_client.assert_called_once()
        call_args = mock_ws_manager.send_to_client.call_args[0]
        assert call_args[0] == "client-1"
        assert call_args[1]["type"] == "error"


class TestNavigationHandling:
    """Test navigation message handling"""
    
    @pytest.mark.asyncio
    async def test_select_category(self, gateway, mock_ws_manager, mock_state_manager):
        """Test select_category message handling"""
        message = {
            "type": "select_category",
            "category": "voice"
        }
        
        await gateway.handle_message("client-1", message)
        
        # Should update state
        mock_state_manager.set_category.assert_called_once()
        call_args = mock_state_manager.set_category.call_args[0]
        assert call_args[0] == "test-session-123"
        assert call_args[1] == Category.VOICE
        
        # Should send category_changed response
        assert mock_ws_manager.send_to_client.call_count >= 1
        # Find the category_changed call
        for call in mock_ws_manager.send_to_client.call_args_list:
            if call[0][1]["type"] == "category_changed":
                assert call[0][0] == "client-1"
                assert "subnodes" in call[0][1]["payload"]
                break
        else:
            pytest.fail("category_changed message not sent")
    
    @pytest.mark.asyncio
    async def test_select_category_with_payload(self, gateway, mock_ws_manager, mock_state_manager):
        """Test select_category with category in payload"""
        message = {
            "type": "select_category",
            "payload": {"category": "agent"}
        }
        
        await gateway.handle_message("client-1", message)
        
        # Should update state
        mock_state_manager.set_category.assert_called_once()
        call_args = mock_state_manager.set_category.call_args[0]
        assert call_args[1] == Category.AGENT
    
    @pytest.mark.asyncio
    async def test_select_category_missing_category(self, gateway, mock_ws_manager):
        """Test select_category without category field"""
        message = {"type": "select_category"}
        
        await gateway.handle_message("client-1", message)
        
        # Should send validation error
        mock_ws_manager.send_to_client.assert_called_once()
        call_args = mock_ws_manager.send_to_client.call_args[0]
        assert call_args[1]["type"] == "validation_error"
    
    @pytest.mark.asyncio
    async def test_select_category_invalid_category(self, gateway, mock_ws_manager):
        """Test select_category with invalid category"""
        message = {
            "type": "select_category",
            "category": "invalid_category"
        }
        
        await gateway.handle_message("client-1", message)
        
        # Should send validation error
        mock_ws_manager.send_to_client.assert_called_once()
        call_args = mock_ws_manager.send_to_client.call_args[0]
        assert call_args[1]["type"] == "validation_error"
    
    @pytest.mark.asyncio
    async def test_select_subnode(self, gateway, mock_ws_manager, mock_state_manager):
        """Test select_subnode message handling"""
        message = {
            "type": "select_subnode",
            "subnode_id": "input"
        }
        
        await gateway.handle_message("client-1", message)
        
        # Should update state
        mock_state_manager.set_subnode.assert_called_once()
        call_args = mock_state_manager.set_subnode.call_args[0]
        assert call_args[0] == "test-session-123"
        assert call_args[1] == "input"
        
        # Should send subnode_changed response
        assert mock_ws_manager.send_to_client.call_count >= 1
        for call in mock_ws_manager.send_to_client.call_args_list:
            if call[0][1]["type"] == "subnode_changed":
                assert call[0][0] == "client-1"
                assert call[0][1]["payload"]["subnode_id"] == "input"
                break
        else:
            pytest.fail("subnode_changed message not sent")
    
    @pytest.mark.asyncio
    async def test_go_back(self, gateway, mock_ws_manager, mock_state_manager):
        """Test go_back message handling"""
        message = {"type": "go_back"}
        
        await gateway.handle_message("client-1", message)
        
        # Should call go_back
        mock_state_manager.go_back.assert_called_once()
        call_args = mock_state_manager.go_back.call_args[0]
        assert call_args[0] == "test-session-123"


class TestSettingsHandling:
    """Test settings message handling"""
    
    @pytest.mark.asyncio
    async def test_update_field(self, gateway, mock_ws_manager, mock_state_manager):
        """Test update_field message handling"""
        message = {
            "type": "update_field",
            "subnode_id": "input",
            "field_id": "input_device",
            "value": "Microphone (USB)"
        }
        
        await gateway.handle_message("client-1", message)
        
        # Should update field
        mock_state_manager.update_field.assert_called_once()
        call_args = mock_state_manager.update_field.call_args[0]
        assert call_args[0] == "test-session-123"
        assert call_args[1] == "input"
        assert call_args[2] == "input_device"
        assert call_args[3] == "Microphone (USB)"
        
        # Should send field_updated response
        assert mock_ws_manager.send_to_client.call_count >= 1
        for call in mock_ws_manager.send_to_client.call_args_list:
            if call[0][1]["type"] == "field_updated":
                payload = call[0][1]["payload"]
                assert payload["subnode_id"] == "input"
                assert payload["field_id"] == "input_device"
                assert payload["value"] == "Microphone (USB)"
                assert payload["valid"] is True
                break
        else:
            pytest.fail("field_updated message not sent")
    
    @pytest.mark.asyncio
    async def test_update_field_validation_failure(self, gateway, mock_ws_manager, mock_state_manager):
        """Test update_field with validation failure"""
        mock_state_manager.update_field.return_value = False
        
        message = {
            "type": "update_field",
            "subnode_id": "input",
            "field_id": "input_device",
            "value": "invalid"
        }
        
        await gateway.handle_message("client-1", message)
        
        # Should send validation error
        mock_ws_manager.send_to_client.assert_called_once()
        call_args = mock_ws_manager.send_to_client.call_args[0]
        assert call_args[1]["type"] == "validation_error"
    
    @pytest.mark.asyncio
    async def test_update_theme(self, gateway, mock_ws_manager, mock_state_manager):
        """Test update_theme message handling"""
        message = {
            "type": "update_theme",
            "payload": {
                "glow_color": "#ff00ff",
                "font_color": "#ffffff"
            }
        }
        
        await gateway.handle_message("client-1", message)
        
        # Should update theme
        mock_state_manager.update_theme.assert_called_once()
        call_args = mock_state_manager.update_theme.call_args
        assert call_args[0][0] == "test-session-123"
        assert call_args[1]["glow_color"] == "#ff00ff"
        assert call_args[1]["font_color"] == "#ffffff"
        
        # Should broadcast theme_updated
        mock_ws_manager.broadcast_to_session.assert_called()
        for call in mock_ws_manager.broadcast_to_session.call_args_list:
            if call[0][1]["type"] == "theme_updated":
                assert "active_theme" in call[0][1]["payload"]
                break
        else:
            pytest.fail("theme_updated message not broadcast")
    
    @pytest.mark.asyncio
    async def test_confirm_mini_node(self, gateway, mock_ws_manager, mock_state_manager):
        """Test confirm_mini_node message handling"""
        message = {
            "type": "confirm_mini_node",
            "payload": {
                "subnode_id": "input",
                "values": {"input_device": "Microphone"}
            }
        }
        
        await gateway.handle_message("client-1", message)
        
        # Should confirm subnode
        mock_state_manager.confirm_subnode.assert_called_once()
        call_args = mock_state_manager.confirm_subnode.call_args[0]
        assert call_args[0] == "test-session-123"
        assert call_args[2] == "input"
        
        # Should send mini_node_confirmed response
        assert mock_ws_manager.send_to_client.call_count >= 1
        for call in mock_ws_manager.send_to_client.call_args_list:
            if call[0][1]["type"] == "mini_node_confirmed":
                payload = call[0][1]["payload"]
                assert payload["subnode_id"] == "input"
                assert payload["orbit_angle"] == 45.0
                break
        else:
            pytest.fail("mini_node_confirmed message not sent")


class TestPingPong:
    """Test ping/pong handling"""
    
    @pytest.mark.asyncio
    async def test_ping(self, gateway, mock_ws_manager):
        """Test ping message handling"""
        message = {"type": "ping"}
        
        await gateway.handle_message("client-1", message)
        
        # Should send pong
        mock_ws_manager.send_to_client.assert_called_once()
        call_args = mock_ws_manager.send_to_client.call_args[0]
        assert call_args[0] == "client-1"
        assert call_args[1]["type"] == "pong"
    
    @pytest.mark.asyncio
    async def test_pong(self, gateway, mock_ws_manager):
        """Test pong message handling"""
        message = {"type": "pong"}
        
        await gateway.handle_message("client-1", message)
        
        # Should handle pong
        mock_ws_manager.handle_pong.assert_called_once_with("client-1")


class TestRequestState:
    """Test request_state handling"""
    
    @pytest.mark.asyncio
    async def test_request_state(self, gateway, mock_ws_manager, mock_state_manager):
        """Test request_state message handling"""
        message = {"type": "request_state"}
        
        await gateway.handle_message("client-1", message)
        
        # Should get state
        mock_state_manager.get_state.assert_called()
        
        # Should send initial_state
        mock_ws_manager.send_to_client.assert_called_once()
        call_args = mock_ws_manager.send_to_client.call_args[0]
        assert call_args[0] == "client-1"
        assert call_args[1]["type"] == "initial_state"
        assert "state" in call_args[1]["payload"]


class TestUnknownMessageType:
    """Test unknown message type handling"""
    
    @pytest.mark.asyncio
    async def test_unknown_message_type(self, gateway, mock_ws_manager):
        """Test handling of unknown message type"""
        message = {"type": "unknown_type"}
        
        await gateway.handle_message("client-1", message)
        
        # Should send error
        mock_ws_manager.send_to_client.assert_called_once()
        call_args = mock_ws_manager.send_to_client.call_args[0]
        assert call_args[0] == "client-1"
        assert call_args[1]["type"] == "error"
        assert "unknown" in call_args[1]["payload"]["message"].lower()
