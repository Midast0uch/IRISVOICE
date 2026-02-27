"""
Property-based tests for MCP server startup resilience.
Tests universal properties that should hold for MCP server startup,
including error handling, logging, and continued operation when servers fail.
"""
import pytest
from hypothesis import given, settings, strategies as st, seed
import sys
import os
from unittest.mock import Mock, patch, AsyncMock, call
import asyncio
from datetime import datetime

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.mcp.server_manager import ServerManager, ServerConfig, ServerHealth


# ============================================================================
# Test Data Generators (Hypothesis Strategies)
# ============================================================================

@st.composite
def server_name_generator(draw):
    """Generate valid server names."""
    return draw(st.sampled_from([
        "BrowserServer",
        "AppLauncherServer",
        "SystemServer",
        "FileManagerServer",
        "GUIAutomationServer",
        "CustomServer1",
        "CustomServer2",
        "TestServer"
    ]))


@st.composite
def server_type_generator(draw):
    """Generate server types."""
    return draw(st.sampled_from(["stdio", "websocket", "http"]))


@st.composite
def server_config_generator(draw, will_fail=None):
    """Generate server configurations."""
    name = draw(server_name_generator())
    server_type = draw(server_type_generator())
    
    # If will_fail is specified, use it; otherwise randomly decide
    if will_fail is None:
        will_fail = draw(st.booleans())
    
    config = ServerConfig(
        name=name,
        type=server_type,
        enabled=True,
        health_check_interval=draw(st.integers(min_value=10, max_value=120)),
        max_restart_attempts=draw(st.integers(min_value=1, max_value=5)),
        restart_delay=draw(st.integers(min_value=1, max_value=10))
    )
    
    # Add type-specific configuration
    if server_type == "stdio":
        config.command = "python" if not will_fail else "nonexistent_command"
        config.args = ["-m", "server"] if not will_fail else ["--invalid"]
    elif server_type == "websocket":
        config.url = "ws://localhost:8080" if not will_fail else "ws://invalid:99999"
    elif server_type == "http":
        config.url = "http://localhost:8080" if not will_fail else "http://invalid:99999"
    
    return config, will_fail


@st.composite
def server_configs_list_generator(draw):
    """Generate a list of server configurations with some that will fail."""
    num_servers = draw(st.integers(min_value=2, max_value=8))
    num_failures = draw(st.integers(min_value=1, max_value=max(1, num_servers - 1)))
    
    configs = []
    failure_indices = draw(st.lists(
        st.integers(min_value=0, max_value=num_servers - 1),
        min_size=num_failures,
        max_size=num_failures,
        unique=True
    ))
    
    for i in range(num_servers):
        will_fail = i in failure_indices
        config, _ = draw(server_config_generator(will_fail=will_fail))
        # Ensure unique names
        config.name = f"{config.name}_{i}"
        configs.append((config, will_fail))
    
    return configs


@st.composite
def error_message_generator(draw):
    """Generate error messages for server failures."""
    return draw(st.sampled_from([
        "Connection refused",
        "Command not found",
        "Timeout connecting to server",
        "Invalid server configuration",
        "Server process crashed",
        "Network unreachable",
        "Permission denied"
    ]))


# ============================================================================
# Property 42: MCP Server Startup Resilience
# Feature: irisvoice-backend-integration, Property 42: MCP Server Startup Resilience
# Validates: Requirements 16.7
# ============================================================================

class TestMCPServerStartupResilience:
    """
    Property 42: MCP Server Startup Resilience
    
    For any MCP server that fails to start, the Server_Manager shall:
    - Log the error
    - Continue starting other servers
    - Not crash the system
    - Maintain valid state after failures
    
    This tests:
    - Requirement 16.7: Server startup failure handling
    """
    
    @settings(max_examples=100, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        server_configs=server_configs_list_generator()
    )
    @pytest.mark.asyncio
    async def test_failed_server_does_not_prevent_other_servers_from_starting(
        self, server_configs
    ):
        """
        Property: For any server that fails to start, other servers continue starting.
        
        # Feature: irisvoice-backend-integration, Property 42: MCP Server Startup Resilience
        **Validates: Requirements 16.7**
        """
        # Setup: Create fresh ServerManager instance
        ServerManager._instance = None
        ServerManager._initialized = False
        manager = ServerManager()
        
        # Register all servers
        for config, will_fail in server_configs:
            manager.register_server(config)
        
        # Mock the MCP client connections
        with patch('backend.mcp.server_manager.get_mcp_client') as mock_get_client:
            
            def create_mock_client(name, server_type):
                """Create a mock client that succeeds or fails based on config."""
                mock_client = Mock()
                
                # Find if this server should fail
                should_fail = False
                for config, will_fail in server_configs:
                    if config.name == name:
                        should_fail = will_fail
                        break
                
                # Setup connection methods
                async def connect_stdio(command, args):
                    if should_fail:
                        raise Exception(f"Failed to start {name}")
                    return True
                
                async def connect_websocket(url):
                    if should_fail:
                        raise Exception(f"Failed to connect to {name}")
                    return True
                
                async def connect_http(url):
                    if should_fail:
                        raise Exception(f"Failed to connect to {name}")
                    return True
                
                mock_client.connect_stdio = AsyncMock(side_effect=connect_stdio)
                mock_client.connect_websocket = AsyncMock(side_effect=connect_websocket)
                mock_client.connect_http = AsyncMock(side_effect=connect_http)
                mock_client.disconnect = AsyncMock()
                
                return mock_client
            
            mock_get_client.side_effect = create_mock_client
            
            # Execute: Connect all servers
            with patch('backend.mcp.server_manager.logger') as mock_logger:
                results = await manager.connect_all()
            
            # Verify: All servers were attempted
            assert len(results) == len(server_configs), \
                "All servers should be attempted"
            
            # Verify: Successful servers are connected
            expected_successes = [config.name for config, will_fail in server_configs if not will_fail]
            expected_failures = [config.name for config, will_fail in server_configs if will_fail]
            
            for name in expected_successes:
                assert results[name] is True, \
                    f"Server {name} should have connected successfully"
                assert manager.is_connected(name), \
                    f"Server {name} should be marked as connected"
            
            # Verify: Failed servers are not connected but system continues
            for name in expected_failures:
                assert results[name] is False, \
                    f"Server {name} should have failed to connect"
                assert not manager.is_connected(name), \
                    f"Server {name} should not be marked as connected"
            
            # Verify: At least one successful server (if any were supposed to succeed)
            if expected_successes:
                connected_servers = manager.get_connected_servers()
                assert len(connected_servers) > 0, \
                    "At least one server should be connected"
    
    @settings(max_examples=100, deadline=None)
    @seed(42)
    @given(
        server_configs=server_configs_list_generator()
    )
    @pytest.mark.asyncio
    async def test_server_failures_are_logged(self, server_configs):
        """
        Property: For any server that fails to start, the error is logged.
        
        # Feature: irisvoice-backend-integration, Property 42: MCP Server Startup Resilience
        **Validates: Requirements 16.7**
        """
        # Setup: Create fresh ServerManager instance
        ServerManager._instance = None
        ServerManager._initialized = False
        manager = ServerManager()
        
        # Register all servers
        for config, will_fail in server_configs:
            manager.register_server(config)
        
        # Mock the MCP client connections
        with patch('backend.mcp.server_manager.get_mcp_client') as mock_get_client:
            
            def create_mock_client(name, server_type):
                mock_client = Mock()
                
                # Find if this server should fail
                should_fail = False
                for config, will_fail in server_configs:
                    if config.name == name:
                        should_fail = will_fail
                        break
                
                async def connect_stdio(command, args):
                    if should_fail:
                        raise Exception(f"Failed to start {name}")
                    return True
                
                async def connect_websocket(url):
                    if should_fail:
                        raise Exception(f"Failed to connect to {name}")
                    return True
                
                async def connect_http(url):
                    if should_fail:
                        raise Exception(f"Failed to connect to {name}")
                    return True
                
                mock_client.connect_stdio = AsyncMock(side_effect=connect_stdio)
                mock_client.connect_websocket = AsyncMock(side_effect=connect_websocket)
                mock_client.connect_http = AsyncMock(side_effect=connect_http)
                mock_client.disconnect = AsyncMock()
                
                return mock_client
            
            mock_get_client.side_effect = create_mock_client
            
            # Execute: Connect all servers with logging mock
            with patch('backend.mcp.server_manager.logger') as mock_logger:
                await manager.connect_all()
                
                # Verify: Errors were logged for failed servers
                expected_failures = [config.name for config, will_fail in server_configs if will_fail]
                
                if expected_failures:
                    # Check that error logging occurred
                    error_calls = [call for call in mock_logger.error.call_args_list]
                    assert len(error_calls) >= len(expected_failures), \
                        f"Expected at least {len(expected_failures)} error log calls"
                    
                    # Verify each failed server was logged
                    logged_messages = [str(call) for call in error_calls]
                    for failed_name in expected_failures:
                        assert any(failed_name in msg for msg in logged_messages), \
                            f"Failed server {failed_name} should be logged"
    
    @settings(max_examples=100, deadline=None)
    @seed(42)
    @given(
        server_configs=server_configs_list_generator()
    )
    @pytest.mark.asyncio
    async def test_server_manager_remains_in_valid_state_after_failures(
        self, server_configs
    ):
        """
        Property: For any server failures, ServerManager remains in a valid state.
        
        # Feature: irisvoice-backend-integration, Property 42: MCP Server Startup Resilience
        **Validates: Requirements 16.7**
        """
        # Setup: Create fresh ServerManager instance
        ServerManager._instance = None
        ServerManager._initialized = False
        manager = ServerManager()
        
        # Register all servers
        for config, will_fail in server_configs:
            manager.register_server(config)
        
        # Mock the MCP client connections
        with patch('backend.mcp.server_manager.get_mcp_client') as mock_get_client:
            
            def create_mock_client(name, server_type):
                mock_client = Mock()
                
                # Find if this server should fail
                should_fail = False
                for config, will_fail in server_configs:
                    if config.name == name:
                        should_fail = will_fail
                        break
                
                async def connect_stdio(command, args):
                    if should_fail:
                        raise Exception(f"Failed to start {name}")
                    return True
                
                async def connect_websocket(url):
                    if should_fail:
                        raise Exception(f"Failed to connect to {name}")
                    return True
                
                async def connect_http(url):
                    if should_fail:
                        raise Exception(f"Failed to connect to {name}")
                    return True
                
                mock_client.connect_stdio = AsyncMock(side_effect=connect_stdio)
                mock_client.connect_websocket = AsyncMock(side_effect=connect_websocket)
                mock_client.connect_http = AsyncMock(side_effect=connect_http)
                mock_client.disconnect = AsyncMock()
                
                return mock_client
            
            mock_get_client.side_effect = create_mock_client
            
            # Execute: Connect all servers
            with patch('backend.mcp.server_manager.logger'):
                await manager.connect_all()
            
            # Verify: ServerManager state is valid
            # 1. All registered servers are still registered
            registered_servers = manager.get_servers()
            assert len(registered_servers) == len(server_configs), \
                "All servers should still be registered"
            
            # 2. Health status exists for all servers
            health_status = manager.get_all_health_status()
            assert len(health_status) == len(server_configs), \
                "Health status should exist for all servers"
            
            # 3. Health status reflects actual connection state
            for config, will_fail in server_configs:
                health = manager.get_server_health(config.name)
                assert health is not None, \
                    f"Health status should exist for {config.name}"
                assert health.is_healthy == (not will_fail), \
                    f"Health status for {config.name} should reflect connection state"
            
            # 4. Can query server status without errors
            summary = manager.get_health_summary()
            assert isinstance(summary, dict), \
                "Health summary should be a dictionary"
            assert "total_servers" in summary, \
                "Health summary should include total_servers"
            assert summary["total_servers"] == len(server_configs), \
                "Health summary should report correct total"
    
    @settings(max_examples=100, deadline=None)
    @seed(42)
    @given(
        server_configs=server_configs_list_generator()
    )
    @pytest.mark.asyncio
    async def test_system_does_not_crash_on_server_failures(self, server_configs):
        """
        Property: For any server failures, the system does not crash.
        
        # Feature: irisvoice-backend-integration, Property 42: MCP Server Startup Resilience
        **Validates: Requirements 16.7**
        """
        # Setup: Create fresh ServerManager instance
        ServerManager._instance = None
        ServerManager._initialized = False
        manager = ServerManager()
        
        # Register all servers
        for config, will_fail in server_configs:
            manager.register_server(config)
        
        # Mock the MCP client connections
        with patch('backend.mcp.server_manager.get_mcp_client') as mock_get_client:
            
            def create_mock_client(name, server_type):
                mock_client = Mock()
                
                # Find if this server should fail
                should_fail = False
                for config, will_fail in server_configs:
                    if config.name == name:
                        should_fail = will_fail
                        break
                
                async def connect_stdio(command, args):
                    if should_fail:
                        raise Exception(f"Failed to start {name}")
                    return True
                
                async def connect_websocket(url):
                    if should_fail:
                        raise Exception(f"Failed to connect to {name}")
                    return True
                
                async def connect_http(url):
                    if should_fail:
                        raise Exception(f"Failed to connect to {name}")
                    return True
                
                mock_client.connect_stdio = AsyncMock(side_effect=connect_stdio)
                mock_client.connect_websocket = AsyncMock(side_effect=connect_websocket)
                mock_client.connect_http = AsyncMock(side_effect=connect_http)
                mock_client.disconnect = AsyncMock()
                
                return mock_client
            
            mock_get_client.side_effect = create_mock_client
            
            # Execute: Connect all servers - should not raise exception
            with patch('backend.mcp.server_manager.logger'):
                try:
                    results = await manager.connect_all()
                    # Verify: Method completed without crashing
                    assert isinstance(results, dict), \
                        "connect_all should return a dictionary"
                except Exception as e:
                    pytest.fail(f"System crashed on server failures: {e}")
    
    @settings(max_examples=100, deadline=None)
    @seed(42)
    @given(
        server_configs=server_configs_list_generator()
    )
    @pytest.mark.asyncio
    async def test_health_status_tracks_failures(self, server_configs):
        """
        Property: For any server failure, health status tracks the failure.
        
        # Feature: irisvoice-backend-integration, Property 42: MCP Server Startup Resilience
        **Validates: Requirements 16.7**
        """
        # Setup: Create fresh ServerManager instance
        ServerManager._instance = None
        ServerManager._initialized = False
        manager = ServerManager()
        
        # Register all servers
        for config, will_fail in server_configs:
            manager.register_server(config)
        
        # Mock the MCP client connections
        with patch('backend.mcp.server_manager.get_mcp_client') as mock_get_client:
            
            def create_mock_client(name, server_type):
                mock_client = Mock()
                
                # Find if this server should fail
                should_fail = False
                for config, will_fail in server_configs:
                    if config.name == name:
                        should_fail = will_fail
                        break
                
                async def connect_stdio(command, args):
                    if should_fail:
                        raise Exception(f"Failed to start {name}")
                    return True
                
                async def connect_websocket(url):
                    if should_fail:
                        raise Exception(f"Failed to connect to {name}")
                    return True
                
                async def connect_http(url):
                    if should_fail:
                        raise Exception(f"Failed to connect to {name}")
                    return True
                
                mock_client.connect_stdio = AsyncMock(side_effect=connect_stdio)
                mock_client.connect_websocket = AsyncMock(side_effect=connect_websocket)
                mock_client.connect_http = AsyncMock(side_effect=connect_http)
                mock_client.disconnect = AsyncMock()
                
                return mock_client
            
            mock_get_client.side_effect = create_mock_client
            
            # Execute: Connect all servers
            with patch('backend.mcp.server_manager.logger'):
                await manager.connect_all()
            
            # Verify: Health status tracks failures
            for config, will_fail in server_configs:
                health = manager.get_server_health(config.name)
                assert health is not None, \
                    f"Health status should exist for {config.name}"
                
                if will_fail:
                    assert not health.is_healthy, \
                        f"Failed server {config.name} should be marked unhealthy"
                    assert health.consecutive_failures >= 1, \
                        f"Failed server {config.name} should have failure count"
                    assert health.error_message is not None, \
                        f"Failed server {config.name} should have error message"
                else:
                    assert health.is_healthy, \
                        f"Successful server {config.name} should be marked healthy"
                    assert health.consecutive_failures == 0, \
                        f"Successful server {config.name} should have no failures"
    
    @settings(max_examples=100, deadline=None)
    @seed(42)
    @given(
        server_configs=server_configs_list_generator()
    )
    @pytest.mark.asyncio
    async def test_can_query_tools_from_successful_servers_after_failures(
        self, server_configs
    ):
        """
        Property: For any server failures, can still query tools from successful servers.
        
        # Feature: irisvoice-backend-integration, Property 42: MCP Server Startup Resilience
        **Validates: Requirements 16.7**
        """
        # Setup: Create fresh ServerManager instance
        ServerManager._instance = None
        ServerManager._initialized = False
        manager = ServerManager()
        
        # Register all servers
        for config, will_fail in server_configs:
            manager.register_server(config)
        
        # Mock the MCP client connections
        with patch('backend.mcp.server_manager.get_mcp_client') as mock_get_client:
            
            def create_mock_client(name, server_type):
                mock_client = Mock()
                
                # Find if this server should fail
                should_fail = False
                for config, will_fail in server_configs:
                    if config.name == name:
                        should_fail = will_fail
                        break
                
                async def connect_stdio(command, args):
                    if should_fail:
                        raise Exception(f"Failed to start {name}")
                    return True
                
                async def connect_websocket(url):
                    if should_fail:
                        raise Exception(f"Failed to connect to {name}")
                    return True
                
                async def connect_http(url):
                    if should_fail:
                        raise Exception(f"Failed to connect to {name}")
                    return True
                
                # Mock tool listing for successful servers
                mock_tool = Mock()
                mock_tool.to_dict.return_value = {
                    "name": f"tool_{name}",
                    "description": f"Tool from {name}"
                }
                mock_client.get_tools.return_value = [mock_tool] if not should_fail else []
                
                mock_client.connect_stdio = AsyncMock(side_effect=connect_stdio)
                mock_client.connect_websocket = AsyncMock(side_effect=connect_websocket)
                mock_client.connect_http = AsyncMock(side_effect=connect_http)
                mock_client.disconnect = AsyncMock()
                
                return mock_client
            
            mock_get_client.side_effect = create_mock_client
            
            # Execute: Connect all servers
            with patch('backend.mcp.server_manager.logger'):
                await manager.connect_all()
            
            # Verify: Can query tools from successful servers
            try:
                all_tools = manager.get_all_tools()
                assert isinstance(all_tools, list), \
                    "get_all_tools should return a list"
                
                # Should have tools from successful servers only
                expected_successes = [config.name for config, will_fail in server_configs if not will_fail]
                assert len(all_tools) == len(expected_successes), \
                    f"Should have tools from {len(expected_successes)} successful servers"
                
                # Each tool should have a server field
                for tool in all_tools:
                    assert "server" in tool, \
                        "Each tool should have a server field"
                    assert tool["server"] in expected_successes, \
                        f"Tool server {tool['server']} should be in successful servers"
            except Exception as e:
                pytest.fail(f"Failed to query tools after server failures: {e}")
