"""
Server Manager - Manages MCP server connections and lifecycle
"""
import asyncio
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

from .client import MCPClient, get_mcp_client


@dataclass
class ServerConfig:
    """MCP server configuration"""
    name: str
    type: str  # "stdio", "websocket", "http"
    command: Optional[str] = None
    args: Optional[List[str]] = None
    url: Optional[str] = None
    enabled: bool = True
    health_check_interval: int = 60  # seconds
    max_restart_attempts: int = 3
    restart_delay: int = 5  # seconds


@dataclass
class ServerHealth:
    """Server health status"""
    name: str
    is_healthy: bool
    last_check: datetime
    consecutive_failures: int = 0
    restart_attempts: int = 0
    last_restart: Optional[datetime] = None
    error_message: Optional[str] = None


class ServerManager:
    """
    Manages multiple MCP server connections
    - Built-in servers (Browser, App Launcher, System, File Manager, GUIAutomation)
    - External servers via stdio/WebSocket/HTTP
    - Health monitoring and automatic restart
    """
    
    _instance: Optional['ServerManager'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if ServerManager._initialized:
            return
        
        self._servers: Dict[str, ServerConfig] = {}
        self._clients: Dict[str, MCPClient] = {}
        self._connected: Dict[str, bool] = {}
        self._health_status: Dict[str, ServerHealth] = {}
        self._health_check_tasks: Dict[str, asyncio.Task] = {}
        self._shutdown_event = asyncio.Event()
        
        ServerManager._initialized = True
    
    def register_server(self, config: ServerConfig) -> None:
        """Register a server configuration"""
        self._servers[config.name] = config
        logger.info(f"[ServerManager] Registered server: {config.name} ({config.type})")
    
    def get_servers(self) -> List[ServerConfig]:
        """Get all registered servers"""
        return list(self._servers.values())
    
    def get_server(self, name: str) -> Optional[ServerConfig]:
        """Get server by name"""
        return self._servers.get(name)
    
    async def connect_server(self, name: str) -> bool:
        """Connect to a registered server"""
        config = self._servers.get(name)
        if not config:
            logger.warning(f"[ServerManager] Unknown server: {name}")
            return False
        
        if not config.enabled:
            logger.info(f"[ServerManager] Server {name} is disabled")
            return False
        
        # Create client
        client = get_mcp_client(name, config.type)
        self._clients[name] = client
        
        # Connect based on type
        success = False
        error_message = None
        try:
            if config.type == "stdio" and config.command:
                success = await client.connect_stdio(config.command, config.args)
            elif config.type == "websocket" and config.url:
                success = await client.connect_websocket(config.url)
            elif config.type == "http" and config.url:
                success = await client.connect_http(config.url)
        except Exception as e:
            error_message = str(e)
            logger.error(f"[ServerManager] Error connecting to {name}: {e}")
            success = False
        
        self._connected[name] = success
        
        # Initialize health status
        self._health_status[name] = ServerHealth(
            name=name,
            is_healthy=success,
            last_check=datetime.now(),
            consecutive_failures=0 if success else 1,
            error_message=error_message
        )
        
        if success:
            logger.info(f"[ServerManager] Connected to {name}")
            # Start health monitoring
            await self._start_health_monitoring(name)
        else:
            logger.error(f"[ServerManager] Failed to connect to {name}: {error_message}")
        
        return success
    
    async def connect_all(self) -> Dict[str, bool]:
        """Connect to all enabled servers"""
        results = {}
        for name, config in self._servers.items():
            if config.enabled:
                results[name] = await self.connect_server(name)
        return results
    
    async def disconnect_server(self, name: str) -> None:
        """Disconnect from a server"""
        client = self._clients.get(name)
        if client:
            await client.disconnect()
            self._connected[name] = False
            logger.info(f"[ServerManager] Disconnected from {name}")
    
    async def disconnect_all(self) -> None:
        """Disconnect from all servers"""
        for name in list(self._clients.keys()):
            await self.disconnect_server(name)
    
    def is_connected(self, name: str) -> bool:
        """Check if server is connected"""
        return self._connected.get(name, False)
    
    def get_connected_servers(self) -> List[str]:
        """Get list of connected server names"""
        return [name for name, connected in self._connected.items() if connected]
    
    def get_client(self, name: str) -> Optional[MCPClient]:
        """Get MCP client for a server"""
        return self._clients.get(name)
    
    def get_all_tools(self) -> List[Dict]:
        """Get all tools from all connected servers"""
        all_tools = []
        for name, client in self._clients.items():
            if self._connected.get(name, False):
                tools = client.get_tools()
                for tool in tools:
                    tool_dict = tool.to_dict()
                    tool_dict["server"] = name
                    all_tools.append(tool_dict)
        return all_tools
    
    async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> Optional[dict]:
        """Call a tool on a specific server"""
        client = self._clients.get(server_name)
        if not client or not self._connected.get(server_name, False):
            logger.error(f"[ServerManager] Server {server_name} not connected")
            return None
        
        return await client.call_tool(tool_name, arguments)

    def stop_all_servers(self) -> None:
        """Stop all servers and cleanup resources"""
        logger.info("[ServerManager] Stopping all servers...")
        # Signal shutdown
        self._shutdown_event.set()
        # Cancel all health check tasks
        for task in self._health_check_tasks.values():
            if not task.done():
                task.cancel()
        # Disconnect from all servers
        asyncio.create_task(self.disconnect_all())
        logger.info("[ServerManager] All servers stopped")
    
    async def _start_health_monitoring(self, name: str):
        """Start health monitoring for a server"""
        config = self._servers.get(name)
        if not config:
            return
        
        # Cancel existing health check task if any
        if name in self._health_check_tasks:
            self._health_check_tasks[name].cancel()
        
        # Start new health check task
        task = asyncio.create_task(self._health_check_loop(name, config.health_check_interval))
        self._health_check_tasks[name] = task
        logger.info(f"[ServerManager] Started health monitoring for {name}")
    
    async def _health_check_loop(self, name: str, interval: int):
        """Health check loop for a server"""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(interval)
                await self._check_server_health(name)
            except asyncio.CancelledError:
                logger.info(f"[ServerManager] Health check cancelled for {name}")
                break
            except Exception as e:
                logger.error(f"[ServerManager] Health check error for {name}: {e}")
    
    async def _check_server_health(self, name: str):
        """Check health of a server"""
        client = self._clients.get(name)
        config = self._servers.get(name)
        health = self._health_status.get(name)
        
        if not client or not config or not health:
            return
        
        # Try to list tools as a health check
        is_healthy = False
        error_message = None
        try:
            tools = await client.list_tools()
            is_healthy = len(tools) >= 0  # Success if we can list tools
        except Exception as e:
            error_message = str(e)
            logger.warning(f"[ServerManager] Health check failed for {name}: {e}")
        
        # Update health status
        health.last_check = datetime.now()
        health.is_healthy = is_healthy
        health.error_message = error_message
        
        if is_healthy:
            health.consecutive_failures = 0
            self._connected[name] = True
        else:
            health.consecutive_failures += 1
            self._connected[name] = False
            
            # Attempt restart if failures exceed threshold
            if health.consecutive_failures >= 3 and health.restart_attempts < config.max_restart_attempts:
                logger.warning(f"[ServerManager] Server {name} unhealthy, attempting restart...")
                await self._restart_server(name)
    
    async def _restart_server(self, name: str):
        """Restart a failed server"""
        config = self._servers.get(name)
        health = self._health_status.get(name)
        
        if not config or not health:
            return
        
        # Increment restart attempts
        health.restart_attempts += 1
        health.last_restart = datetime.now()
        
        logger.info(f"[ServerManager] Restarting {name} (attempt {health.restart_attempts}/{config.max_restart_attempts})")
        
        # Disconnect first
        await self.disconnect_server(name)
        
        # Wait before reconnecting
        await asyncio.sleep(config.restart_delay)
        
        # Reconnect
        success = await self.connect_server(name)
        
        if success:
            logger.info(f"[ServerManager] Successfully restarted {name}")
            health.consecutive_failures = 0
        else:
            logger.error(f"[ServerManager] Failed to restart {name}")
            
            # If max restart attempts reached, log error and continue
            if health.restart_attempts >= config.max_restart_attempts:
                logger.error(f"[ServerManager] Max restart attempts reached for {name}, giving up")
    
    def get_server_health(self, name: str) -> Optional[ServerHealth]:
        """Get health status for a server"""
        return self._health_status.get(name)
    
    def get_all_health_status(self) -> Dict[str, ServerHealth]:
        """Get health status for all servers"""
        return self._health_status.copy()
    
    def get_health_summary(self) -> Dict[str, any]:
        """Get summary of server health"""
        total = len(self._health_status)
        healthy = sum(1 for h in self._health_status.values() if h.is_healthy)
        unhealthy = total - healthy
        
        return {
            "total_servers": total,
            "healthy": healthy,
            "unhealthy": unhealthy,
            "servers": {
                name: {
                    "is_healthy": health.is_healthy,
                    "consecutive_failures": health.consecutive_failures,
                    "restart_attempts": health.restart_attempts,
                    "last_check": health.last_check.isoformat() if health.last_check else None,
                    "error_message": health.error_message
                }
                for name, health in self._health_status.items()
            }
        }


def get_server_manager() -> ServerManager:
    """Get the singleton ServerManager instance"""
    return ServerManager()
