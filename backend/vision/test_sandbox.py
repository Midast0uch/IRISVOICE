import pytest
import asyncio
import json
from pathlib import Path
from datetime import datetime, timedelta

from .sandbox_executor import SandboxedExecutor, ExecutionContext, ExecutionResult
from .permission_system import PermissionRequestSystem, PermissionRequest, PermissionResponse
from .automation_audit import AutomationAuditLogger, AuditEvent
from .action_allowlist import ActionAllowlist, ActionType, UIAction

@pytest.fixture
def allowlist_manager(tmp_path):
    """Fixture for ActionAllowlist."""
    config_path = tmp_path / "ui_actions.json"
    return ActionAllowlist(config_path=config_path)

@pytest.fixture
def sandbox_executor(allowlist_manager):
    """Fixture for SandboxedExecutor."""
    return SandboxedExecutor(allowlist=allowlist_manager)

@pytest.fixture
def permission_system(tmp_path):
    """Fixture for PermissionRequestSystem."""
    config_path = tmp_path / "permissions.json"
    return PermissionRequestSystem(config_path=config_path)

@pytest.fixture
def audit_logger(tmp_path):
    """Fixture for AutomationAuditLogger."""
    log_dir = tmp_path / "audit_logs"
    logger = AutomationAuditLogger(log_dir=log_dir)
    yield logger
    # stop_worker is synchronous
    logger.stop_worker()

class TestSandboxedExecutor:
    """Test cases for SandboxedExecutor."""
    
    @pytest.mark.asyncio
    async def test_create_execution_context(self, sandbox_executor):
        """Test creating execution context."""
        context = await sandbox_executor.create_execution_context(
            session_id="test_session",
            user_id="test_user",
            permissions={"ui_automation", "element_click"},
            restrictions={"block_all_actions": False}
        )
        
        assert context.session_id == "test_session"
        assert context.user_id == "test_user"
        assert "ui_automation" in context.permissions
        assert context.restrictions["block_all_actions"] is False
    
    @pytest.mark.asyncio
    async def test_execute_safe_action(self, sandbox_executor):
        """Test executing a safe action."""
        context = await sandbox_executor.create_execution_context(
            session_id="test_session",
            user_id="test_user",
            permissions={"ui_automation", "element_click"}
        )
        
        action = UIAction(
            action_type=ActionType.CLICK,
            target_role="button",
            target_name="Submit Button"
        )
        
        result = await sandbox_executor.execute_action(action, context)
        
        assert result["success"] is True
        assert result["execution_time"] > 0
        assert result["simulated"] is True
    
    @pytest.mark.asyncio
    async def test_execute_blocked_action(self, sandbox_executor):
        """Test executing a blocked action."""
        context = await sandbox_executor.create_execution_context(
            session_id="test_session",
            user_id="test_user",
            permissions={"ui_automation"}
        )
        
        # This action should be blocked by the dangerous actions rule
        action = UIAction(
            action_type=ActionType.RIGHT_CLICK,
            target_role="button",
            target_name="Context Menu"
        )
        
        result = await sandbox_executor.execute_action(action, context)
        
        assert result["success"] is False
        assert "not allowed" in result["error"]
        assert result["rule_matched"] == "dangerous_actions"
    
    @pytest.mark.asyncio
    async def test_execute_actions_batch(self, sandbox_executor):
        """Test executing multiple actions in batch."""
        context = await sandbox_executor.create_execution_context(
            session_id="test_session",
            user_id="test_user",
            permissions={"ui_automation", "element_click", "text_input", "form_input"}
        )
        
        actions = [
            UIAction(action_type=ActionType.CLICK, target_role="button"),
            UIAction(action_type=ActionType.TYPE, target_role="textbox", target_name="Username"),
            UIAction(action_type=ActionType.CLICK, target_role="button", target_name="Submit")
        ]
        
        result = await sandbox_executor.execute_actions(actions, context)
        
        assert isinstance(result, ExecutionResult)
        assert result.success is True
        assert len(result.actions_executed) == 3
        assert len(result.errors) == 0
        assert result.execution_time > 0
    
    @pytest.mark.asyncio
    async def test_rate_limiting(self, sandbox_executor):
        """Test rate limiting functionality."""
        context = await sandbox_executor.create_execution_context(
            session_id="test_session",
            user_id="test_user",
            permissions={"ui_automation", "element_click"},
            restrictions={"max_actions_per_minute": 2}
        )
        
        action = UIAction(action_type=ActionType.CLICK, target_role="button")
        
        # Execute actions up to the limit
        result1 = await sandbox_executor.execute_action(action, context)
        assert result1["success"] is True
        
        result2 = await sandbox_executor.execute_action(action, context)
        assert result2["success"] is True
        
        # This should hit the rate limit
        result3 = await sandbox_executor.execute_action(action, context)
        assert result3["success"] is False
        assert "Rate limit exceeded" in result3["error"]
    
    @pytest.mark.asyncio
    async def test_permission_checking(self, sandbox_executor):
        """Test permission checking."""
        context = await sandbox_executor.create_execution_context(
            session_id="test_session",
            user_id="test_user",
            permissions={"ui_automation"}  # Missing element_click permission
        )
        
        action = UIAction(action_type=ActionType.CLICK, target_role="button")
        
        result = await sandbox_executor.execute_action(action, context)
        
        assert result["success"] is False
        assert "Missing required permissions" in result["error"]
    
    @pytest.mark.asyncio
    async def test_execution_history(self, sandbox_executor):
        """Test execution history tracking."""
        context = await sandbox_executor.create_execution_context(
            session_id="test_session",
            user_id="test_user",
            permissions={"ui_automation", "element_click"}
        )
        
        # Execute a few actions
        action = UIAction(action_type=ActionType.CLICK, target_role="button")
        await sandbox_executor.execute_action(action, context)
        await sandbox_executor.execute_action(action, context)
        
        # Get execution history
        history = await sandbox_executor.get_execution_history(session_id="test_session", limit=10)
        
        assert len(history) == 2
        assert all(entry["session_id"] == "test_session" for entry in history)
        assert all("action" in entry for entry in history)

class TestPermissionRequestSystem:
    """Test cases for PermissionRequestSystem."""
    
    @pytest.mark.asyncio
    async def test_create_permission_request(self, permission_system):
        """Test creating a permission request."""
        request = await permission_system.create_permission_request(
            session_id="test_session",
            user_id="test_user",
            permission_type="basic_automation",
            requested_actions=["click", "hover"],
            justification="Need to interact with UI elements"
        )
        
        assert request.session_id == "test_session"
        assert request.user_id == "test_user"
        assert request.permission_type == "basic_automation"
        assert request.status == "approved"  # Should be auto-approved
        assert len(request.requested_actions) == 2
    
    @pytest.mark.asyncio
    async def test_auto_approve_permissions(self, permission_system):
        """Test auto-approval of permissions."""
        request = await permission_system.create_permission_request(
            session_id="test_session",
            user_id="test_user",
            permission_type="navigation",
            requested_actions=["scroll"]
        )
        
        assert request.status == "approved"
        
        # Check permission
        result = await permission_system.check_permission(
            session_id="test_session",
            permission_type="navigation",
            action="scroll"
        )
        
        assert result["allowed"] is True
        assert result["reason"] == "Action approved"
    
    @pytest.mark.asyncio
    async def test_permission_requiring_approval(self, permission_system):
        """Test permissions requiring manual approval."""
        request = await permission_system.create_permission_request(
            session_id="test_session",
            user_id="test_user",
            permission_type="advanced_interaction",
            requested_actions=["right_click", "double_click"],
            justification="Need advanced interactions for testing"
        )
        
        assert request.status == "pending"
        assert request.permission_type == "advanced_interaction"
        
        # Should not be allowed without approval
        result = await permission_system.check_permission(
            session_id="test_session",
            permission_type="advanced_interaction",
            action="right_click"
        )
        
        assert result["allowed"] is False
        assert result["requires_request"] is True
    
    @pytest.mark.asyncio
    async def test_approve_permission_request(self, permission_system):
        """Test approving a permission request."""
        request = await permission_system.create_permission_request(
            session_id="test_session",
            user_id="test_user",
            permission_type="text_input",
            requested_actions=["type"],
            justification="Need to fill forms"
        )
        
        response = await permission_system.approve_permission_request(
            request_id=request.request_id,
            approved_actions=["type"],
            reason="Approved for form filling"
        )
        
        assert response.approved is True
        assert response.request_id == request.request_id
        assert "type" in response.approved_actions
        
        # Check permission now
        result = await permission_system.check_permission(
            session_id="test_session",
            permission_type="text_input",
            action="type"
        )
        
        assert result["allowed"] is True
    
    @pytest.mark.asyncio
    async def test_deny_permission_request(self, permission_system):
        """Test denying a permission request."""
        request = await permission_system.create_permission_request(
            session_id="test_session",
            user_id="test_user",
            permission_type="system_ui",
            requested_actions=["click"],
            justification="Need system access"
        )
        
        response = await permission_system.deny_permission_request(
            request_id=request.request_id,
            reason="System UI access not allowed for this session"
        )
        
        assert response.approved is False
        assert response.request_id == request.request_id
        assert len(response.approved_actions) == 0
    
    @pytest.mark.asyncio
    async def test_permission_expiration(self, permission_system):
        """Test permission expiration."""
        request = await permission_system.create_permission_request(
            session_id="test_session",
            user_id="test_user",
            permission_type="basic_automation",
            requested_actions=["click"]
        )
        
        # Manually expire the permission by manipulating the stored data
        permission_key = "test_session:basic_automation"
        if permission_key in permission_system.approved_permissions:
            permission_system.approved_permissions[permission_key]["expires_at"] = datetime.now() - timedelta(minutes=1)
        
        # Check permission - should be expired
        result = await permission_system.check_permission(
            session_id="test_session",
            permission_type="basic_automation",
            action="click"
        )
        
        assert result["allowed"] is False
        assert result["reason"] == "Permission expired"
    
    @pytest.mark.asyncio
    async def test_revoke_permissions(self, permission_system):
        """Test revoking permissions."""
        # Create and approve permissions
        await permission_system.create_permission_request(
            session_id="test_session",
            user_id="test_user",
            permission_type="basic_automation",
            requested_actions=["click"]
        )
        
        await permission_system.create_permission_request(
            session_id="test_session",
            user_id="test_user",
            permission_type="navigation",
            requested_actions=["scroll"]
        )
        
        # Revoke all permissions
        revoked_count = await permission_system.revoke_all_permissions("test_session")
        
        assert revoked_count >= 2
        
        # Check permissions - should be gone
        result1 = await permission_system.check_permission(
            session_id="test_session",
            permission_type="basic_automation",
            action="click"
        )
        
        result2 = await permission_system.check_permission(
            session_id="test_session",
            permission_type="navigation",
            action="scroll"
        )
        
        assert result1["allowed"] is False
        assert result2["allowed"] is False

class TestAutomationAuditLogger:
    """Test cases for AutomationAuditLogger."""
    
    @pytest.mark.asyncio
    async def test_log_event(self, audit_logger):
        """Test logging an event."""
        await audit_logger.log_event(
            session_id="test_session",
            user_id="test_user",
            event_type="action_executed",
            details={"action": "click", "target": "button"},
            severity="info"
        )
        
        # Wait a bit for async logging
        await asyncio.sleep(0.1)
        
        # Query logs
        logs = await audit_logger.query_logs(session_id="test_session")
        
        assert len(logs) == 1
        assert logs[0]["event_type"] == "action_executed"
        assert logs[0]["session_id"] == "test_session"
        assert logs[0]["details"]["action"] == "click"
    
    @pytest.mark.asyncio
    async def test_log_multiple_events(self, audit_logger):
        """Test logging multiple events."""
        events = [
            ("action_executed", {"action": "click"}, "info"),
            ("permission_requested", {"permission": "text_input"}, "info"),
            ("error_occurred", {"error": "timeout"}, "error")
        ]
        
        for event_type, details, severity in events:
            await audit_logger.log_event(
                session_id="test_session",
                user_id="test_user",
                event_type=event_type,
                details=details,
                severity=severity
            )
        
        # Wait for async logging
        await asyncio.sleep(0.1)
        
        # Query logs
        logs = await audit_logger.query_logs(session_id="test_session")
        
        assert len(logs) == 3
        assert logs[0]["event_type"] == "action_executed"
        assert logs[1]["event_type"] == "permission_requested"
        assert logs[2]["event_type"] == "error_occurred"
        assert logs[2]["severity"] == "error"
    
    @pytest.mark.asyncio
    async def test_query_logs_with_filters(self, audit_logger):
        """Test querying logs with filters."""
        # Log events with different types and severities
        await audit_logger.log_event(
            session_id="test_session",
            user_id="test_user",
            event_type="action_executed",
            details={"action": "click"},
            severity="info"
        )
        
        await audit_logger.log_event(
            session_id="test_session",
            user_id="test_user",
            event_type="error_occurred",
            details={"error": "timeout"},
            severity="error"
        )
        
        await asyncio.sleep(0.1)
        
        # Query with event type filter
        logs = await audit_logger.query_logs(
            session_id="test_session",
            event_type="error_occurred"
        )
        
        assert len(logs) == 1
        assert logs[0]["event_type"] == "error_occurred"
        
        # Query with severity filter
        logs = await audit_logger.query_logs(
            session_id="test_session",
            severity="error"
        )
        
        assert len(logs) == 1
        assert logs[0]["severity"] == "error"
    
    @pytest.mark.asyncio
    async def test_log_rotation(self, audit_logger):
        """Test log rotation functionality."""
        # Create a large log entry to trigger rotation
        large_details = {"data": "x" * (1024 * 1024)}  # 1MB of data
        
        await audit_logger.log_event(
            session_id="test_session",
            user_id="test_user",
            event_type="large_event",
            details=large_details,
            severity="info"
        )
        
        # Wait for logging and rotation
        await asyncio.sleep(0.2)
        
        # Check if rotation occurred
        log_files = list(audit_logger.log_dir.glob("automation_audit_*.log"))
        
        # Should have at least the current log file
        assert len(log_files) >= 1
    
    @pytest.mark.asyncio
    async def test_audit_logger_with_sandbox_executor(self, audit_logger, allowlist_manager):
        """Test audit logger integration with sandbox executor."""
        sandbox_executor = SandboxedExecutor(
            allowlist=allowlist_manager,
            audit_logger=audit_logger
        )
        
        context = await sandbox_executor.create_execution_context(
            session_id="test_session",
            user_id="test_user",
            permissions={"ui_automation", "element_click"}
        )
        
        action = UIAction(action_type=ActionType.CLICK, target_role="button")
        
        # Execute action
        result = await sandbox_executor.execute_action(action, context)
        
        assert result["success"] is True
        
        # Wait for audit logging
        await asyncio.sleep(0.1)
        
        # Query audit logs
        logs = await audit_logger.query_logs(session_id="test_session")
        
        # Should have logged the action execution
        assert len(logs) >= 1
        assert any(log["event_type"] == "ui_action" for log in logs)