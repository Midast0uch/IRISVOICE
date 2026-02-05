"""
MCP Protocol - Model Context Protocol message types and JSON-RPC implementation
Based on MCP specification
"""
from typing import Any, Dict, List, Optional, Callable
from enum import Enum
import json
import uuid


class MCPMessageType(str, Enum):
    """MCP message types"""
    INITIALIZE = "initialize"
    INITIALIZED = "initialized"
    TOOLS_LIST = "tools/list"
    TOOLS_CALL = "tools/call"
    TOOLS_RESULT = "tools/result"
    RESOURCES_LIST = "resources/list"
    RESOURCES_READ = "resources/read"
    PROMPTS_LIST = "prompts/list"
    PROMPTS_GET = "prompts/get"
    PING = "ping"
    NOTIFICATION = "notification"


class MCPErrorCode(int, Enum):
    """MCP error codes"""
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    SERVER_ERROR = -32000


class MCPMessage:
    """Base MCP JSON-RPC message"""
    
    def __init__(self, jsonrpc: str = "2.0"):
        self.jsonrpc = jsonrpc
    
    def to_dict(self) -> Dict[str, Any]:
        return {"jsonrpc": self.jsonrpc}


class MCPRequest(MCPMessage):
    """MCP request message"""
    
    def __init__(self, method: str, params: Optional[Dict[str, Any]] = None, id: Optional[str] = None):
        super().__init__()
        self.id = id or str(uuid.uuid4())[:8]
        self.method = method
        self.params = params or {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "jsonrpc": self.jsonrpc,
            "id": self.id,
            "method": self.method,
            "params": self.params
        }


class MCPResponse(MCPMessage):
    """MCP response message"""
    
    def __init__(self, id: str, result: Optional[Any] = None, error: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.id = id
        self.result = result
        self.error = error
    
    def to_dict(self) -> Dict[str, Any]:
        data = {
            "jsonrpc": self.jsonrpc,
            "id": self.id
        }
        if self.error:
            data["error"] = self.error
        else:
            data["result"] = self.result
        return data


class MCPTool:
    """MCP Tool definition"""
    
    def __init__(self, name: str, description: str, input_schema: Dict[str, Any]):
        self.name = name
        self.description = description
        self.input_schema = input_schema
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MCPTool':
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            input_schema=data.get("inputSchema", {})
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema
        }


class MCPResource:
    """MCP Resource definition"""
    
    def __init__(self, uri: str, name: str, mime_type: Optional[str] = None):
        self.uri = uri
        self.name = name
        self.mime_type = mime_type
    
    def to_dict(self) -> Dict[str, Any]:
        data = {
            "uri": self.uri,
            "name": self.name
        }
        if self.mime_type:
            data["mimeType"] = self.mime_type
        return data


class MCPPrompt:
    """MCP Prompt definition"""
    
    def __init__(self, name: str, description: Optional[str] = None, arguments: Optional[List[Dict[str, Any]]] = None):
        self.name = name
        self.description = description
        self.arguments = arguments or []
    
    def to_dict(self) -> Dict[str, Any]:
        data = {"name": self.name}
        if self.description:
            data["description"] = self.description
        if self.arguments:
            data["arguments"] = self.arguments
        return data


def parse_mcp_message(data: str) -> Optional[MCPMessage]:
    """Parse JSON string to MCP message"""
    try:
        parsed = json.loads(data)
        
        if "method" in parsed:
            # It's a request
            return MCPRequest(
                method=parsed["method"],
                params=parsed.get("params"),
                id=parsed.get("id")
            )
        elif "id" in parsed:
            # It's a response
            return MCPResponse(
                id=parsed["id"],
                result=parsed.get("result"),
                error=parsed.get("error")
            )
        else:
            return None
    except json.JSONDecodeError:
        return None


def create_error_response(id: str, code: int, message: str) -> MCPResponse:
    """Create an error response"""
    return MCPResponse(
        id=id,
        error={
            "code": code,
            "message": message
        }
    )


def create_tools_list_request(id: Optional[str] = None) -> MCPRequest:
    """Create a tools/list request"""
    return MCPRequest(
        method=MCPMessageType.TOOLS_LIST,
        id=id
    )


def create_tools_call_request(name: str, arguments: Dict[str, Any], id: Optional[str] = None) -> MCPRequest:
    """Create a tools/call request"""
    return MCPRequest(
        method=MCPMessageType.TOOLS_CALL,
        params={
            "name": name,
            "arguments": arguments
        },
        id=id
    )


def create_initialize_request(client_name: str = "IRIS", protocol_version: str = "2024-11-05") -> MCPRequest:
    """Create an initialize request"""
    return MCPRequest(
        method=MCPMessageType.INITIALIZE,
        params={
            "protocolVersion": protocol_version,
            "capabilities": {
                "tools": {},
                "resources": {},
                "prompts": {}
            },
            "clientInfo": {
                "name": client_name,
                "version": "1.0.0"
            }
        }
    )
