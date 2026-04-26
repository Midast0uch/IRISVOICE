"""
MCP Bridge - Connects Integration Lifecycle Manager to MCP ServerManager

This module bridges the Iris Integration Layer with the existing MCP infrastructure:
- Registers integration-based servers with ServerManager
- Routes tool calls to the correct integration server
- Handles stdio transport for external MCP servers
"""

import asyncio
import logging
from typing import Any, Dict, Optional

from ..mcp.server_manager import ServerManager, ServerConfig, get_server_manager
from ..mcp.client import MCPClient

logger = logging.getLogger(__name__)


class IntegrationMCPBridge:
    """
    Bridges integration-based MCP servers with the existing ServerManager.
    
    This acts as the "MCP Host" that the LifecycleManager expects,
    delegating to the existing MCP infrastructure.
    """
    
    def __init__(self, server_manager: Optional[ServerManager] = None):
        self.server_manager = server_manager or get_server_manager()
        self._integration_servers: Dict[str, Dict[str, Any]] = {}
        logger.info("IntegrationMCPBridge initialized")
    
    async def register_server(
        self,
        server_id: str,
        stdin: Any,
        stdout: Any,
    ) -> bool:
        """
        Register an integration's MCP server with the ServerManager.
        
        Args:
            server_id: The integration ID (e.g., "gmail", "telegram")
            stdin: Process stdin pipe
            stdout: Process stdout pipe
        
        Returns True if registration succeeded.
        """
        try:
            # Create a ServerConfig for stdio-based integration server
            config = ServerConfig(
                name=server_id,
                type="stdio",
                command=None,  # Process already spawned
                args=None,
                enabled=True,
                health_check_interval=30,
            )
            
            # Register with ServerManager
            self.server_manager.register_server(config)
            
            # Store reference to pipes for communication
            self._integration_servers[server_id] = {
                "stdin": stdin,
                "stdout": stdout,
                "registered_at": asyncio.get_event_loop().time(),
            }
            
            logger.info(f"[MCPBridge] Registered integration server: {server_id}")
            return True
            
        except Exception as e:
            logger.error(f"[MCPBridge] Failed to register server {server_id}: {e}")
            return False
    
    async def deregister_server(self, server_id: str) -> bool:
        """
        Deregister an integration server.
        
        Args:
            server_id: The integration ID
        
        Returns True if deregistration succeeded.
        """
        try:
            # Remove from tracking
            if server_id in self._integration_servers:
                del self._integration_servers[server_id]
            
            logger.info(f"[MCPBridge] Deregistered integration server: {server_id}")
            return True
            
        except Exception as e:
            logger.error(f"[MCPBridge] Failed to deregister server {server_id}: {e}")
            return False
    
    async def get_server_tools(self, server_id: str) -> list:
        """
        Get available tools for an integration server.
        
        Args:
            server_id: The integration ID
        
        Returns list of tool names.
        """
        try:
            # Get client from ServerManager
            client = self.server_manager._clients.get(server_id)
            if client and hasattr(client, 'tools'):
                return list(client.tools.keys())
            
            # If not connected yet, return empty list
            return []
            
        except Exception as e:
            logger.error(f"[MCPBridge] Failed to get tools for {server_id}: {e}")
            return []
    
    def is_server_registered(self, server_id: str) -> bool:
        """Check if an integration server is registered."""
        return server_id in self._integration_servers
    
    def get_server_pipes(self, server_id: str) -> Optional[Dict[str, Any]]:
        """Get the stdin/stdout pipes for a registered server."""
        return self._integration_servers.get(server_id)


# Singleton instance
_mcp_bridge: Optional[IntegrationMCPBridge] = None


def get_mcp_bridge(server_manager: Optional[ServerManager] = None) -> IntegrationMCPBridge:
    """Get or create the singleton MCP bridge."""
    global _mcp_bridge
    if _mcp_bridge is None:
        _mcp_bridge = IntegrationMCPBridge(server_manager)
    return _mcp_bridge


def reset_mcp_bridge() -> None:
    """Reset the singleton (for testing)."""
    global _mcp_bridge
    _mcp_bridge = None
