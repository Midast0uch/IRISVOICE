"""
MCP Security Manager - Controls and validates MCP tool operations
Implements security controls for Model Context Protocol tool execution
"""
import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from datetime import datetime

from .allowlists import MCP_ALLOWLISTS, DangerousPatterns
from .audit_logger import SecurityAuditLogger
from .security_types import SecurityContext, SecurityValidation, SecurityLevel


class MCPSecurityManager:
    """
    Central security manager for MCP tool operations.
    Implements allowlist-based validation, pattern detection, and audit logging.
    """
    
    def __init__(self, audit_logger: Optional[SecurityAuditLogger] = None):
        self.audit_logger = audit_logger or SecurityAuditLogger()
        self._dangerous_patterns = DangerousPatterns()
        self._validation_cache: Dict[str, SecurityValidation] = {}
        self._cache_ttl = 300  # 5 minutes
        self._stats = {
            "validations_total": 0,
            "validations_blocked": 0,
            "validations_allowed": 0,
            "cache_hits": 0,
            "cache_misses": 0
        }
        
    async def validate_tool_operation(
        self, 
        tool_name: str, 
        operation: str, 
        arguments: Dict[str, Any],
        context: Optional[SecurityContext] = None
    ) -> SecurityValidation:
        """
        Validate an MCP tool operation against security policies.
        
        Args:
            tool_name: Name of the MCP tool
            operation: Specific operation being performed
            arguments: Operation arguments
            context: Security context for the operation
            
        Returns:
            SecurityValidation result with allow/deny decision
        """
        self._stats["validations_total"] += 1
        
        # Create context if not provided
        if context is None:
            context = SecurityContext(
                session_id="unknown",
                tool_name=tool_name,
                operation_type=operation
            )
        
        # Check cache first
        cache_key = self._generate_cache_key(tool_name, operation, arguments)
        cached_result = self._get_cached_validation(cache_key)
        if cached_result:
            self._stats["cache_hits"] += 1
            return cached_result
        
        self._stats["cache_misses"] += 1
        
        # Perform validation
        validation = self._perform_validation(tool_name, operation, arguments, context)
        
        # Cache result
        self._set_cached_validation(cache_key, validation)
        
        # Log security violation if not allowed
        if not validation.allowed:
            await self.audit_logger.log_security_violation(
                validation_result=validation,
                context=context,
                tool_name=tool_name,
                operation_type=operation,
                sanitized_args=validation.sanitized_args
            )
        else:
            # Log successful operation
            await self.audit_logger.log_tool_operation(
                tool_name=tool_name,
                operation=operation,
                arguments=arguments,
                context=context,
                result=None,
                risk_score=validation.risk_score
            )
        
        # Update stats
        if validation.allowed:
            self._stats["validations_allowed"] += 1
        else:
            self._stats["validations_blocked"] += 1
            
        return validation
    
    def _perform_validation(
        self, 
        tool_name: str, 
        operation: str, 
        arguments: Dict[str, Any],
        context: SecurityContext
    ) -> SecurityValidation:
        """Core validation logic"""
        
        # Check if tool is in allowlist
        tool_allowlist = MCP_ALLOWLISTS.get(tool_name, {})
        allowed_operations = tool_allowlist.get("operations", [])
        
        # Tool not in allowlist - block by default
        if not tool_allowlist:
            return SecurityValidation(
                allowed=False,
                security_level=SecurityLevel.BLOCKED,
                reason=f"Tool '{tool_name}' not in security allowlist",
                risk_score=1.0
            )
        
        # Tool-specific validation (run first for file_manager to catch sandboxing issues early)
        tool_validation = self._validate_tool_specific(tool_name, operation, arguments, context)
        if not tool_validation.allowed:
            return tool_validation

        # Operation not allowed for this tool
        if operation not in allowed_operations:
            return SecurityValidation(
                allowed=False,
                security_level=SecurityLevel.RESTRICTED,
                reason=f"Operation '{operation}' not allowed for tool '{tool_name}'",
                risk_score=0.8
            )

        # Check for dangerous patterns in arguments
        pattern_validation = self._check_dangerous_patterns(arguments)
        if not pattern_validation.allowed:
            return pattern_validation
        
        # Sanitize arguments if needed
        sanitized_args = self._sanitize_arguments(tool_name, operation, arguments)
        
        return SecurityValidation(
            allowed=True,
            security_level=SecurityLevel.SAFE,
            reason="Operation validated successfully",
            sanitized_args=sanitized_args,
            risk_score=0.0
        )
    
    def _check_dangerous_patterns(self, arguments: Dict[str, Any]) -> SecurityValidation:
        """Check arguments for dangerous patterns"""
        
        # Convert arguments to string for pattern matching
        args_str = str(arguments).lower()
        
        # Check for dangerous patterns
        for pattern_name, pattern_info in self._dangerous_patterns.get_all_patterns().items():
            pattern = pattern_info["pattern"]
            severity = pattern_info["severity"]
            
            if re.search(pattern, args_str, re.IGNORECASE):
                risk_score = 1.0 if severity == "critical" else 0.7
                security_level = SecurityLevel.BLOCKED if severity == "critical" else SecurityLevel.RESTRICTED
                
                return SecurityValidation(
                    allowed=False,
                    security_level=security_level,
                    reason=f"Dangerous pattern detected: {pattern_name}",
                    risk_score=risk_score
                )
        
        return SecurityValidation(
            allowed=True,
            security_level=SecurityLevel.SAFE,
            reason="No dangerous patterns detected",
            risk_score=0.0
        )
    
    def _validate_tool_specific(
        self, 
        tool_name: str, 
        operation: str, 
        arguments: Dict[str, Any],
        context: SecurityContext
    ) -> SecurityValidation:
        """Tool-specific validation rules"""
        
        # File operations validation
        if tool_name == "file_manager":
            return self._validate_file_operation(operation, arguments, context)
        
        # GUI automation validation
        if tool_name == "gui_automation":
            return self._validate_gui_automation(operation, arguments, context)
        
        # System operations validation
        if tool_name == "system":
            return self._validate_system_operation(operation, arguments, context)
        
        return SecurityValidation(
            allowed=True,
            security_level=SecurityLevel.SAFE,
            reason="No tool-specific restrictions apply",
            risk_score=0.0
        )
    
    def _validate_file_operation(
        self, 
        operation: str, 
        arguments: Dict[str, Any], 
        context: SecurityContext
    ) -> SecurityValidation:
        """Validate file manager operations with sandboxing"""
        
        # First check for sandboxing requirements
        sandbox_validation = self._validate_file_sandboxing(operation, arguments, context)
        if not sandbox_validation.allowed:
            return sandbox_validation
        
        # Check path restrictions
        if "path" in arguments:
            path = arguments["path"]
            
            # Block system directories
            restricted_paths = [
                "/system", "/etc", "/usr", "/bin", "/sbin",
                "C:\\Windows", "C:\\Program Files", "C:\\ProgramData"
            ]
            
            for restricted in restricted_paths:
                if restricted in str(path).lower():
                    return SecurityValidation(
                        allowed=False,
                        security_level=SecurityLevel.DANGEROUS,
                        reason=f"Access to system path '{path}' blocked",
                        risk_score=0.9
                    )
        
        # Check file extensions for write operations
        if operation in ["write", "create"] and "path" in arguments:
            path = arguments["path"]
            dangerous_extensions = [".exe", ".bat", ".cmd", ".sh", ".ps1"]
            
            for ext in dangerous_extensions:
                if str(path).lower().endswith(ext):
                    return SecurityValidation(
                        allowed=False,
                        security_level=SecurityLevel.DANGEROUS,
                        reason=f"Creation of executable files blocked: {path}",
                        risk_score=0.8
                    )
        
        return SecurityValidation(
            allowed=True,
            security_level=SecurityLevel.SAFE,
            reason="File operation validated",
            risk_score=0.1
        )
    
    def _validate_file_sandboxing(
        self,
        operation: str,
        arguments: Dict[str, Any],
        context: SecurityContext
    ) -> SecurityValidation:
        """Validate file sandboxing requirements"""
        
        # Get tool allowlist for file operations
        tool_allowlist = MCP_ALLOWLISTS.get("file_manager", {})
        restrictions = tool_allowlist.get("restrictions", {})
        
        # Check if sandboxing is required (no sandbox parameter means unsandboxed)
        sandbox = arguments.get("sandbox")
        path = arguments.get("path", "")
        
        # If no sandbox specified and path looks dangerous, block it
        if not sandbox and path:
            # Check if path is trying to access system directories
            system_paths = ["/etc", "/usr", "/bin", "/sbin", "/var", "C:\\Windows", "C:\\ProgramData"]
            for sys_path in system_paths:
                if sys_path.lower() in str(path).lower():
                    return SecurityValidation(
                        allowed=False,
                        security_level=SecurityLevel.BLOCKED,
                        reason=f"Unsandboxed access to system path '{path}' blocked",
                        risk_score=0.95
                    )
        
        # If sandbox is specified, validate sandbox rules
        if sandbox:
            # Get allowed sandboxes from restrictions
            allowed_sandboxes = restrictions.get("allowed_sandboxes", ["user_data", "temp", "cache"])
            
            if sandbox not in allowed_sandboxes:
                return SecurityValidation(
                    allowed=False,
                    security_level=SecurityLevel.BLOCKED,
                    reason=f"Sandbox '{sandbox}' not allowed",
                    risk_score=0.9
                )
            
            # Validate path is within sandbox boundaries
            sandbox_validation = self._validate_sandbox_path(path, sandbox, restrictions)
            if not sandbox_validation.allowed:
                return sandbox_validation
            
            # Check file size limits
            if "size" in arguments:
                file_size = arguments["size"]
                max_file_size = restrictions.get("max_file_size", 10 * 1024 * 1024)  # 10MB default
                if file_size > max_file_size:
                    return SecurityValidation(
                        allowed=False,
                        security_level=SecurityLevel.RESTRICTED,
                        reason=f"File size {file_size} exceeds limit {max_file_size}",
                        risk_score=0.6
                    )
            
            # Check MIME type restrictions
            if "mime_type" in arguments:
                mime_type = arguments["mime_type"]
                allowed_mime_types = restrictions.get("allowed_mime_types", ["text/*", "application/json", "application/xml"])
                
                mime_allowed = False
                for allowed_pattern in allowed_mime_types:
                    if allowed_pattern.endswith("/*"):
                        # Wildcard pattern like "text/*"
                        prefix = allowed_pattern[:-2]
                        if mime_type.startswith(prefix + "/"):
                            mime_allowed = True
                            break
                    elif mime_type == allowed_pattern:
                        mime_allowed = True
                        break
                
                if not mime_allowed:
                    return SecurityValidation(
                        allowed=False,
                        security_level=SecurityLevel.RESTRICTED,
                        reason=f"MIME type '{mime_type}' not allowed in sandbox",
                        risk_score=0.5
                    )
        
        return SecurityValidation(
            allowed=True,
            security_level=SecurityLevel.SAFE,
            reason="Sandboxing validation passed",
            risk_score=0.0
        )
    
    def _validate_sandbox_path(
        self,
        path: str,
        sandbox: str,
        restrictions: Dict[str, Any]
    ) -> SecurityValidation:
        """Validate that path is within sandbox boundaries"""
        
        if not path:
            return SecurityValidation(
                allowed=True,
                security_level=SecurityLevel.SAFE,
                reason="No path specified",
                risk_score=0.0
            )
        
        # Get sandbox base paths from restrictions
        sandbox_paths = restrictions.get("sandbox_paths", {
            "user_data": "/tmp/sandbox/user_data",
            "temp": "/tmp/sandbox/temp",
            "cache": "/tmp/sandbox/cache"
        })
        
        base_path = sandbox_paths.get(sandbox, f"/tmp/sandbox/{sandbox}")
        
        # Normalize paths for comparison
        normalized_path = str(path).replace("\\", "/")
        normalized_base = base_path.replace("\\", "/")
        
        # Check for path traversal attempts
        if "../" in normalized_path or "..\\" in str(path):
            return SecurityValidation(
                allowed=False,
                security_level=SecurityLevel.BLOCKED,
                reason=f"Sandbox escape attempt detected in path '{path}'",
                risk_score=1.0
            )
        
        # Ensure path starts with base path (sandbox boundary check)
        if not normalized_path.startswith(normalized_base):
            # Allow if it's a relative path within sandbox
            if not str(path).startswith("/") and not str(path).startswith("C:\\"):
                # Relative path - should be resolved within sandbox
                return SecurityValidation(
                    allowed=True,
                    security_level=SecurityLevel.SAFE,
                    reason="Relative path within sandbox",
                    risk_score=0.0
                )
            else:
                return SecurityValidation(
                    allowed=False,
                    security_level=SecurityLevel.BLOCKED,
                    reason=f"Path '{path}' outside sandbox '{sandbox}' boundaries",
                    risk_score=0.9
                )
        
        return SecurityValidation(
            allowed=True,
            security_level=SecurityLevel.SAFE,
            reason="Path within sandbox boundaries",
            risk_score=0.0
        )
    
    def _validate_gui_automation(
        self, 
        operation: str, 
        arguments: Dict[str, Any], 
        context: SecurityContext
    ) -> SecurityValidation:
        """Validate GUI automation operations"""
        
        # Block sensitive UI elements
        if "selector" in arguments:
            selector = str(arguments["selector"]).lower()
            sensitive_elements = ["password", "credit", "ssn", "secret"]
            
            for sensitive in sensitive_elements:
                if sensitive in selector:
                    return SecurityValidation(
                        allowed=False,
                        security_level=SecurityLevel.DANGEROUS,
                        reason=f"Interaction with sensitive UI element blocked: {selector}",
                        risk_score=0.9
                    )
        
        return SecurityValidation(
            allowed=True,
            security_level=SecurityLevel.SAFE,
            reason="GUI automation validated",
            risk_score=0.2
        )
    
    def _validate_system_operation(
        self, 
        operation: str, 
        arguments: Dict[str, Any], 
        context: SecurityContext
    ) -> SecurityValidation:
        """Validate system operations"""
        
        # Block dangerous system commands
        if "command" in arguments:
            command = str(arguments["command"]).lower()
            dangerous_commands = ["format", "del", "rm -rf", "shutdown", "reboot"]
            
            for dangerous in dangerous_commands:
                if command.startswith(dangerous):
                    return SecurityValidation(
                        allowed=False,
                        security_level=SecurityLevel.DANGEROUS,
                        reason=f"Dangerous system command blocked: {command}",
                        risk_score=1.0
                    )
        
        return SecurityValidation(
            allowed=True,
            security_level=SecurityLevel.SAFE,
            reason="System operation validated",
            risk_score=0.1
        )
    
    def _sanitize_arguments(
        self, 
        tool_name: str, 
        operation: str, 
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Sanitize arguments based on tool and operation"""
        
        sanitized = arguments.copy()
        
        # Remove potentially sensitive data
        sensitive_keys = ["password", "secret", "token", "key", "credential"]
        for key in list(sanitized.keys()):
            if any(sensitive in key.lower() for sensitive in sensitive_keys):
                sanitized[key] = "[REDACTED]"
        
        return sanitized
    
    def _generate_cache_key(self, tool_name: str, operation: str, arguments: Dict[str, Any]) -> str:
        """Generate cache key for validation result"""
        # Create a simple hash of the key components
        import hashlib
        key_str = f"{tool_name}:{operation}:{str(sorted(arguments.items()))}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _get_cached_validation(self, cache_key: str) -> Optional[SecurityValidation]:
        """Get cached validation result"""
        if cache_key in self._validation_cache:
            # Check if cache is still valid
            cached_time = getattr(self._validation_cache[cache_key], '_cache_time', 0)
            current_time = asyncio.get_event_loop().time()
            
            if current_time - cached_time < self._cache_ttl:
                return self._validation_cache[cache_key]
            else:
                # Cache expired
                del self._validation_cache[cache_key]
        
        return None
    
    def _set_cached_validation(self, cache_key: str, validation: SecurityValidation):
        """Cache validation result"""
        validation._cache_time = asyncio.get_event_loop().time()
        self._validation_cache[cache_key] = validation
    
    def get_security_stats(self) -> Dict[str, Any]:
        """Get security validation statistics"""
        total = self._stats["validations_total"]
        blocked = self._stats["validations_blocked"]
        
        return {
            "total_validations": total,
            "blocked_operations": blocked,
            "allowed_operations": self._stats["validations_allowed"],
            "block_rate": (blocked / total * 100) if total > 0 else 0,
            "cache_hit_rate": (self._stats["cache_hits"] / 
                              (self._stats["cache_hits"] + self._stats["cache_misses"]) * 100 
                              if (self._stats["cache_hits"] + self._stats["cache_misses"]) > 0 else 0),
            "cache_size": len(self._validation_cache)
        }
    
    def clear_cache(self):
        """Clear validation cache"""
        self._validation_cache.clear()
        self._stats["cache_hits"] = 0
        self._stats["cache_misses"] = 0
    
    def update_allowlist(self, tool_name: str, operations: List[str]):
        """Update allowlist for a specific tool"""
        if tool_name in MCP_ALLOWLISTS:
            MCP_ALLOWLISTS[tool_name]["operations"] = operations
            self.clear_cache()  # Clear cache to reflect changes
            
            # Audit log the change
            self.audit_logger.log_allowlist_update(tool_name, operations)
    
    def add_dangerous_pattern(self, name: str, pattern: str, severity: str = "high"):
        """Add a new dangerous pattern"""
        self._dangerous_patterns.add_pattern(name, pattern, severity)
        self.clear_cache()
        
        # Audit log the change
        self.audit_logger.log_pattern_update(name, pattern, severity)


# Global security manager instance
_security_manager: Optional[MCPSecurityManager] = None


def get_security_manager() -> MCPSecurityManager:
    """Get the singleton MCPSecurityManager instance"""
    global _security_manager
    if _security_manager is None:
        _security_manager = MCPSecurityManager()
    return _security_manager