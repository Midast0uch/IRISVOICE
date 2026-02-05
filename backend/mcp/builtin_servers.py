"""
Built-in MCP Servers - Local implementations of common tools
"""
import asyncio
import json
import os
import subprocess
import webbrowser
from typing import Any, Dict, List, Optional
from pathlib import Path

from .protocol import MCPRequest, MCPResponse, MCPTool, MCPMessageType


class BuiltinServer:
    """Base class for built-in MCP servers"""
    
    def __init__(self, name: str):
        self.name = name
        self._tools: List[MCPTool] = []
        self._setup_tools()
    
    def _setup_tools(self):
        """Override to define tools"""
        pass
    
    def get_tools(self) -> List[MCPTool]:
        """Get available tools"""
        return self._tools
    
    async def handle_request(self, request: MCPRequest) -> MCPResponse:
        """Handle MCP request"""
        if request.method == MCPMessageType.TOOLS_LIST:
            return MCPResponse(
                id=request.id,
                result={"tools": [t.to_dict() for t in self._tools]}
            )
        elif request.method == MCPMessageType.TOOLS_CALL:
            return await self._handle_tool_call(request)
        else:
            return MCPResponse(
                id=request.id,
                error={"code": -32601, "message": f"Method not found: {request.method}"}
            )
    
    async def _handle_tool_call(self, request: MCPRequest) -> MCPResponse:
        """Handle tool execution"""
        params = request.params or {}
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        result = await self.execute_tool(tool_name, arguments)
        
        return MCPResponse(
            id=request.id,
            result=result
        )
    
    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a tool - override in subclasses"""
        return {"error": "Not implemented"}


class BrowserServer(BuiltinServer):
    """Browser control MCP server"""
    
    def __init__(self):
        super().__init__("browser")
    
    def _setup_tools(self):
        self._tools = [
            MCPTool(
                name="open_url",
                description="Open a URL in the default browser",
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to open"}
                    },
                    "required": ["url"]
                }
            ),
            MCPTool(
                name="search",
                description="Search using default search engine",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"]
                }
            ),
            MCPTool(
                name="open_incognito",
                description="Open URL in incognito/private mode",
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to open"}
                    },
                    "required": ["url"]
                }
            )
        ]
    
    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if name == "open_url":
            url = arguments.get("url", "")
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            webbrowser.open(url)
            return {"success": True, "message": f"Opened {url}"}
        
        elif name == "search":
            query = arguments.get("query", "")
            # Use Google search
            url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            webbrowser.open(url)
            return {"success": True, "message": f"Searched for: {query}"}
        
        elif name == "open_incognito":
            url = arguments.get("url", "")
            # Note: incognito opening is browser-specific
            # This is a simplified version
            return {"success": False, "message": "Incognito mode not implemented for this browser"}
        
        return {"error": f"Unknown tool: {name}"}


class AppLauncherServer(BuiltinServer):
    """Application launcher MCP server"""
    
    def __init__(self):
        super().__init__("app_launcher")
    
    def _setup_tools(self):
        self._tools = [
            MCPTool(
                name="launch_app",
                description="Launch an application by name",
                input_schema={
                    "type": "object",
                    "properties": {
                        "app_name": {"type": "string", "description": "Application name"}
                    },
                    "required": ["app_name"]
                }
            ),
            MCPTool(
                name="open_file",
                description="Open a file with its default application",
                input_schema={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Path to file"}
                    },
                    "required": ["file_path"]
                }
            ),
            MCPTool(
                name="list_running_apps",
                description="List currently running applications",
                input_schema={"type": "object", "properties": {}}
            )
        ]
    
    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if name == "launch_app":
            app_name = arguments.get("app_name", "")
            try:
                if os.name == "nt":  # Windows
                    subprocess.Popen([app_name], shell=True)
                else:  # macOS/Linux
                    subprocess.Popen([app_name])
                return {"success": True, "message": f"Launched {app_name}"}
            except Exception as e:
                return {"success": False, "error": str(e)}
        
        elif name == "open_file":
            file_path = arguments.get("file_path", "")
            try:
                if os.name == "nt":
                    os.startfile(file_path)
                elif os.name == "posix":
                    subprocess.call(["open" if os.uname().sysname == "Darwin" else "xdg-open", file_path])
                return {"success": True, "message": f"Opened {file_path}"}
            except Exception as e:
                return {"success": False, "error": str(e)}
        
        elif name == "list_running_apps":
            # Platform-specific implementation would go here
            return {"success": True, "apps": ["Feature requires platform-specific implementation"]}
        
        return {"error": f"Unknown tool: {name}"}


class SystemServer(BuiltinServer):
    """System control MCP server"""
    
    def __init__(self):
        super().__init__("system")
    
    def _setup_tools(self):
        self._tools = [
            MCPTool(
                name="get_system_info",
                description="Get system information",
                input_schema={"type": "object", "properties": {}}
            ),
            MCPTool(
                name="shutdown",
                description="Shutdown the system",
                input_schema={
                    "type": "object",
                    "properties": {
                        "delay": {"type": "integer", "description": "Delay in seconds", "default": 0}
                    }
                }
            ),
            MCPTool(
                name="restart",
                description="Restart the system",
                input_schema={
                    "type": "object",
                    "properties": {
                        "delay": {"type": "integer", "description": "Delay in seconds", "default": 0}
                    }
                }
            ),
            MCPTool(
                name="sleep",
                description="Put system to sleep",
                input_schema={"type": "object", "properties": {}}
            ),
            MCPTool(
                name="lock",
                description="Lock the screen",
                input_schema={"type": "object", "properties": {}}
            )
        ]
    
    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if name == "get_system_info":
            import platform
            return {
                "success": True,
                "info": {
                    "platform": platform.system(),
                    "release": platform.release(),
                    "version": platform.version(),
                    "machine": platform.machine(),
                    "processor": platform.processor()
                }
            }
        
        elif name == "shutdown":
            delay = arguments.get("delay", 0)
            # Note: This requires elevated permissions
            try:
                if os.name == "nt":
                    subprocess.run(["shutdown", "/s", "/t", str(delay)])
                else:
                    subprocess.run(["shutdown", "-h", "+", str(delay)])
                return {"success": True, "message": f"Shutdown scheduled in {delay} seconds"}
            except Exception as e:
                return {"success": False, "error": str(e)}
        
        elif name == "restart":
            delay = arguments.get("delay", 0)
            try:
                if os.name == "nt":
                    subprocess.run(["shutdown", "/r", "/t", str(delay)])
                else:
                    subprocess.run(["shutdown", "-r", "+", str(delay)])
                return {"success": True, "message": f"Restart scheduled in {delay} seconds"}
            except Exception as e:
                return {"success": False, "error": str(e)}
        
        elif name == "sleep":
            try:
                if os.name == "nt":
                    subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
                elif os.uname().sysname == "Darwin":
                    subprocess.run(["pmset", "sleepnow"])
                else:
                    subprocess.run(["systemctl", "suspend"])
                return {"success": True, "message": "Sleep initiated"}
            except Exception as e:
                return {"success": False, "error": str(e)}
        
        elif name == "lock":
            try:
                if os.name == "nt":
                    subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"])
                elif os.uname().sysname == "Darwin":
                    subprocess.run(["/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession", "-suspend"])
                else:
                    subprocess.run(["gnome-screensaver-command", "-l"])
                return {"success": True, "message": "Screen locked"}
            except Exception as e:
                return {"success": False, "error": str(e)}
        
        return {"error": f"Unknown tool: {name}"}


class FileManagerServer(BuiltinServer):
    """File manager MCP server"""
    
    def __init__(self):
        super().__init__("file_manager")
    
    def _setup_tools(self):
        self._tools = [
            MCPTool(
                name="read_file",
                description="Read contents of a file",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path"}
                    },
                    "required": ["path"]
                }
            ),
            MCPTool(
                name="write_file",
                description="Write contents to a file",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path"},
                        "content": {"type": "string", "description": "Content to write"}
                    },
                    "required": ["path", "content"]
                }
            ),
            MCPTool(
                name="list_directory",
                description="List contents of a directory",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path"},
                        "recursive": {"type": "boolean", "description": "List recursively", "default": False}
                    },
                    "required": ["path"]
                }
            ),
            MCPTool(
                name="create_directory",
                description="Create a new directory",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path"}
                    },
                    "required": ["path"]
                }
            ),
            MCPTool(
                name="delete_file",
                description="Delete a file or directory",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to delete"}
                    },
                    "required": ["path"]
                }
            )
        ]
    
    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if name == "read_file":
            path = arguments.get("path", "")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                return {"success": True, "content": content, "path": path}
            except Exception as e:
                return {"success": False, "error": str(e), "path": path}
        
        elif name == "write_file":
            path = arguments.get("path", "")
            content = arguments.get("content", "")
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                return {"success": True, "message": f"Written to {path}", "bytes": len(content)}
            except Exception as e:
                return {"success": False, "error": str(e)}
        
        elif name == "list_directory":
            path = arguments.get("path", ".")
            recursive = arguments.get("recursive", False)
            try:
                items = []
                p = Path(path)
                if recursive:
                    for item in p.rglob("*"):
                        items.append({
                            "name": item.name,
                            "path": str(item),
                            "type": "directory" if item.is_dir() else "file",
                            "size": item.stat().st_size if item.is_file() else None
                        })
                else:
                    for item in p.iterdir():
                        items.append({
                            "name": item.name,
                            "path": str(item),
                            "type": "directory" if item.is_dir() else "file",
                            "size": item.stat().st_size if item.is_file() else None
                        })
                return {"success": True, "items": items, "path": path}
            except Exception as e:
                return {"success": False, "error": str(e)}
        
        elif name == "create_directory":
            path = arguments.get("path", "")
            try:
                Path(path).mkdir(parents=True, exist_ok=True)
                return {"success": True, "message": f"Created directory {path}"}
            except Exception as e:
                return {"success": False, "error": str(e)}
        
        elif name == "delete_file":
            path = arguments.get("path", "")
            try:
                p = Path(path)
                if p.is_dir():
                    import shutil
                    shutil.rmtree(p)
                else:
                    p.unlink()
                return {"success": True, "message": f"Deleted {path}"}
            except Exception as e:
                return {"success": False, "error": str(e)}
        
        return {"error": f"Unknown tool: {name}"}
