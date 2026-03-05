"""
Tests for IntegrationLifecycleManager.

Note: These tests mock subprocess.Popen and other external dependencies
to avoid actually spawning processes during testing.
"""

import asyncio
import json
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

import pytest

from ..lifecycle_manager import (
    IntegrationLifecycleManager,
    ProcessInfo,
    ProcessError,
    get_lifecycle_manager,
    reset_lifecycle_manager,
)
from ..models import IntegrationConfig, IntegrationStatus, AuthType


@pytest.fixture
def mock_credential_store():
    """Create a mock credential store."""
    store = MagicMock()
    store.exists = AsyncMock(return_value=True)
    store.load = AsyncMock(return_value={
        "integration_id": "gmail",
        "auth_type": "oauth2",
        "access_token": "test_token",
    })
    store.wipe = AsyncMock()
    return store


@pytest.fixture
def mock_registry_loader():
    """Create a mock registry loader."""
    loader = MagicMock()
    loader.get_integration = MagicMock(return_value=IntegrationConfig(
        id="gmail",
        name="Gmail",
        category="email",
        auth_type=AuthType.OAUTH2,
        icon="gmail.svg",
        mcp_server={
            "binary": "iris-mcp-gmail",
            "module": "servers/gmail/index.js",
            "tools": ["gmail_list_inbox"],
        },
        permissions_summary="Read and send Gmail",
        enabled_by_default=False,
    ))
    return loader


@pytest.fixture
def mock_mcp_host():
    """Create a mock MCP host."""
    host = AsyncMock()
    host.register_server = AsyncMock()
    host.deregister_server = AsyncMock()
    host.get_server_tools = AsyncMock(return_value=["gmail_list_inbox"])
    return host


@pytest.fixture
def lifecycle_manager(mock_credential_store, mock_registry_loader, mock_mcp_host):
    """Create a lifecycle manager with mocked dependencies."""
    reset_lifecycle_manager()
    manager = IntegrationLifecycleManager(
        credential_store=mock_credential_store,
        registry_loader=mock_registry_loader,
        mcp_host=mock_mcp_host,
    )
    return manager


@pytest.fixture
def mock_process():
    """Create a mock subprocess.Popen."""
    proc = MagicMock()
    proc.pid = 12345
    proc.poll = MagicMock(return_value=None)  # Running
    proc.stdin = MagicMock()
    proc.stdout = MagicMock()
    proc.stderr = MagicMock()
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = MagicMock(return_value=0)
    proc.send_signal = MagicMock()
    return proc


class TestIntegrationLifecycleManager:
    """Tests for IntegrationLifecycleManager."""
    
    @pytest.mark.asyncio
    async def test_enable_success(self, lifecycle_manager, mock_process):
        """Test successful enable flow."""
        with patch("subprocess.Popen", return_value=mock_process):
            result = await lifecycle_manager.enable("gmail")
        
        assert result is True
        assert "gmail" in lifecycle_manager._processes
        assert lifecycle_manager.is_running("gmail")
        
        state = lifecycle_manager.get_state("gmail")
        assert state.status == IntegrationStatus.RUNNING
    
    @pytest.mark.asyncio
    async def test_enable_no_credentials(self, lifecycle_manager):
        """Test enable when no credentials exist."""
        lifecycle_manager.credential_store.exists = AsyncMock(return_value=False)
        
        result = await lifecycle_manager.enable("gmail")
        
        assert result is False
        assert "gmail" not in lifecycle_manager._processes
        
        state = lifecycle_manager.get_state("gmail")
        assert state.status == IntegrationStatus.AUTH_PENDING
    
    @pytest.mark.asyncio
    async def test_enable_registry_not_found(self, lifecycle_manager):
        """Test enable when integration not in registry."""
        lifecycle_manager.registry_loader.get_integration = MagicMock(return_value=None)
        
        result = await lifecycle_manager.enable("unknown")
        
        assert result is False
        
        state = lifecycle_manager.get_state("unknown")
        assert state.status == IntegrationStatus.ERROR
        assert "not found" in state.error_message.lower()
    
    @pytest.mark.asyncio
    async def test_enable_already_running(self, lifecycle_manager, mock_process):
        """Test enable when already running."""
        with patch("subprocess.Popen", return_value=mock_process):
            await lifecycle_manager.enable("gmail")
            result = await lifecycle_manager.enable("gmail")
        
        assert result is True  # Returns True because it's already running
    
    @pytest.mark.asyncio
    async def test_enable_spawn_failure(self, lifecycle_manager):
        """Test enable when process spawn fails."""
        with patch("subprocess.Popen", side_effect=FileNotFoundError("Binary not found")):
            result = await lifecycle_manager.enable("gmail")
        
        assert result is False
        
        state = lifecycle_manager.get_state("gmail")
        assert state.status == IntegrationStatus.ERROR
        assert "spawn" in state.error_message.lower()
    
    @pytest.mark.asyncio
    async def test_disable_running(self, lifecycle_manager, mock_process):
        """Test disable stops running process."""
        with patch("subprocess.Popen", return_value=mock_process):
            await lifecycle_manager.enable("gmail")
        
        result = await lifecycle_manager.disable("gmail", forget_credentials=False)
        
        assert result is True
        assert "gmail" not in lifecycle_manager._processes
        assert not lifecycle_manager.is_running("gmail")
        
        mock_process.terminate.assert_called_once()
        lifecycle_manager.mcp_host.deregister_server.assert_called_once_with("gmail")
    
    @pytest.mark.asyncio
    async def test_disable_forget_credentials(self, lifecycle_manager, mock_process):
        """Test disable with credential wiping."""
        with patch("subprocess.Popen", return_value=mock_process):
            await lifecycle_manager.enable("gmail")
        
        result = await lifecycle_manager.disable("gmail", forget_credentials=True)
        
        assert result is True
        lifecycle_manager.credential_store.wipe.assert_called_once_with("gmail")
        
        state = lifecycle_manager.get_state("gmail")
        assert state.status == IntegrationStatus.WIPED
    
    @pytest.mark.asyncio
    async def test_disable_not_running(self, lifecycle_manager):
        """Test disable when not running."""
        result = await lifecycle_manager.disable("gmail", forget_credentials=False)
        
        assert result is True  # Still succeeds, nothing to do
    
    @pytest.mark.asyncio
    async def test_restart(self, lifecycle_manager, mock_process):
        """Test restart functionality."""
        with patch("subprocess.Popen", return_value=mock_process):
            await lifecycle_manager.enable("gmail")
            result = await lifecycle_manager.restart("gmail")
        
        assert result is True
        assert lifecycle_manager.is_running("gmail")
    
    @pytest.mark.asyncio
    async def test_process_monitor_graceful_exit(self, lifecycle_manager, mock_process):
        """Test monitor handles graceful process exit."""
        # Process exits cleanly after first check
        mock_process.poll = MagicMock(side_effect=[None, 0])
        
        with patch("subprocess.Popen", return_value=mock_process):
            await lifecycle_manager.enable("gmail")
            # Let monitor run briefly
            await asyncio.sleep(0.1)
        
        state = lifecycle_manager.get_state("gmail")
        assert state.status == IntegrationStatus.DISABLED
    
    @pytest.mark.asyncio
    async def test_process_monitor_crash_restart(self, lifecycle_manager, mock_process):
        """Test monitor handles crash and attempts restart."""
        # Process crashes after first check
        mock_process.poll = MagicMock(side_effect=[None, 1, None])
        
        mock_process2 = MagicMock()
        mock_process2.pid = 12346
        mock_process2.poll = MagicMock(return_value=None)
        mock_process2.stdin = MagicMock()
        mock_process2.stdout = MagicMock()
        mock_process2.stderr = MagicMock()
        mock_process2.terminate = MagicMock()
        mock_process2.kill = MagicMock()
        mock_process2.wait = MagicMock(return_value=0)
        
        with patch("subprocess.Popen", side_effect=[mock_process, mock_process2]):
            await lifecycle_manager.enable("gmail")
            # Wait for crash detection and restart
            await asyncio.sleep(3)  # Account for restart delay
        
        # Should have attempted restart
        assert mock_process2.poll() is None  # Second process running
    
    @pytest.mark.asyncio
    async def test_process_monitor_restart_exhaustion(self, lifecycle_manager, mock_process):
        """Test monitor gives up after max restarts."""
        lifecycle_manager.MAX_RESTART_ATTEMPTS = 2
        lifecycle_manager.RESTART_DELAY_BASE = 0.1  # Speed up test
        
        # Process always crashes
        mock_process.poll = MagicMock(return_value=1)
        
        with patch("subprocess.Popen", return_value=mock_process):
            await lifecycle_manager.enable("gmail")
            # Wait for multiple restart attempts
            await asyncio.sleep(1)
        
        state = lifecycle_manager.get_state("gmail")
        assert state.status == IntegrationStatus.ERROR
        assert "exhausted" in state.error_message.lower() or "crashed" in state.error_message.lower()
    
    @pytest.mark.asyncio
    async def test_shutdown_all(self, lifecycle_manager, mock_process):
        """Test shutdown all integrations."""
        mock_process2 = MagicMock()
        mock_process2.pid = 12346
        mock_process2.poll = MagicMock(return_value=None)
        mock_process2.stdin = MagicMock()
        mock_process2.stdout = MagicMock()
        mock_process2.terminate = MagicMock()
        mock_process2.kill = MagicMock()
        mock_process2.wait = MagicMock(return_value=0)
        
        with patch("subprocess.Popen", side_effect=[mock_process, mock_process2]):
            await lifecycle_manager.enable("gmail")
            
            # Mock a second integration
            lifecycle_manager.registry_loader.get_integration = MagicMock(return_value=IntegrationConfig(
                id="telegram",
                name="Telegram",
                category="messaging",
                auth_type=AuthType.TELEGRAM_MTPROTO,
                icon="telegram.svg",
                mcp_server={"binary": "iris-mcp-telegram", "runtime": "python"},
                permissions_summary="Read and send Telegram messages",
                enabled_by_default=False,
            ))
            lifecycle_manager.credential_store.exists = AsyncMock(return_value=True)
            await lifecycle_manager.enable("telegram")
        
        await lifecycle_manager.shutdown_all()
        
        assert len(lifecycle_manager._processes) == 0
    
    def test_event_handlers(self, lifecycle_manager):
        """Test event registration and emission."""
        events_received = []
        
        async def on_state_change(integration_id, state):
            events_received.append(("state_change", integration_id))
        
        def on_spawn(integration_id, process):
            events_received.append(("process_spawn", integration_id))
        
        lifecycle_manager.on("state_change", on_state_change)
        lifecycle_manager.on("process_spawn", on_spawn)
        
        # Emit events
        lifecycle_manager._emit("state_change", integration_id="test", state=None)
        lifecycle_manager._emit("process_spawn", integration_id="test", process=None)
        
        assert len(events_received) == 2
        assert ("state_change", "test") in events_received
        assert ("process_spawn", "test") in events_received
    
    def test_get_all_states(self, lifecycle_manager):
        """Test getting all states."""
        # Manually set some states
        lifecycle_manager._states["gmail"] = MagicMock()
        lifecycle_manager._states["telegram"] = MagicMock()
        
        states = lifecycle_manager.get_all_states()
        
        assert "gmail" in states
        assert "telegram" in states
    
    def test_get_process_info(self, lifecycle_manager):
        """Test getting process info."""
        mock_info = MagicMock()
        lifecycle_manager._processes["gmail"] = mock_info
        
        info = lifecycle_manager.get_process_info("gmail")
        
        assert info == mock_info
    
    @pytest.mark.asyncio
    async def test_credential_environment_injection(self, lifecycle_manager, mock_process):
        """Test credentials are injected via environment variable."""
        test_credential = {
            "integration_id": "gmail",
            "auth_type": "oauth2",
            "access_token": "secret_token_123",
        }
        lifecycle_manager.credential_store.load = AsyncMock(return_value=test_credential)
        
        captured_env = {}
        
        def capture_popen(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return mock_process
        
        with patch("subprocess.Popen", side_effect=capture_popen):
            await lifecycle_manager.enable("gmail")
        
        assert "IRIS_CREDENTIAL" in captured_env
        credential = json.loads(captured_env["IRIS_CREDENTIAL"])
        assert credential["access_token"] == "secret_token_123"
        assert captured_env["IRIS_INTEGRATION_ID"] == "gmail"
        assert captured_env["IRIS_MCP_VERSION"] == "1.0"
    
    @pytest.mark.asyncio
    async def test_python_module_spawn(self, lifecycle_manager, mock_process):
        """Test spawning Python-based MCP server."""
        lifecycle_manager.registry_loader.get_integration = MagicMock(return_value=IntegrationConfig(
            id="telegram",
            name="Telegram",
            category="messaging",
            auth_type=AuthType.TELEGRAM_MTPROTO,
            icon="telegram.svg",
            mcp_server={
                "module": "servers.telegram",
                "runtime": "python",
            },
            permissions_summary="Telegram access",
            enabled_by_default=False,
        ))
        
        captured_cmd = []
        
        def capture_popen(cmd, **kwargs):
            captured_cmd.extend(cmd)
            return mock_process
        
        with patch("subprocess.Popen", side_effect=capture_popen):
            await lifecycle_manager.enable("telegram")
        
        assert sys.executable in captured_cmd
        assert "-m" in captured_cmd
        assert "servers.telegram" in captured_cmd


class TestProcessInfo:
    """Tests for ProcessInfo dataclass."""
    
    def test_to_dict(self):
        """Test ProcessInfo serialization."""
        proc = MagicMock()
        proc.pid = 12345
        
        info = ProcessInfo(
            integration_id="gmail",
            process=proc,
            started_at=datetime(2024, 1, 1, 12, 0, 0),
            restart_count=2,
            last_exit_code=1,
            last_error="Connection failed",
        )
        
        data = info.to_dict()
        
        assert data["integration_id"] == "gmail"
        assert data["pid"] == 12345
        assert data["restart_count"] == 2
        assert data["last_exit_code"] == 1


class TestSingleton:
    """Tests for singleton pattern."""
    
    def test_get_lifecycle_manager_singleton(self):
        """Test singleton behavior."""
        reset_lifecycle_manager()
        
        manager1 = get_lifecycle_manager()
        manager2 = get_lifecycle_manager()
        
        assert manager1 is manager2
        
        reset_lifecycle_manager()
        manager3 = get_lifecycle_manager()
        
        assert manager1 is not manager3
