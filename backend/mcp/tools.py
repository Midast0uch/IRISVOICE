"""
Tool Registry - Manages tool execution and caching with security validation
"""
import asyncio
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field

# Import security components
try:
    from ..security.mcp_security import MCPSecurityManager, SecurityContext, SecurityValidation
    from ..security.audit_logger import SecurityAuditLogger
    SECURITY_AVAILABLE = True
except ImportError:
    SECURITY_AVAILABLE = False
    MCPSecurityManager = None
    SecurityContext = None
    SecurityValidation = None
    SecurityAuditLogger = None


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
    
    def __init__(self, max_history: int = 100, enable_security: bool = True):
        # Check if we need to re-initialize due to security settings change
        if ToolRegistry._initialized:
            # If security settings changed, we need to re-initialize
            if hasattr(self, '_security_enabled') and self._security_enabled == (enable_security and SECURITY_AVAILABLE):
                return
        
        self._tool_cache: Dict[str, Dict] = {}  # tool_name -> tool_info
        self._execution_history: List[ToolExecution] = []
        self._max_history = max_history
        self._local_tools: Dict[str, Callable] = {}  # Local Python functions
        
        # Initialize security components
        self._security_enabled = enable_security and SECURITY_AVAILABLE
        self._security_manager: Optional[MCPSecurityManager] = None
        self._audit_logger: Optional[SecurityAuditLogger] = None
        
        if self._security_enabled:
            try:
                self._audit_logger = SecurityAuditLogger()
                self._security_manager = MCPSecurityManager(self._audit_logger)
                print("[ToolRegistry] Security validation enabled")
            except Exception as e:
                print(f"[ToolRegistry] Failed to initialize security: {e}")
                self._security_enabled = False
        else:
            if not SECURITY_AVAILABLE:
                print("[ToolRegistry] Security components not available")
            elif not enable_security:
                print("[ToolRegistry] Security validation disabled by configuration")
        
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
    
    async def execute_local_tool(self, name: str, arguments: Dict[str, Any], 
                                context: Optional[SecurityContext] = None) -> Any:
        """Execute a local registered tool with security validation"""
        func = self._local_tools.get(name)
        if not func:
            return None
        
        # Security validation
        if self._security_enabled and self._security_manager:
            try:
                # Create context if not provided
                if context is None:
                    context = SecurityContext(
                        session_id="default",
                        user_id="system",
                        timestamp=datetime.now(),
                        tool_name=name,
                        operation_type="execute"
                    )
                
                # Validate the operation
                validation = await self._security_manager.validate_tool_operation(
                    tool_name=name,
                    operation="execute",
                    arguments=arguments,
                    context=context
                )
                
                if not validation.allowed:
                    error_msg = f"Security validation failed: {validation.reason}"
                    print(f"[ToolRegistry] {error_msg}")
                    
                    # Log the violation
                    if self._audit_logger:
                        await self._audit_logger.log_tool_operation(context, validation)
                    
                    return {"error": error_msg, "security_violation": True}
                
                # Log successful validation
                if self._audit_logger:
                    await self._audit_logger.log_tool_operation(context, validation)
                
                # Use sanitized arguments if provided
                if validation.sanitized_args is not None:
                    arguments = validation.sanitized_args
                    
            except Exception as e:
                print(f"[ToolRegistry] Security validation error: {e}")
                # Continue execution if security check fails (fail-open for now)
        
        # Execute the tool
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(**arguments)
            else:
                result = func(**arguments)
            
            # Record successful execution
            self.record_execution(name, "local", arguments, result, True)
            return result
            
        except Exception as e:
            error_result = {"error": str(e)}
            print(f"[ToolRegistry] Local tool error: {e}")
            
            # Record failed execution
            self.record_execution(name, "local", arguments, error_result, False)
            return error_result
    
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
    
    async def validate_tool_operation(self, tool_name: str, operation: str, 
                                    arguments: Dict[str, Any], 
                                    context: Optional[SecurityContext] = None) -> Any:
        """Validate a tool operation with security checks"""
        if not self._security_enabled or not self._security_manager:
            # Return permissive validation if security is disabled
            if SecurityValidation:
                return SecurityValidation(
                    allowed=True,
                    reason="Security validation disabled",
                    security_level="low",
                    risk_score=0.0,
                    sanitized_args=arguments
                )
            else:
                return {"allowed": True, "reason": "Security validation disabled"}
        
        # Create context if not provided
        if context is None:
            context = SecurityContext(
                session_id="default",
                user_id="system",
                timestamp=datetime.now(),
                tool_name=tool_name,
                operation_type=operation
            )
        
        # Perform validation
        return await self._security_manager.validate_tool_operation(
            tool_name=tool_name,
            operation=operation,
            arguments=arguments,
            context=context
        )
    
    async def execute_tool_with_security(self, tool_name: str, operation: str, 
                                      arguments: Dict[str, Any], 
                                      context: Optional[SecurityContext] = None) -> Dict[str, Any]:
        """Execute a tool with security validation"""
        # Validate the operation
        validation = await self.validate_tool_operation(tool_name, operation, arguments, context)
        
        if not validation.allowed:
            return {
                "error": f"Security validation failed: {validation.reason}",
                "security_violation": True,
                "validation": validation
            }
        
        # For local tools, execute directly
        if tool_name in self._local_tools:
            return await self.execute_local_tool(tool_name, validation.sanitized_args, context)
        
        # For external tools, return validation result
        return {
            "validation": validation,
            "ready_to_execute": True,
            "sanitized_args": validation.sanitized_args
        }
    
    def is_security_enabled(self) -> bool:
        """Check if security validation is enabled"""
        return self._security_enabled
    
    def get_security_status(self) -> Dict[str, Any]:
        """Get security status information"""
        return {
            "enabled": self._security_enabled,
            "available": SECURITY_AVAILABLE,
            "manager_initialized": self._security_manager is not None,
            "audit_logger_initialized": self._audit_logger is not None
        }
    
    async def get_security_analytics(self) -> Dict[str, Any]:
        """Get security analytics if audit logger is available"""
        if not self._audit_logger:
            return {"error": "Audit logger not available"}
        
        return await self._audit_logger.get_security_analytics()
    
    async def detect_security_anomalies(self) -> List[Dict[str, Any]]:
        """Detect security anomalies if audit logger is available"""
        if not self._audit_logger:
            return []
        
        return await self._audit_logger.detect_anomalies()


def get_tool_registry() -> ToolRegistry:
    """Get the singleton ToolRegistry instance"""
    return ToolRegistry()
