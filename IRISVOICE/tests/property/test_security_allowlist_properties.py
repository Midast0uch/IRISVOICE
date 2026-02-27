"""
Property-based tests for security allowlist enforcement.
Tests that tool executions with dangerous parameters are blocked by the SecurityFilter.
"""
import pytest
import asyncio
from hypothesis import given, settings, strategies as st, seed
import sys
import os

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.security.mcp_security import MCPSecurityManager
from backend.security.allowlists import MCP_ALLOWLISTS, DangerousPatterns
from backend.security.security_types import SecurityContext, SecurityLevel


# ============================================================================
# Test Data Generators (Hypothesis Strategies)
# ============================================================================

@st.composite
def safe_tool_names(draw):
    """Generate safe tool names from the allowlist."""
    return draw(st.sampled_from([
        "file_manager", "gui_automation", "system", 
        "web_browser", "clipboard", "screen_capture"
    ]))


@st.composite
def safe_operations(draw, tool_name):
    """Generate safe operations for a given tool."""
    allowlist = MCP_ALLOWLISTS.get(tool_name, {})
    operations = allowlist.get("operations", [])
    if not operations:
        return draw(st.just("read"))
    return draw(st.sampled_from(operations))


@st.composite
def safe_file_paths(draw):
    """Generate safe file paths within allowed directories."""
    safe_dirs = ["/tmp/sandbox/user_data", "/tmp/sandbox/temp", "/tmp/sandbox/cache"]
    safe_dir = draw(st.sampled_from(safe_dirs))
    filename = draw(st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'), whitelist_characters='_-.'),
        min_size=1,
        max_size=20
    ))
    extension = draw(st.sampled_from([".txt", ".json", ".xml", ".log", ".md"]))
    return f"{safe_dir}/{filename}{extension}"


@st.composite
def dangerous_file_paths(draw):
    """Generate dangerous file paths that should be blocked."""
    return draw(st.sampled_from([
        "/etc/passwd",
        "/etc/shadow",
        "C:\\Windows\\System32\\config\\SAM",
        "/usr/bin/sudo",
        "/system/bin/su",
        "../../../etc/passwd",
        "..\\..\\..\\Windows\\System32",
        "/tmp/../etc/passwd"
    ]))


@st.composite
def dangerous_commands(draw):
    """Generate dangerous system commands that should be blocked."""
    return draw(st.sampled_from([
        "rm -rf /",
        "format C:",
        "del /f /q C:\\*",
        "shutdown /s /t 0",
        "reboot now",
        "sudo rm -rf /",
        "powershell -e encoded_command",
        "bash -c 'rm -rf /'",
        "cmd /c del /f /q *"
    ]))


@st.composite
def dangerous_patterns_text(draw):
    """Generate text containing dangerous patterns."""
    patterns = [
        "eval(malicious_code)",
        "__import__('os').system('rm -rf /')",
        "password=secret123",
        "api_key=sk-1234567890",
        "nmap -sV target.com",
        "nc -lvp 4444",
        "xmrig --url pool.com",
        "DROP TABLE users;",
        "UNION SELECT * FROM passwords"
    ]
    return draw(st.sampled_from(patterns))


@st.composite
def safe_tool_arguments(draw, tool_name, operation):
    """Generate safe tool arguments."""
    if tool_name == "file_manager":
        if operation in ["read", "list"]:
            return {
                "path": draw(safe_file_paths()),
                "sandbox": draw(st.sampled_from(["user_data", "temp", "cache"]))
            }
        elif operation in ["write", "create"]:
            return {
                "path": draw(safe_file_paths()),
                "sandbox": draw(st.sampled_from(["user_data", "temp", "cache"])),
                "content": draw(st.text(min_size=0, max_size=100))
            }
    elif tool_name == "system":
        return {
            "command": draw(st.sampled_from(["ping", "echo", "hostname", "date", "time"]))
        }
    elif tool_name == "gui_automation":
        return {
            "selector": draw(st.text(min_size=1, max_size=20)),
            "action": draw(st.sampled_from(["click", "hover", "scroll"]))
        }
    else:
        return {}


@st.composite
def dangerous_tool_arguments(draw, tool_name, operation):
    """Generate dangerous tool arguments that should be blocked."""
    if tool_name == "file_manager":
        return {
            "path": draw(dangerous_file_paths()),
            "operation": operation
        }
    elif tool_name == "system":
        return {
            "command": draw(dangerous_commands())
        }
    elif tool_name == "gui_automation":
        return {
            "selector": draw(st.sampled_from(["password_field", "credit_card_input", "ssn_field"])),
            "action": "type"
        }
    else:
        return {
            "dangerous_pattern": draw(dangerous_patterns_text())
        }


# ============================================================================
# Property 26: Security Allowlist Enforcement
# Feature: irisvoice-backend-integration, Property 26: Security Allowlist Enforcement
# Validates: Requirements 8.7, 24.1, 24.2
# ============================================================================

class TestSecurityAllowlistEnforcement:
    """
    Property 26: Security Allowlist Enforcement
    
    For any tool execution with parameters that violate security allowlists,
    the SecurityFilter shall block the execution and return an error.
    """
    
    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None)
    @seed(42)  # Fixed seed for reproducibility
    @given(
        tool_name=safe_tool_names()
    )
    async def test_safe_tool_operations_are_allowed(self, tool_name):
        """
        Property: For any tool in the allowlist with safe parameters,
        the security manager allows the operation.
        
        # Feature: irisvoice-backend-integration, Property 26: Security Allowlist Enforcement
        """
        # Create security manager
        security_manager = MCPSecurityManager()
        
        # Get a safe operation for this tool
        allowlist = MCP_ALLOWLISTS.get(tool_name, {})
        operations = allowlist.get("operations", [])
        
        if not operations:
            pytest.skip(f"No operations defined for {tool_name}")
        
        operation = operations[0]
        
        # Generate safe arguments
        if tool_name == "file_manager":
            arguments = {
                "path": "/tmp/sandbox/user_data/test.txt",
                "sandbox": "user_data"
            }
        elif tool_name == "system":
            arguments = {"command": "echo hello"}
        elif tool_name == "gui_automation":
            arguments = {"selector": "button", "action": "click"}
        else:
            arguments = {}
        
        # Create security context
        context = SecurityContext(
            session_id="test_session",
            tool_name=tool_name,
            operation_type=operation
        )
        
        # Validate the operation
        validation = await security_manager.validate_tool_operation(
            tool_name=tool_name,
            operation=operation,
            arguments=arguments,
            context=context
        )
        
        # Verify the operation is allowed
        assert validation.allowed, \
            f"Safe operation {tool_name}.{operation} with safe arguments should be allowed. Reason: {validation.reason}"
        assert validation.security_level == SecurityLevel.SAFE, \
            f"Safe operation should have SAFE security level, got {validation.security_level}"
    
    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None)
    @seed(42)
    @given(
        tool_name=safe_tool_names()
    )
    async def test_dangerous_file_paths_are_blocked(self, tool_name):
        """
        Property: For any file operation with dangerous paths,
        the security manager blocks the operation.
        
        # Feature: irisvoice-backend-integration, Property 26: Security Allowlist Enforcement
        """
        if tool_name != "file_manager":
            pytest.skip("Test only applies to file_manager")
        
        # Create security manager
        security_manager = MCPSecurityManager()
        
        # Test dangerous paths
        dangerous_paths = [
            "/etc/passwd",
            "/etc/shadow",
            "C:\\Windows\\System32\\config\\SAM",
            "../../../etc/passwd"
        ]
        
        for dangerous_path in dangerous_paths:
            arguments = {
                "path": dangerous_path,
                "operation": "read"
            }
            
            context = SecurityContext(
                session_id="test_session",
                tool_name=tool_name,
                operation_type="read"
            )
            
            # Validate the operation
            validation = await security_manager.validate_tool_operation(
                tool_name=tool_name,
                operation="read",
                arguments=arguments,
                context=context
            )
            
            # Verify the operation is blocked
            assert not validation.allowed, \
                f"Dangerous path {dangerous_path} should be blocked"
            assert validation.security_level in [SecurityLevel.DANGEROUS, SecurityLevel.BLOCKED, SecurityLevel.RESTRICTED], \
                f"Dangerous operation should have high security level, got {validation.security_level}"
    
    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None)
    @seed(42)
    @given(
        command=dangerous_commands()
    )
    async def test_dangerous_system_commands_are_blocked(self, command):
        """
        Property: For any system operation with dangerous commands,
        the security manager blocks the operation.
        
        # Feature: irisvoice-backend-integration, Property 26: Security Allowlist Enforcement
        """
        # Create security manager
        security_manager = MCPSecurityManager()
        
        arguments = {"command": command}
        
        context = SecurityContext(
            session_id="test_session",
            tool_name="system",
            operation_type="execute"
        )
        
        # Validate the operation
        validation = await security_manager.validate_tool_operation(
            tool_name="system",
            operation="execute",
            arguments=arguments,
            context=context
        )
        
        # Verify the operation is blocked
        assert not validation.allowed, \
            f"Dangerous command '{command}' should be blocked. Reason: {validation.reason}"
        assert validation.security_level in [SecurityLevel.DANGEROUS, SecurityLevel.BLOCKED], \
            f"Dangerous command should have DANGEROUS or BLOCKED security level, got {validation.security_level}"
    
    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None)
    @seed(42)
    @given(
        pattern_text=dangerous_patterns_text()
    )
    async def test_dangerous_patterns_are_detected(self, pattern_text):
        """
        Property: For any tool arguments containing dangerous patterns,
        the security manager detects and blocks them.
        
        # Feature: irisvoice-backend-integration, Property 26: Security Allowlist Enforcement
        """
        # Create security manager
        security_manager = MCPSecurityManager()
        
        # Create arguments containing the dangerous pattern
        arguments = {
            "data": pattern_text,
            "content": f"Some text with {pattern_text} embedded"
        }
        
        context = SecurityContext(
            session_id="test_session",
            tool_name="test_tool",
            operation_type="execute"
        )
        
        # Validate the operation
        validation = await security_manager.validate_tool_operation(
            tool_name="test_tool",
            operation="execute",
            arguments=arguments,
            context=context
        )
        
        # Verify the operation is blocked (either by tool not in allowlist or pattern detection)
        assert not validation.allowed, \
            f"Arguments containing dangerous pattern '{pattern_text}' should be blocked"
    
    @pytest.mark.asyncio
    async def test_tool_not_in_allowlist_is_blocked(self):
        """
        Property: For any tool not in the allowlist,
        the security manager blocks all operations.
        
        # Feature: irisvoice-backend-integration, Property 26: Security Allowlist Enforcement
        """
        # Create security manager
        security_manager = MCPSecurityManager()
        
        # Test with a tool not in the allowlist
        unknown_tool = "malicious_tool"
        
        arguments = {"action": "do_something"}
        
        context = SecurityContext(
            session_id="test_session",
            tool_name=unknown_tool,
            operation_type="execute"
        )
        
        # Validate the operation
        validation = await security_manager.validate_tool_operation(
            tool_name=unknown_tool,
            operation="execute",
            arguments=arguments,
            context=context
        )
        
        # Verify the operation is blocked
        assert not validation.allowed, \
            f"Tool '{unknown_tool}' not in allowlist should be blocked"
        assert validation.security_level == SecurityLevel.BLOCKED, \
            f"Unknown tool should have BLOCKED security level, got {validation.security_level}"
        assert "not in security allowlist" in validation.reason.lower(), \
            f"Reason should mention allowlist, got: {validation.reason}"
    
    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None)
    @seed(42)
    @given(
        tool_name=safe_tool_names()
    )
    async def test_disallowed_operation_is_blocked(self, tool_name):
        """
        Property: For any operation not in the tool's allowed operations list,
        the security manager blocks the operation.
        
        # Feature: irisvoice-backend-integration, Property 26: Security Allowlist Enforcement
        """
        # Create security manager
        security_manager = MCPSecurityManager()
        
        # Use an operation that's not in the allowlist
        disallowed_operation = "malicious_operation_xyz"
        
        arguments = {"action": "test"}
        
        context = SecurityContext(
            session_id="test_session",
            tool_name=tool_name,
            operation_type=disallowed_operation
        )
        
        # Validate the operation
        validation = await security_manager.validate_tool_operation(
            tool_name=tool_name,
            operation=disallowed_operation,
            arguments=arguments,
            context=context
        )
        
        # Verify the operation is blocked
        assert not validation.allowed, \
            f"Disallowed operation '{disallowed_operation}' for tool '{tool_name}' should be blocked"
        assert validation.security_level in [SecurityLevel.RESTRICTED, SecurityLevel.BLOCKED], \
            f"Disallowed operation should have RESTRICTED or BLOCKED security level, got {validation.security_level}"
    
    @pytest.mark.asyncio
    async def test_path_traversal_attempts_are_blocked(self):
        """
        Property: For any file operation with path traversal attempts,
        the security manager blocks the operation.
        
        # Feature: irisvoice-backend-integration, Property 26: Security Allowlist Enforcement
        """
        # Create security manager
        security_manager = MCPSecurityManager()
        
        # Test path traversal patterns
        traversal_paths = [
            "../../../etc/passwd",
            "..\\..\\..\\Windows\\System32",
            "/tmp/../etc/passwd",
            "/tmp/sandbox/user_data/../../../etc/passwd"
        ]
        
        for traversal_path in traversal_paths:
            arguments = {
                "path": traversal_path,
                "sandbox": "user_data"
            }
            
            context = SecurityContext(
                session_id="test_session",
                tool_name="file_manager",
                operation_type="read"
            )
            
            # Validate the operation
            validation = await security_manager.validate_tool_operation(
                tool_name="file_manager",
                operation="read",
                arguments=arguments,
                context=context
            )
            
            # Verify the operation is blocked
            assert not validation.allowed, \
                f"Path traversal attempt '{traversal_path}' should be blocked"
    
    @pytest.mark.asyncio
    async def test_sensitive_ui_elements_are_blocked(self):
        """
        Property: For any GUI automation targeting sensitive UI elements,
        the security manager blocks the operation.
        
        # Feature: irisvoice-backend-integration, Property 26: Security Allowlist Enforcement
        """
        # Create security manager
        security_manager = MCPSecurityManager()
        
        # Test sensitive UI selectors
        sensitive_selectors = [
            "password_field",
            "credit_card_input",
            "ssn_field",
            "secret_key_input"
        ]
        
        for selector in sensitive_selectors:
            arguments = {
                "selector": selector,
                "action": "type"
            }
            
            context = SecurityContext(
                session_id="test_session",
                tool_name="gui_automation",
                operation_type="type"
            )
            
            # Validate the operation
            validation = await security_manager.validate_tool_operation(
                tool_name="gui_automation",
                operation="type",
                arguments=arguments,
                context=context
            )
            
            # Verify the operation is blocked
            assert not validation.allowed, \
                f"Sensitive UI element '{selector}' should be blocked"
    
    @pytest.mark.asyncio
    async def test_executable_file_creation_is_blocked(self):
        """
        Property: For any file write operation creating executable files,
        the security manager blocks the operation.
        
        # Feature: irisvoice-backend-integration, Property 26: Security Allowlist Enforcement
        """
        # Create security manager
        security_manager = MCPSecurityManager()
        
        # Test executable file extensions
        executable_extensions = [".exe", ".bat", ".cmd", ".sh", ".ps1"]
        
        for ext in executable_extensions:
            arguments = {
                "path": f"/tmp/sandbox/user_data/malicious{ext}",
                "sandbox": "user_data",
                "content": "malicious code"
            }
            
            context = SecurityContext(
                session_id="test_session",
                tool_name="file_manager",
                operation_type="write"
            )
            
            # Validate the operation
            validation = await security_manager.validate_tool_operation(
                tool_name="file_manager",
                operation="write",
                arguments=arguments,
                context=context
            )
            
            # Verify the operation is blocked
            assert not validation.allowed, \
                f"Creation of executable file with extension '{ext}' should be blocked"
    
    @pytest.mark.asyncio
    async def test_blocked_operations_return_appropriate_error_messages(self):
        """
        Property: For any blocked operation, the security manager returns
        an appropriate error message explaining why it was blocked.
        
        # Feature: irisvoice-backend-integration, Property 26: Security Allowlist Enforcement
        """
        # Create security manager
        security_manager = MCPSecurityManager()
        
        # Test various blocked scenarios
        test_cases = [
            {
                "tool_name": "unknown_tool",
                "operation": "execute",
                "arguments": {},
                "expected_reason_keywords": ["not in", "allowlist"]
            },
            {
                "tool_name": "file_manager",
                "operation": "read",
                "arguments": {"path": "/etc/passwd"},
                "expected_reason_keywords": ["system path", "blocked"]
            },
            {
                "tool_name": "system",
                "operation": "execute",
                "arguments": {"command": "rm -rf /"},
                "expected_reason_keywords": ["dangerous", "command", "blocked"]
            }
        ]
        
        for test_case in test_cases:
            context = SecurityContext(
                session_id="test_session",
                tool_name=test_case["tool_name"],
                operation_type=test_case["operation"]
            )
            
            validation = await security_manager.validate_tool_operation(
                tool_name=test_case["tool_name"],
                operation=test_case["operation"],
                arguments=test_case["arguments"],
                context=context
            )
            
            # Verify operation is blocked
            assert not validation.allowed, \
                f"Operation should be blocked for {test_case['tool_name']}.{test_case['operation']}"
            
            # Verify error message contains expected keywords
            reason_lower = validation.reason.lower()
            keywords_found = any(
                keyword.lower() in reason_lower 
                for keyword in test_case["expected_reason_keywords"]
            )
            assert keywords_found, \
                f"Error message should contain one of {test_case['expected_reason_keywords']}, got: {validation.reason}"
    
    @pytest.mark.asyncio
    async def test_sandboxed_file_operations_are_validated(self):
        """
        Property: For any file operation, sandboxing requirements are enforced.
        
        # Feature: irisvoice-backend-integration, Property 26: Security Allowlist Enforcement
        """
        # Create security manager
        security_manager = MCPSecurityManager()
        
        # Test unsandboxed access to system paths
        arguments = {
            "path": "/etc/passwd"
            # No sandbox parameter - unsandboxed access
        }
        
        context = SecurityContext(
            session_id="test_session",
            tool_name="file_manager",
            operation_type="read"
        )
        
        validation = await security_manager.validate_tool_operation(
            tool_name="file_manager",
            operation="read",
            arguments=arguments,
            context=context
        )
        
        # Verify unsandboxed system access is blocked
        assert not validation.allowed, \
            "Unsandboxed access to system paths should be blocked"
        
        # Test sandboxed access with valid sandbox
        arguments_sandboxed = {
            "path": "/tmp/sandbox/user_data/test.txt",
            "sandbox": "user_data"
        }
        
        validation_sandboxed = await security_manager.validate_tool_operation(
            tool_name="file_manager",
            operation="read",
            arguments=arguments_sandboxed,
            context=context
        )
        
        # Verify sandboxed access is allowed
        assert validation_sandboxed.allowed, \
            f"Sandboxed access should be allowed. Reason: {validation_sandboxed.reason}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
