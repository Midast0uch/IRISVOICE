"""
Server Manager - Manages MCP server connections and lifecycle
"""
import asyncio
from typing import Dict, List, Optional
from dataclasses import dataclass

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


class ServerManager:
    """
    Manages multiple MCP server connections
    - Built-in servers (Browser, App Launcher, System, File Manager)
    - External servers via stdio/WebSocket/HTTP
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
        
        ServerManager._initialized = True
    
    def register_server(self, config: ServerConfig) -> None:
        """Register a server configuration"""
        self._servers[config.name] = config
        print(f"[ServerManager] Registered server: {config.name} ({config.type})")
    
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
            print(f"[ServerManager] Unknown server: {name}")
            return False
        
        if not config.enabled:
            print(f"[ServerManager] Server {name} is disabled")
            return False
        
        # Create client
        client = get_mcp_client(name, config.type)
        self._clients[name] = client
        
        # Connect based on type
        success = False
        if config.type == "stdio" and config.command:
            success = await client.connect_stdio(config.command, config.args)
        elif config.type == "websocket" and config.url:
            success = await client.connect_websocket(config.url)
        elif config.type == "http" and config.url:
            success = await client.connect_http(config.url)
        
        self._connected[name] = success
        
        if success:
            print(f"[ServerManager] Connected to {name}")
        else:
            print(f"[ServerManager] Failed to connect to {name}")
        
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
            print(f"[ServerManager] Disconnected from {name}")
    
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
            print(f"[ServerManager] Server {server_name} not connected")
            return None
        
        return await client.call_tool(tool_name, arguments)


def get_server_manager() -> ServerManager:
    """Get the singleton ServerManager instance"""
    return ServerManager()
