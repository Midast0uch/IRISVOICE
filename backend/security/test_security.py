"""
Test suite for MCP Security Manager
Comprehensive testing of security validation, audit logging, and threat detection
"""
import asyncio
import pytest
import tempfile
import json
from pathlib import Path
from datetime import datetime

# Import security components
from backend.security.mcp_security import MCPSecurityManager
from backend.security.security_types import SecurityContext, SecurityLevel
from backend.security.allowlists import MCP_ALLOWLISTS, DangerousPatterns
from backend.security.audit_logger import SecurityAuditLogger, AuditEvent, AuditEventType, AuditSeverity
from backend.mcp.tools import ToolRegistry


class TestMCPSecurityManager:
    """Test the MCPSecurityManager class"""
    
    @pytest.fixture
    def security_manager(self):
        """Create a security manager instance for testing"""
        audit_logger = SecurityAuditLogger()
        return MCPSecurityManager(audit_logger)
    
    @pytest.fixture
    def sample_context(self):
        """Create a sample security context"""
        return SecurityContext(
            session_id="test_session_123",
            user_id="test_user",
            tool_name="file_manager",
            operation_type="read"
        )

    @pytest.fixture
    def sample_context(self):
        """Return a sample security context"""
        return SecurityContext(
            session_id="test_session_123",
            user_id="test_user",
            tool_name="file_manager",
            operation_type="read",
        )

    @pytest.mark.asyncio
    async def test_safe_file_read_operation(self, security_manager, sample_context):
        """Test safe file read operation"""
        arguments = {
            "path": "/tmp/test.txt",
            "encoding": "utf-8"
        }
        
        validation = await security_manager.validate_tool_operation(
            tool_name="file_manager",
            operation="read",
            arguments=arguments,
            context=sample_context
        )
        
        assert validation.allowed is True
        assert validation.security_level == SecurityLevel.SAFE
        assert validation.risk_score < 0.3
    
    @pytest.fixture
    def sample_context(self):
        """Return a sample security context"""
        return SecurityContext(
            session_id="test_session_123",
            user_id="test_user",
            tool_name="file_manager",
            operation_type="read",
        )

    @pytest.mark.asyncio
    async def test_dangerous_path_traversal_blocked(self, security_manager, sample_context):
        """Test that path traversal attacks are blocked"""
        arguments = {
            "path": "../../../etc/passwd",
            "encoding": "utf-8"
        }
        
        validation = await security_manager.validate_tool_operation(
            tool_name="file_manager",
            operation="read",
            arguments=arguments,
            context=sample_context
        )
        
        assert validation.allowed is False
        assert validation.security_level == SecurityLevel.BLOCKED
        assert validation.risk_score > 0.8
        assert "unsandboxed access" in validation.reason.lower() or "path traversal" in validation.reason.lower()
    
    @pytest.mark.asyncio
    async def test_command_injection_blocked(self, security_manager, sample_context):
        """Test that command injection attacks are blocked"""
        arguments = {
            "command": "rm -rf /",
            "shell": True
        }
        
        validation = await security_manager.validate_tool_operation(
            tool_name="system",
            operation="execute",
            arguments=arguments,
            context=sample_context
        )
        
        assert validation.allowed is False
        assert validation.security_level == SecurityLevel.DANGEROUS  # Command injection is DANGEROUS, not BLOCKED
        assert validation.risk_score > 0.8
    
    @pytest.mark.asyncio
    async def test_safe_system_ping(self, security_manager, sample_context):
        """Test safe system ping operation"""
        arguments = {
            "host": "localhost",
            "count": 1
        }
        
        validation = await security_manager.validate_tool_operation(
            tool_name="system",
            operation="ping",
            arguments=arguments,
            context=sample_context
        )
        
        assert validation.allowed is True
        assert validation.security_level == SecurityLevel.SAFE
    
    @pytest.mark.asyncio
    async def test_unknown_tool_blocked(self, security_manager, sample_context):
        """Test that unknown tools are blocked"""
        arguments = {"data": "test"}
        
        validation = await security_manager.validate_tool_operation(
            tool_name="unknown_tool",
            operation="execute",
            arguments=arguments,
            context=sample_context
        )
        
        assert validation.allowed is False
        assert validation.security_level == SecurityLevel.BLOCKED


class TestDangerousPatterns:
    """Test the DangerousPatterns class"""
    
    @pytest.fixture
    def dangerous_patterns(self):
        """Create a DangerousPatterns instance"""
        return DangerousPatterns()
    
    def test_path_traversal_detection(self, dangerous_patterns):
        """Test path traversal pattern detection"""
        test_cases = [
            ("../../../etc/passwd", True),
            ("..\\..\\windows\\system32\\config\\sam", True),
            ("/home/user/file.txt", False),
            ("./relative/path.txt", False),
            ("C:\\Users\\Public\\file.txt", False),
        ]
        
        for path, should_match in test_cases:
            result = dangerous_patterns.check_path_traversal(path)
            assert result == should_match, f"Path '{path}' should {'match' if should_match else 'not match'}"
    
    def test_command_injection_detection(self, dangerous_patterns):
        """Test command injection pattern detection"""
        test_cases = [
            ("rm -rf /", True),
            ("del /f /q *.*", True),
            ("ping localhost", True),
            ("echo 'hello'", False),
            ("ls -la", False),
        ]
        
        for command, should_match in test_cases:
            result = dangerous_patterns.check_command_injection(command)
            assert result == should_match, f"Command '{command}' should {'match' if should_match else 'not match'}"
    
    def test_code_injection_detection(self, dangerous_patterns):
        """Test code injection pattern detection"""
        test_cases = [
            ("eval('__import__(\"os\").system(\"ls\")')", True),
            ("exec('print(\"hello\")')", True),
            ("import os; os.system('ls')", True),
            ("print('hello world')", False),
            ("x = 5 + 3", False),
        ]
        
        for code, should_match in test_cases:
            result = dangerous_patterns.check_code_injection(code)
            assert result == should_match, f"Code '{code}' should {'match' if should_match else 'not match'}"


class TestSecurityAuditLogger:
    """Test the SecurityAuditLogger class"""
    
    @pytest.fixture
    def sample_context(self):
        """Return a sample security context"""
        return SecurityContext(
            session_id="test_session_123",
            user_id="test_user",
            tool_name="file_manager",
            operation_type="read",
        )
    
    @pytest.fixture
    def audit_logger(self):
        """Create an audit logger instance for testing"""
        with tempfile.TemporaryDirectory() as temp_dir:
            logger = SecurityAuditLogger(temp_dir)
            yield logger
            logger.close()
    
    @pytest.fixture
    def sample_event(self):
        """Create a sample audit event"""
        return AuditEvent(
            event_type=AuditEventType.TOOL_OPERATION,
            timestamp=datetime.now(),
            session_id="test_session_123",
            user_id="test_user",
            event_data={"tool": "file_manager", "operation": "read"},
            severity=AuditSeverity.INFO,
            risk_score=0.1
        )
    
    @pytest.mark.asyncio
    async def test_audit_event_creation(self, sample_event):
        """Test audit event creation and serialization"""
        event_dict = sample_event.to_dict()
        
        assert event_dict["event_type"] == "tool_operation"
        assert event_dict["session_id"] == "test_session_123"
        assert event_dict["severity"] == "info"
        assert event_dict["risk_score"] == 0.1
    
    @pytest.mark.asyncio
    async def test_audit_event_deserialization(self, sample_event):
        """Test audit event deserialization"""
        event_dict = sample_event.to_dict()
        restored_event = AuditEvent.from_dict(event_dict)
        
        assert restored_event.event_type == sample_event.event_type
        assert restored_event.session_id == sample_event.session_id
        assert restored_event.risk_score == sample_event.risk_score
    
    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_security_violation_logging(self, audit_logger, sample_context):
        """Test logging of security violations"""
        violation_event = AuditEvent(
            event_type=AuditEventType.SECURITY_VIOLATION,
            timestamp=datetime.now(),
            session_id="test_session_123",
            user_id="test_user",
            event_data={
                "tool_name": "file_manager",
                "operation": "read",
                "violation_type": "path_traversal",
                "blocked_path": "../../../etc/passwd"
            },
            severity=AuditSeverity.CRITICAL,
            risk_score=0.9
        )
        
        await audit_logger._log_event(violation_event)
        
        # Verify the event was logged
        analytics = await audit_logger.get_security_analytics()
        assert analytics["total_events"] > 0
        assert analytics["violations_rate"] > 0
    
    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_audit_trail_retrieval(self, audit_logger, sample_event):
        """Test audit trail retrieval with filtering"""
        # Log multiple events
        for i in range(5):
            event = AuditEvent(
                event_type=AuditEventType.TOOL_OPERATION,
                timestamp=datetime.now(),
                session_id=f"session_{i}",
                user_id=f"user_{i}",
                event_data={"index": i},
                severity=AuditSeverity.INFO,
                risk_score=0.1 * i
            )
            await audit_logger._log_event(event)
        
        # Test filtering by session
        trail = await audit_logger.get_audit_trail(session_id="session_2")
        assert len(trail) > 0
        assert all(e.session_id == "session_2" for e in trail)
    
    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_security_analytics(self, audit_logger, sample_context):
        """Test security analytics generation"""
        # Log some test events
        for i in range(10):
            event = AuditEvent(
                event_type=AuditEventType.TOOL_OPERATION,
                timestamp=datetime.now(),
                session_id=f"session_{i}",
                user_id=f"user_{i % 3}",  # 3 unique users
                event_data={"test": True},
                severity=AuditSeverity.INFO,
                risk_score=0.1
            )
            await audit_logger._log_event(event)

        analytics = await audit_logger.get_security_analytics()

        assert analytics["total_events"] == 10
        assert analytics["unique_sessions"] == 10
        assert analytics["unique_users"] == 3
        assert analytics["average_risk_score"] == pytest.approx(0.1)
        assert analytics["violations_rate"] == 0.0


class TestToolRegistrySecurity:
    """Test security integration with ToolRegistry"""
    
    @pytest.fixture
    def tool_registry(self):
        """Create a tool registry with security enabled"""
        registry = ToolRegistry(enable_security=True)
        
        # Register a test tool
        def test_tool_func(name: str = "world"):
            return f"Hello, {name}!"
        
        registry.register_local_tool("test_tool", test_tool_func, "A test tool")
        
        return registry
    
    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_secure_tool_execution(self, tool_registry):
        """Test secure tool execution"""
        result = await tool_registry.execute_local_tool("test_tool", {"name": "Security"})
        
        assert result == "Hello, Security!"
    
    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_security_validation_integration(self, tool_registry):
        """Test security validation in tool registry"""
        validation = await tool_registry.validate_tool_operation(
            tool_name="file_manager",
            operation="read",
            arguments={"path": "/etc/passwd"}
        )
        
        # Should be blocked due to dangerous path
        assert not validation.allowed
        assert validation.risk_score > 0.5
    
    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_security_status_reporting(self, tool_registry):
        """Test security status reporting"""
        status = tool_registry.get_security_status()
        
        assert status["enabled"] is True
        assert status["available"] is True
        assert status["manager_initialized"] is True
        assert status["audit_logger_initialized"] is True
    
    @pytest.mark.asyncio
    async def test_security_disabled_mode(self):
        """Test tool registry with security disabled"""
        registry = ToolRegistry(enable_security=False)
        
        status = registry.get_security_status()
        assert status["enabled"] is False
        
        # Should allow all operations when disabled
        validation = await registry.validate_tool_operation(
            tool_name="file_manager",
            operation="read",
            arguments={"path": "../../../etc/passwd"}
        )
        
        assert validation.allowed is True


class TestSecurityIntegration:
    """Test overall security integration"""
    
    @pytest.mark.asyncio
    async def test_end_to_end_security_flow(self):
        """Test complete security validation flow"""
        # Create components
        audit_logger = SecurityAuditLogger()
        security_manager = MCPSecurityManager(audit_logger)
        
        # Create context
        context = SecurityContext(
            session_id="integration_test_session",
            user_id="test_user",
            tool_name="file_manager",
            operation_type="write"
        )
        
        # Test dangerous operation
        dangerous_args = {
            "path": "../../../etc/shadow",
            "content": "malicious data"
        }
        
        validation = await security_manager.validate_tool_operation(
            tool_name="file_manager",
            operation="write",
            arguments=dangerous_args,
            context=context
        )
        
        # Verify blocking
        assert validation.allowed is False
        assert validation.security_level == SecurityLevel.BLOCKED
        
        # Verify audit logging
        analytics = await audit_logger.get_security_analytics()
        assert analytics["total_events"] > 0
        assert analytics["violations_rate"] > 0


# Integration test for the complete security system
@pytest.mark.asyncio
async def test_complete_security_system():
    """Test the complete security system integration"""
    
    # Create tool registry with security
    registry = ToolRegistry(enable_security=True)
    
    # Test safe file operation
    safe_result = await registry.execute_local_tool(
        "file_manager", 
        {"path": "/tmp/sandbox/user_data/test.txt", "operation": "read", "sandbox": "user_data"}
    )
    
    # The result should be the actual file content or an error message
    # Since the file doesn't exist, we expect an error or None
    assert safe_result is None or isinstance(safe_result, str) or isinstance(safe_result, dict)
    
    # Test dangerous file operation (should be blocked)
    dangerous_result = await registry.execute_local_tool(
        "file_manager",
        {"path": "../../../etc/passwd", "operation": "read"}
    )
    
    # The result should be None or a dictionary with security violation
    assert dangerous_result is None or (isinstance(dangerous_result, dict) and dangerous_result.get("security_violation", False))


class TestFileSandboxing:
    """Test file sandboxing functionality"""
    
    @pytest.fixture
    def security_manager(self):
        """Create a security manager instance for testing"""
        audit_logger = SecurityAuditLogger()
        return MCPSecurityManager(audit_logger)
    
    @pytest.fixture
    def sample_context(self):
        """Create a sample security context"""
        return SecurityContext(
            session_id="test_session_123",
            user_id="test_user",
            tool_name="file_manager",
            operation_type="read"
        )
    
    @pytest.mark.asyncio
    async def test_sandboxed_file_access_allowed(self, security_manager, sample_context):
        """Test that sandboxed file access within allowed directories works"""
        arguments = {
            "path": "/tmp/sandbox/user_data/test.txt",
            "sandbox": "user_data",
            "operation": "read"
        }
        
        validation = await security_manager.validate_tool_operation(
            tool_name="file_manager",
            operation="read",
            arguments=arguments,
            context=sample_context
        )
        
        assert validation.allowed is True
        assert validation.security_level == SecurityLevel.SAFE
    
    @pytest.mark.asyncio
    async def test_unsandboxed_file_access_blocked(self, security_manager, sample_context):
        """Test that unsandboxed access to system paths is blocked"""
        arguments = {
            "path": "/etc/passwd",
            "operation": "read"
        }
        
        validation = await security_manager.validate_tool_operation(
            tool_name="file_manager",
            operation="read",
            arguments=arguments,
            context=sample_context
        )
        
        assert validation.allowed is False
        assert validation.security_level == SecurityLevel.BLOCKED
        assert "unsandboxed access to system path" in validation.reason.lower()
    
    @pytest.mark.asyncio
    async def test_sandbox_escape_attempt_blocked(self, security_manager, sample_context):
        """Test that sandbox escape attempts are blocked"""
        arguments = {
            "path": "/tmp/sandbox/user_data/../../../etc/passwd",
            "sandbox": "user_data",
            "operation": "read"
        }
        
        validation = await security_manager.validate_tool_operation(
            tool_name="file_manager",
            operation="read",
            arguments=arguments,
            context=sample_context
        )
        
        assert validation.allowed is False
        assert validation.security_level == SecurityLevel.BLOCKED
        assert "sandbox escape attempt" in validation.reason.lower()
    
    @pytest.mark.asyncio
    async def test_sandbox_directory_creation_allowed(self, security_manager, sample_context):
        """Test that directory creation within a sandbox is allowed"""
        arguments = {
            "path": "/tmp/sandbox/user_data/new_folder",
            "sandbox": "user_data",
            "operation": "create"
        }
        
        validation = await security_manager.validate_tool_operation(
            tool_name="file_manager",
            operation="create",
            arguments=arguments,
            context=sample_context
        )
        
        assert validation.allowed is True
        assert validation.security_level == SecurityLevel.SAFE
    
    @pytest.mark.asyncio
    async def test_file_size_limit_enforced(self, security_manager, sample_context):
        """Test that file size limits are enforced"""
        arguments = {
            "path": "/tmp/sandbox/user_data/large_file.bin",
            "sandbox": "user_data",
            "operation": "write",
            "size": 20 * 1024 * 1024  # 20MB > 10MB limit
        }
        
        validation = await security_manager.validate_tool_operation(
            tool_name="file_manager",
            operation="write",
            arguments=arguments,
            context=sample_context
        )
        
        assert validation.allowed is False
        assert validation.security_level == SecurityLevel.RESTRICTED
        assert "exceeds limit" in validation.reason.lower()
    
    @pytest.mark.asyncio
    async def test_blocked_file_extensions_enforced(self, security_manager, sample_context):
        """Test that blocked file extensions are enforced"""
        arguments = {
            "path": "/tmp/sandbox/user_data/malware.exe",
            "sandbox": "user_data",
            "operation": "write"
        }
        
        validation = await security_manager.validate_tool_operation(
            tool_name="file_manager",
            operation="write",
            arguments=arguments,
            context=sample_context
        )
        
        assert validation.allowed is False
        assert validation.security_level == SecurityLevel.DANGEROUS
        assert "executable" in validation.reason.lower()
    
    @pytest.mark.asyncio
    async def test_mime_type_validation(self, security_manager, sample_context):
        """Test MIME type validation for file operations"""
        arguments = {
            "path": "/tmp/sandbox/user_data/document.pdf",
            "sandbox": "user_data",
            "operation": "write",
            "mime_type": "application/pdf"
        }
        
        validation = await security_manager.validate_tool_operation(
            tool_name="file_manager",
            operation="write",
            arguments=arguments,
            context=sample_context
        )
        
        assert validation.allowed is False
        assert validation.security_level == SecurityLevel.RESTRICTED
        assert "mime type" in validation.reason.lower()


if __name__ == "__main__":
    # Run basic tests
    asyncio.run(test_complete_security_system())
    print("✅ Basic security integration test passed!")