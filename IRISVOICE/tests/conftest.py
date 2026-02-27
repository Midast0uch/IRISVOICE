"""
Pytest configuration for IRISVOICE tests.
"""
import sys
import os
import pytest
from unittest.mock import MagicMock, AsyncMock

# Add the project root to the path so imports work correctly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# Integration test fixtures
@pytest.fixture
def mock_websocket_manager():
    """Mock WebSocket manager for integration tests."""
    manager = MagicMock()
    manager.active_connections = {}
    manager._client_sessions = {}
    
    # Make connect return the session_id and add to active_connections
    async def mock_connect(websocket, client_id, session_id=None):
        await websocket.accept()
        manager.active_connections[client_id] = websocket
        if session_id:
            manager._client_sessions[client_id] = session_id
        return session_id or "default-session"
    
    manager.connect = AsyncMock(side_effect=mock_connect)
    
    # Make disconnect remove from active_connections
    def mock_disconnect(client_id):
        if client_id in manager.active_connections:
            del manager.active_connections[client_id]
        if client_id in manager._client_sessions:
            del manager._client_sessions[client_id]
    
    manager.disconnect = MagicMock(side_effect=mock_disconnect)
    
    # Make send_to_client actually call websocket.send_json
    async def mock_send_to_client(client_id, message):
        if client_id in manager.active_connections:
            await manager.active_connections[client_id].send_json(message)
            return True
        return False
    
    manager.send_to_client = AsyncMock(side_effect=mock_send_to_client)
    manager.broadcast = AsyncMock()
    manager.broadcast_to_session = AsyncMock()
    
    def mock_get_session_id(client_id):
        return manager._client_sessions.get(client_id)
    
    manager.get_session_id_for_client = MagicMock(side_effect=mock_get_session_id)
    return manager


@pytest.fixture
def mock_session_manager():
    """Mock session manager for integration tests."""
    manager = MagicMock()
    manager.create_session = AsyncMock()
    manager.get_session = MagicMock()
    manager.associate_client_with_session = MagicMock()
    manager.dissociate_client = MagicMock()
    manager.restore_session = AsyncMock()
    return manager


@pytest.fixture
def mock_state_manager():
    """Mock state manager for integration tests."""
    manager = MagicMock()
    manager.get_state = AsyncMock()
    manager.set_category = AsyncMock()
    manager.set_subnode = AsyncMock()
    manager.update_field = AsyncMock()
    manager.update_theme = AsyncMock()
    manager.confirm_subnode = AsyncMock()
    return manager


@pytest.fixture
def mock_agent_kernel():
    """Mock agent kernel for integration tests."""
    kernel = MagicMock()
    kernel.process_text_message = AsyncMock()
    kernel.get_status = MagicMock()
    kernel.fallback_mode = False
    return kernel


@pytest.fixture
def mock_voice_pipeline():
    """Mock voice pipeline for integration tests."""
    pipeline = MagicMock()
    pipeline.start_listening = AsyncMock()
    pipeline.stop_listening = AsyncMock()
    pipeline.get_audio_level = MagicMock(return_value=0.0)
    pipeline.configure_wake_word = AsyncMock()
    pipeline.fallback_to_default_device = AsyncMock()
    return pipeline


@pytest.fixture
def mock_tool_bridge():
    """Mock tool bridge for integration tests."""
    bridge = MagicMock()
    bridge.execute_tool = AsyncMock()
    bridge.execute_mcp_tool = AsyncMock()
    bridge.execute_vision_tool = AsyncMock()
    bridge.get_available_tools = MagicMock(return_value=[])
    return bridge


@pytest.fixture
def mock_conversation_memory():
    """Mock conversation memory for integration tests."""
    memory = MagicMock()
    memory.add_message = MagicMock()
    memory.get_context = MagicMock(return_value=[])
    memory.clear = MagicMock()
    memory.save_to_storage = AsyncMock()
    memory.archive = AsyncMock()
    return memory


@pytest.fixture
def mock_security_filter():
    """Mock security filter for integration tests."""
    filter_obj = MagicMock()
    filter_obj.validate_params = MagicMock(return_value=True)
    filter_obj.get_violation_reason = MagicMock(return_value="")
    filter_obj.is_destructive = MagicMock(return_value=False)
    filter_obj.sanitize_params = MagicMock()
    filter_obj.check_rate_limit = MagicMock(return_value=True)
    return filter_obj


@pytest.fixture
def mock_audit_logger():
    """Mock audit logger for integration tests."""
    logger = MagicMock()
    logger.log_tool_execution = MagicMock()
    logger.detect_suspicious_pattern = MagicMock(return_value=False)
    logger.alert_suspicious_activity = MagicMock()
    return logger


@pytest.fixture
def mock_model_router():
    """Mock model router for integration tests."""
    router = MagicMock()
    router.route_message = AsyncMock()
    return router


@pytest.fixture
def mock_vps_gateway():
    """Mock VPS gateway for integration tests."""
    gateway = MagicMock()
    gateway.infer = AsyncMock()
    gateway.infer_remote = AsyncMock()
    gateway.infer_local = AsyncMock()
    gateway.check_vps_health = AsyncMock()
    gateway.is_vps_available = MagicMock(return_value=True)
    gateway._health_status = {}
    return gateway


@pytest.fixture
def mock_server_manager():
    """Mock MCP server manager for integration tests."""
    manager = MagicMock()
    manager.check_server_health = AsyncMock()
    manager.restart_server = AsyncMock()
    return manager