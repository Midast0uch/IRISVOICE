"""
MCP Client - Manages connection to MCP servers
"""
import asyncio
import json
from typing import Any, Dict, List, Optional, Callable
import httpx
import websockets

from .protocol import (
    MCPRequest, MCPResponse, MCPTool, MCPResource, MCPPrompt,
    create_initialize_request, create_tools_list_request, create_tools_call_request,
    parse_mcp_message, MCPMessageType
)


class MCPClient:
    """
    Client for connecting to MCP servers via stdio, HTTP, or WebSocket
    """
    
    def __init__(self, server_name: str, connection_type: str = "stdio"):
        self.server_name = server_name
        self.connection_type = connection_type
        
        # Connection state
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._process: Optional[asyncio.subprocess.Process] = None
        
        # MCP state
        self._initialized = False
        self._tools: List[MCPTool] = []
        self._resources: List[MCPResource] = []
        self._prompts: List[MCPPrompt] = []
        
        # Pending requests
        self._pending_requests: Dict[str, asyncio.Future] = {}
    
    async def connect_stdio(self, command: str, args: List[str] = None) -> bool:
        """Connect to MCP server via stdio"""
        try:
            args = args or []
            self._process = await asyncio.create_subprocess_exec(
                command, *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            print(f"[MCPClient] Started {self.server_name} via stdio")
            
            # Start message reader
            asyncio.create_task(self._read_stdio_messages())
            
            # Initialize
            return await self._initialize()
            
        except Exception as e:
            print(f"[MCPClient] Failed to start {self.server_name}: {e}")
            return False
    
    async def connect_websocket(self, url: str) -> bool:
        """Connect to MCP server via WebSocket"""
        try:
            self._ws = await websockets.connect(url)
            print(f"[MCPClient] Connected to {self.server_name} via WebSocket")
            
            # Start message reader
            asyncio.create_task(self._read_ws_messages())
            
            # Initialize
            return await self._initialize()
            
        except Exception as e:
            print(f"[MCPClient] Failed to connect to {url}: {e}")
            return False
    
    async def connect_http(self, url: str) -> bool:
        """Connect to MCP server via HTTP"""
        try:
            self._http_client = httpx.AsyncClient(base_url=url)
            print(f"[MCPClient] Connected to {self.server_name} via HTTP")
            
            # Initialize
            return await self._initialize()
            
        except Exception as e:
            print(f"[MCPClient] Failed to connect to {url}: {e}")
            return False
    
    async def _initialize(self) -> bool:
        """Initialize MCP connection"""
        request = create_initialize_request()
        response = await self._send_request(request)
        
        if response and response.result:
            self._initialized = True
            print(f"[MCPClient] Initialized {self.server_name}")
            
            # Fetch tools
            await self.list_tools()
            return True
        
        return False
    
    async def _send_request(self, request: MCPRequest) -> Optional[MCPResponse]:
        """Send request and wait for response"""
        future = asyncio.Future()
        self._pending_requests[request.id] = future
        
        # Send based on connection type
        message = json.dumps(request.to_dict())
        
        if self.connection_type == "stdio" and self._process:
            self._process.stdin.write(message.encode() + b"\n")
            await self._process.stdin.drain()
            
        elif self.connection_type == "websocket" and self._ws:
            await self._ws.send(message)
            
        elif self.connection_type == "http" and self._http_client:
            response = await self._http_client.post(
                "/mcp",
                json=request.to_dict()
            )
            if response.status_code == 200:
                data = response.json()
                return MCPResponse(
                    id=data.get("id", request.id),
                    result=data.get("result"),
                    error=data.get("error")
                )
            return None
        
        # Wait for response (with timeout)
        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            print(f"[MCPClient] Request {request.id} timed out")
            self._pending_requests.pop(request.id, None)
            return None
    
    async def _read_stdio_messages(self):
        """Read messages from stdio"""
        while self._process and self._process.stdout:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    break
                
                message = parse_mcp_message(line.decode().strip())
                if message:
                    await self._handle_message(message)
                    
            except Exception as e:
                print(f"[MCPClient] stdio read error: {e}")
    
    async def _read_ws_messages(self):
        """Read messages from WebSocket"""
        while self._ws:
            try:
                message_str = await self._ws.recv()
                message = parse_mcp_message(message_str)
                if message:
                    await self._handle_message(message)
                    
            except websockets.exceptions.ConnectionClosed:
                print(f"[MCPClient] WebSocket closed")
                break
            except Exception as e:
                print(f"[MCPClient] WebSocket read error: {e}")
    
    async def _handle_message(self, message):
        """Handle incoming message"""
        if isinstance(message, MCPResponse):
            # Check if it's a response to a pending request
            future = self._pending_requests.pop(message.id, None)
            if future and not future.done():
                future.set_result(message)
    
    async def list_tools(self) -> List[MCPTool]:
        """List available tools from server"""
        if not self._initialized:
            return []
        
        request = create_tools_list_request()
        response = await self._send_request(request)
        
        if response and response.result and "tools" in response.result:
            self._tools = [MCPTool.from_dict(t) for t in response.result["tools"]]
            print(f"[MCPClient] {self.server_name} has {len(self._tools)} tools")
        
        return self._tools
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Call a tool on the server"""
        if not self._initialized:
            return None
        
        request = create_tools_call_request(name, arguments)
        response = await self._send_request(request)
        
        if response:
            if response.error:
                print(f"[MCPClient] Tool error: {response.error}")
                return None
            return response.result
        
        return None
    
    def get_tools(self) -> List[MCPTool]:
        """Get cached tools list"""
        return self._tools
    
    def get_tool(self, name: str) -> Optional[MCPTool]:
        """Get a specific tool by name"""
        for tool in self._tools:
            if tool.name == name:
                return tool
        return None
    
    async def disconnect(self):
        """Disconnect from server"""
        if self._ws:
            await self._ws.close()
            self._ws = None
        
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        
        if self._process:
            self._process.terminate()
            await self._process.wait()
            self._process = None
        
        self._initialized = False
        print(f"[MCPClient] Disconnected from {self.server_name}")


# Global client cache
_mcp_clients: Dict[str, MCPClient] = {}


def get_mcp_client(server_name: str, connection_type: str = "stdio") -> MCPClient:
    """Get or create MCP client for a server"""
    key = f"{server_name}_{connection_type}"
    if key not in _mcp_clients:
        _mcp_clients[key] = MCPClient(server_name, connection_type)
    return _mcp_clients[key]


async def disconnect_all_clients():
    """Disconnect all MCP clients"""
    for client in _mcp_clients.values():
        await client.disconnect()
    _mcp_clients.clear()
