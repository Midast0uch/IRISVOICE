"""
Tool Registry - Manages tool execution and caching
"""
import asyncio
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class ToolExecution:
    """Record of a tool execution"""
    tool_name: str
    server_name: str
    arguments: Dict[str, Any]
    result: Any
    success: bool
    timestamp: float = field(default_factory=lambda: asyncio.get_event_loop().time())


class ToolRegistry:
    """
    Registry for managing tool discovery, caching, and execution history
    """
    
    _instance: Optional['ToolRegistry'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, max_history: int = 100):
        if ToolRegistry._initialized:
            return
        
        self._tool_cache: Dict[str, Dict] = {}  # tool_name -> tool_info
        self._execution_history: List[ToolExecution] = []
        self._max_history = max_history
        self._local_tools: Dict[str, Callable] = {}  # Local Python functions
        
        ToolRegistry._initialized = True
    
    def register_local_tool(self, name: str, func: Callable, description: str = "") -> None:
        """Register a local Python function as a tool"""
        self._local_tools[name] = func
        self._tool_cache[name] = {
            "name": name,
            "description": description or func.__doc__ or "",
            "local": True,
            "server": "local"
        }
        print(f"[ToolRegistry] Registered local tool: {name}")
    
    def update_tools(self, tools: List[Dict]) -> None:
        """Update tool cache from servers"""
        for tool in tools:
            self._tool_cache[tool["name"]] = tool
    
    def get_tool(self, name: str) -> Optional[Dict]:
        """Get tool by name"""
        return self._tool_cache.get(name)
    
    def get_all_tools(self) -> List[Dict]:
        """Get all registered tools"""
        return list(self._tool_cache.values())
    
    def get_tools_by_server(self, server_name: str) -> List[Dict]:
        """Get tools from a specific server"""
        return [t for t in self._tool_cache.values() if t.get("server") == server_name]
    
    def search_tools(self, query: str) -> List[Dict]:
        """Search tools by name or description"""
        query_lower = query.lower()
        results = []
        for tool in self._tool_cache.values():
            if (query_lower in tool.get("name", "").lower() or 
                query_lower in tool.get("description", "").lower()):
                results.append(tool)
        return results
    
    async def execute_local_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a local registered tool"""
        func = self._local_tools.get(name)
        if not func:
            return None
        
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(**arguments)
            else:
                return func(**arguments)
        except Exception as e:
            print(f"[ToolRegistry] Local tool error: {e}")
            return {"error": str(e)}
    
    def record_execution(self, tool_name: str, server_name: str, 
                         arguments: Dict[str, Any], result: Any, success: bool) -> None:
        """Record a tool execution"""
        execution = ToolExecution(
            tool_name=tool_name,
            server_name=server_name,
            arguments=arguments,
            result=result,
            success=success
        )
        self._execution_history.append(execution)
        
        # Trim history if needed
        if len(self._execution_history) > self._max_history:
            self._execution_history = self._execution_history[-self._max_history:]
    
    def get_execution_history(self, limit: int = 10) -> List[ToolExecution]:
        """Get recent tool execution history"""
        return self._execution_history[-limit:]
    
    def get_success_rate(self, tool_name: Optional[str] = None) -> float:
        """Get success rate for all tools or a specific tool"""
        if tool_name:
            executions = [e for e in self._execution_history if e.tool_name == tool_name]
        else:
            executions = self._execution_history
        
        if not executions:
            return 0.0
        
        successful = sum(1 for e in executions if e.success)
        return (successful / len(executions)) * 100
    
    def get_favorite_tools(self, limit: int = 5) -> List[str]:
        """Get most frequently used tools"""
        from collections import Counter
        
        if not self._execution_history:
            return []
        
        tool_counts = Counter(e.tool_name for e in self._execution_history)
        return [name for name, _ in tool_counts.most_common(limit)]
    
    def clear_cache(self) -> None:
        """Clear tool cache"""
        # Keep local tools
        local_tools = {k: v for k, v in self._tool_cache.items() if v.get("local")}
        self._tool_cache = local_tools
    
    def clear_history(self) -> None:
        """Clear execution history"""
        self._execution_history.clear()


def get_tool_registry() -> ToolRegistry:
    """Get the singleton ToolRegistry instance"""
    return ToolRegistry()
