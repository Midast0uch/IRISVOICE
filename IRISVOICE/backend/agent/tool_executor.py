#!/usr/bin/env python3
"""
Tool Executor

This module provides a service for executing tools requested by the executor model,
with parameter validation, security checks, and proper result formatting.
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

from backend.core.input_validator import get_input_validator, InputValidator, ValidationResult
from backend.core.models import (
    ToolDefinition, ToolRequest, ToolResponse, ToolCategory,
    ExecutionContext, ValidationError as ModelValidationError
)

logger = logging.getLogger(__name__)


# Re-export ToolCategory from models for backward compatibility
ToolCategory = ToolCategory


@dataclass
class ToolSpec:
    """Specification for a tool."""
    name: str
    description: str
    category: ToolCategory
    parameters: Dict[str, Any]  # JSON Schema
    required_params: List[str] = field(default_factory=list)
    handler: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Any]] = None
    async_handler: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Any]] = None
    
    def to_definition(self) -> ToolDefinition:
        """Convert ToolSpec to Pydantic ToolDefinition."""
        from backend.core.models import ToolParameter
        
        properties = self.parameters.get("properties", {})
        parameters = []
        
        for param_name, param_spec in properties.items():
            param = ToolParameter(
                name=param_name,
                type=param_spec.get("type", "string"),
                description=param_spec.get("description", ""),
                required=param_name in self.required_params,
                default=param_spec.get("default"),
                enum=param_spec.get("enum"),
                min_length=param_spec.get("minLength"),
                max_length=param_spec.get("maxLength"),
                pattern=param_spec.get("pattern"),
                minimum=param_spec.get("minimum"),
                maximum=param_spec.get("maximum")
            )
            parameters.append(param)
        
        return ToolDefinition(
            name=self.name,
            description=self.description,
            category=self.category,
            parameters=parameters,
            required_params=self.required_params
        )


@dataclass
class ExecutionResult:
    """Result of tool execution."""
    success: bool
    output: Any
    error: Optional[str] = None
    execution_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_response(self, tool_name: str, request_id: Optional[str] = None) -> ToolResponse:
        """Convert ExecutionResult to Pydantic ToolResponse."""
        return ToolResponse(
            success=self.success,
            tool_name=tool_name,
            output=self.output,
            error=self.error,
            execution_time_ms=self.execution_time * 1000,
            request_id=request_id,
            metadata=self.metadata
        )


class ToolExecutor:
    """Executes tools with validation and security checks."""

    _instance: Optional['ToolExecutor'] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        self._tools: Dict[str, ToolSpec] = {}
        self._execution_history: List[Dict[str, Any]] = []
        self._max_history = 100
        self._input_validator: InputValidator = get_input_validator()
        self._initialized = True
        self._register_builtin_tools()

    def _register_builtin_tools(self):
        """Register all built-in tools."""
        # File Management Tools
        self.register_tool(
            name="read_file",
            description="Read contents of a file",
            category=ToolCategory.FILE_MANAGEMENT,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"}
                },
                "required": ["path"]
            },
            required_params=["path"],
            handler=self._read_file
        )

        self.register_tool(
            name="write_file",
            description="Write contents to a file",
            category=ToolCategory.FILE_MANAGEMENT,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Content to write"}
                },
                "required": ["path", "content"]
            },
            required_params=["path", "content"],
            handler=self._write_file
        )

        self.register_tool(
            name="list_directory",
            description="List contents of a directory",
            category=ToolCategory.FILE_MANAGEMENT,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path"},
                    "recursive": {"type": "boolean", "description": "List recursively", "default": False}
                },
                "required": ["path"]
            },
            required_params=["path"],
            handler=self._list_directory
        )

        self.register_tool(
            name="create_directory",
            description="Create a new directory",
            category=ToolCategory.FILE_MANAGEMENT,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to create"}
                },
                "required": ["path"]
            },
            required_params=["path"],
            handler=self._create_directory
        )

        self.register_tool(
            name="delete_file",
            description="Delete a file or directory",
            category=ToolCategory.FILE_MANAGEMENT,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to delete"}
                },
                "required": ["path"]
            },
            required_params=["path"],
            handler=self._delete_file
        )

        # Browser Tools
        self.register_tool(
            name="open_url",
            description="Open a URL in the default browser",
            category=ToolCategory.BROWSER,
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to open"}
                },
                "required": ["url"]
            },
            required_params=["url"],
            handler=self._open_url
        )

        self.register_tool(
            name="search",
            description="Search using default search engine",
            category=ToolCategory.BROWSER,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"]
            },
            required_params=["query"],
            handler=self._search
        )

        # App Launcher Tools
        self.register_tool(
            name="launch_app",
            description="Launch an application by name",
            category=ToolCategory.APP_LAUNCHER,
            parameters={
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "Application name"}
                },
                "required": ["app_name"]
            },
            required_params=["app_name"],
            handler=self._launch_app
        )

        self.register_tool(
            name="open_file",
            description="Open a file with its default application",
            category=ToolCategory.APP_LAUNCHER,
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to file"}
                },
                "required": ["file_path"]
            },
            required_params=["file_path"],
            handler=self._open_file
        )

        # System Tools
        self.register_tool(
            name="get_system_info",
            description="Get system information",
            category=ToolCategory.SYSTEM,
            parameters={
                "type": "object",
                "properties": {}
            },
            required_params=[],
            handler=self._get_system_info
        )

        self.register_tool(
            name="lock",
            description="Lock the screen",
            category=ToolCategory.SYSTEM,
            parameters={
                "type": "object",
                "properties": {}
            },
            required_params=[],
            handler=self._lock_screen
        )

    def register_tool(
        self,
        name: str,
        description: str,
        category: ToolCategory,
        parameters: Dict[str, Any],
        required_params: List[str],
        handler: Optional[Callable] = None,
        async_handler: Optional[Callable] = None
    ):
        """
        Register a new tool with JSON Schema validation.
        
        Args:
            name: Tool name
            description: Tool description
            category: Tool category
            parameters: JSON Schema for parameters
            required_params: List of required parameter names
            handler: Synchronous handler function
            async_handler: Asynchronous handler function
        """
        tool_spec = ToolSpec(
            name=name,
            description=description,
            category=category,
            parameters=parameters,
            required_params=required_params,
            handler=handler,
            async_handler=async_handler
        )
        self._tools[name] = tool_spec
        
        # Register schema with input validator for JSON Schema validation
        try:
            schema = {
                "type": "object",
                "properties": parameters.get("properties", {}),
                "required": required_params
            }
            self._input_validator.register_schema(f"tool:{name}", schema)
            logger.info(f"[ToolExecutor] Registered tool with validation: {name}")
        except Exception as e:
            logger.warning(f"[ToolExecutor] Failed to register validation schema for {name}: {e}")

    def get_tool(self, name: str) -> Optional[ToolSpec]:
        """Get a tool specification by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[Dict[str, Any]]:
        """List all available tools."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "category": tool.category.value,
                "parameters": tool.parameters
            }
            for tool in self._tools.values()
        ]

    def validate_parameters(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        sanitize: bool = True
    ) -> tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Validate parameters against tool specification using JSON Schema.
        
        Args:
            tool_name: Name of the tool
            parameters: Parameters to validate
            sanitize: Whether to sanitize string inputs
            
        Returns:
            Tuple of (valid: bool, error_message: str, sanitized_params: dict)
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return False, f"Tool '{tool_name}' not found", None

        # Check required parameters (fast path)
        for req_param in tool.required_params:
            if req_param not in parameters or parameters[req_param] is None:
                return False, f"Missing required parameter: {req_param}", None

        # JSON Schema validation with InputValidator
        try:
            result = self._input_validator.validate(
                data=parameters,
                schema_name=f"tool:{tool_name}",
                sanitize=sanitize
            )
            
            if not result.is_valid:
                error_msg = "; ".join(result.get_error_messages())
                return False, error_msg, None
            
            # Return sanitized parameters if sanitization was performed
            sanitized = result.sanitized_data if sanitize else parameters
            return True, None, sanitized
            
        except Exception as e:
            logger.error(f"[ToolExecutor] Validation error for {tool_name}: {e}")
            # Fall back to basic validation
            return True, None, parameters

    async def execute(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None
    ) -> ExecutionResult:
        """
        Execute a tool with given parameters.
        
        Args:
            tool_name: Name of the tool to execute
            parameters: Tool parameters (will be validated and sanitized)
            context: Execution context
            request_id: Optional request ID for tracking
            
        Returns:
            ExecutionResult with success status, output, and metadata
        """
        start_time = time.time()

        # Get tool specification
        tool = self.get_tool(tool_name)
        if not tool:
            return ExecutionResult(
                success=False,
                output=None,
                error=f"Tool '{tool_name}' not found",
                execution_time=time.time() - start_time
            )

        # Validate parameters with JSON Schema validation and sanitization
        valid, error, sanitized_params = self.validate_parameters(tool_name, parameters, sanitize=True)
        if not valid:
            return ExecutionResult(
                success=False,
                output=None,
                error=error,
                execution_time=time.time() - start_time
            )

        # Use sanitized parameters for execution
        params_to_use = sanitized_params if sanitized_params is not None else parameters

        # Execute the tool
        try:
            if tool.async_handler:
                output = await tool.async_handler(params_to_use, context or {})
            elif tool.handler:
                if asyncio.iscoroutinefunction(tool.handler):
                    output = await tool.handler(params_to_use, context or {})
                else:
                    output = tool.handler(params_to_use, context or {})
            else:
                output = {"message": f"Tool '{tool_name}' has no handler"}

            execution_time = time.time() - start_time

            # Record execution
            self._record_execution(tool_name, parameters, output, True, execution_time)

            return ExecutionResult(
                success=True,
                output=output,
                execution_time=execution_time
            )

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Error executing tool '{tool_name}': {str(e)}"
            logger.error(f"[ToolExecutor] {error_msg}")

            self._record_execution(tool_name, parameters, str(e), False, execution_time)

            return ExecutionResult(
                success=False,
                output=None,
                error=error_msg,
                execution_time=execution_time
            )

    async def execute_request(self, request: ToolRequest) -> ToolResponse:
        """
        Execute a tool using a Pydantic ToolRequest model.
        
        Args:
            request: ToolRequest with tool_name, parameters, and context
            
        Returns:
            ToolResponse with execution results
        """
        result = await self.execute(
            tool_name=request.tool_name,
            parameters=request.parameters,
            context=request.context,
            request_id=request.request_id
        )
        
        return result.to_response(
            tool_name=request.tool_name,
            request_id=request.request_id
        )

    def _record_execution(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        output: Any,
        success: bool,
        execution_time: float
    ) -> None:
        """Record tool execution in history."""
        record: Dict[str, Any] = {
            "tool_name": tool_name,
            "parameters": parameters,
            "output": str(output)[:500],  # Truncate long outputs
            "success": success,
            "execution_time": execution_time,
            "timestamp": datetime.now().isoformat()
        }
        self._execution_history.append(record)

        if len(self._execution_history) > self._max_history:
            self._execution_history = self._execution_history[-self._max_history:]

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get execution history."""
        return self._execution_history[-limit:]

    def get_statistics(self) -> Dict[str, Any]:
        """Get execution statistics."""
        if not self._execution_history:
            return {"total_executions": 0}

        total = len(self._execution_history)
        successful = sum(1 for e in self._execution_history if e["success"])
        failed = total - successful

        return {
            "total_executions": total,
            "successful": successful,
            "failed": failed,
            "success_rate": (successful / total * 100) if total > 0 else 0,
            "tools_used": list(set(e["tool_name"] for e in self._execution_history))
        }

    # Built-in tool implementations
    def _read_file(self, params: Dict, context: Dict) -> Dict[str, Any]:
        """Read a file."""
        import os
        path = params.get("path", "")
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            return {"success": True, "content": content, "path": path, "bytes": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e), "path": path}

    def _write_file(self, params: Dict, context: Dict) -> Dict[str, Any]:
        """Write to a file."""
        import os
        path = params.get("path", "")
        content = params.get("content", "")
        try:
            os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"success": True, "message": f"Written to {path}", "bytes": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _list_directory(self, params: Dict, context: Dict) -> Dict[str, Any]:
        """List directory contents."""
        from pathlib import Path
        path = params.get("path", ".")
        recursive = params.get("recursive", False)
        try:
            items = []
            p = Path(path)
            if recursive:
                for item in p.rglob("*"):
                    items.append({
                        "name": item.name,
                        "path": str(item),
                        "type": "directory" if item.is_dir() else "file"
                    })
            else:
                for item in p.iterdir():
                    items.append({
                        "name": item.name,
                        "path": str(item),
                        "type": "directory" if item.is_dir() else "file"
                    })
            return {"success": True, "items": items, "path": path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _create_directory(self, params: Dict, context: Dict) -> Dict[str, Any]:
        """Create a directory."""
        from pathlib import Path
        path = params.get("path", "")
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            return {"success": True, "message": f"Created directory {path}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _delete_file(self, params: Dict, context: Dict) -> Dict[str, Any]:
        """Delete a file or directory."""
        from pathlib import Path
        import shutil
        path = params.get("path", "")
        try:
            p = Path(path)
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            return {"success": True, "message": f"Deleted {path}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _open_url(self, params: Dict, context: Dict) -> Dict[str, Any]:
        """Open a URL in browser."""
        import webbrowser
        url = params.get("url", "")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            webbrowser.open(url)
            return {"success": True, "message": f"Opened {url}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _search(self, params: Dict, context: Dict) -> Dict[str, Any]:
        """Search using default search engine."""
        import webbrowser
        query = params.get("query", "")
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        try:
            webbrowser.open(url)
            return {"success": True, "message": f"Searched for: {query}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _launch_app(self, params: Dict, context: Dict) -> Dict[str, Any]:
        """Launch an application."""
        import subprocess
        import os
        app_name = params.get("app_name", "")
        try:
            if os.name == "nt":
                subprocess.Popen(["cmd", "/c", "start", "", app_name])
            else:
                subprocess.Popen([app_name])
            return {"success": True, "message": f"Launched {app_name}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _open_file(self, params: Dict, context: Dict) -> Dict[str, Any]:
        """Open a file with default application."""
        import os
        file_path = params.get("file_path", "")
        try:
            if os.name == "nt":
                os.startfile(file_path)
            return {"success": True, "message": f"Opened {file_path}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _get_system_info(self, params: Dict, context: Dict) -> Dict[str, Any]:
        """Get system information."""
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

    def _lock_screen(self, params: Dict, context: Dict) -> Dict[str, Any]:
        """Lock the screen."""
        import subprocess
        import os
        try:
            if os.name == "nt":
                subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"])
            elif hasattr(os, "uname") and os.uname().sysname == "Darwin":
                subprocess.run(["/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession", "-suspend"])
            else:
                # Linux — try loginctl first (systemd), fall back to gnome-screensaver
                import shutil
                if shutil.which("loginctl"):
                    subprocess.run(["loginctl", "lock-session"])
                else:
                    subprocess.run(["gnome-screensaver-command", "-l"])
            return {"success": True, "message": "Screen locked"}
        except Exception as e:
            return {"success": False, "error": str(e)}


# Singleton accessor
_tool_executor: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    """Get the singleton ToolExecutor instance."""
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ToolExecutor()
    return _tool_executor
