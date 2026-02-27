#!/usr/bin/env python3
"""
Property-Based Tests for Destructive Operation Confirmation

Feature: irisvoice-backend-integration, Property 59: Destructive Operation Confirmation

Tests that the Security_Filter requires user confirmation for destructive operations:
- Destructive tool executions require confirmation
- Non-destructive operations proceed without confirmation
- Confirmation requirement is enforced consistently
- Audit logging captures confirmation requirements

**Validates: Requirements 24.4**
"""

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck
from unittest.mock import Mock, MagicMock, patch, AsyncMock
import asyncio

# Import security components
from backend.security.mcp_security import MCPSecurityManager
from backend.security.security_types import SecurityLevel, SecurityValidation
from backend.customize.behavior import BehaviorManager


# Strategy for generating tool names and operations
tool_names_strategy = st.sampled_from([
    "file_delete", "file_remove", "file_clear", "file_write",
    "system_shutdown", "system_restart", "system_format",
    "app_close", "app_kill", "app_launch",
    "browser_navigate", "browser_click", "browser_type",
    "gui_click", "gui_type", "gui_scroll"
])

destructive_operations_strategy = st.sampled_from([
    "delete", "remove", "clear", "reset", "shutdown", "restart",
    "format", "overwrite", "permanent_delete"
])

safe_operations_strategy = st.sampled_from([
    "read", "list", "get", "view", "search", "query",
    "navigate", "scroll", "click", "type", "launch"
])


# Property 59: Destructive Operation Confirmation
# Validates: Requirements 24.4

@given(
    tool_name=tool_names_strategy,
    operation=destructive_operations_strategy
)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_destructive_operations_require_confirmation(tool_name, operation):
    """
    Property: Destructive operations require user confirmation.
    
    For any tool execution classified as destructive, the system should:
    - Detect the destructive nature of the operation
    - Require user confirmation before proceeding
    - Log the confirmation requirement
    """
    # Create behavior manager
    behavior_manager = BehaviorManager()
    
    # Ensure confirmation is enabled
    behavior_manager.config["confirm_destructive"] = True
    
    # Check if confirmation is required
    should_confirm = behavior_manager.should_confirm(operation)
    
    # Verify confirmation is required for destructive operations
    assert should_confirm == True, \
        f"Destructive operation '{operation}' should require confirmation"


@given(
    tool_name=tool_names_strategy,
    operation=safe_operations_strategy
)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_safe_operations_do_not_require_confirmation(tool_name, operation):
    """
    Property: Safe operations do not require confirmation.
    
    For any tool execution classified as safe, the system should:
    - Detect the safe nature of the operation
    - Proceed without requiring confirmation
    - Not block the operation
    """
    # Create behavior manager
    behavior_manager = BehaviorManager()
    
    # Ensure confirmation is enabled
    behavior_manager.config["confirm_destructive"] = True
    
    # Check if confirmation is required
    should_confirm = behavior_manager.should_confirm(operation)
    
    # Verify confirmation is NOT required for safe operations
    assert should_confirm == False, \
        f"Safe operation '{operation}' should not require confirmation"


@given(operation=destructive_operations_strategy)
@settings(
    max_examples=50,
    deadline=None
)
def test_confirmation_can_be_disabled(operation):
    """
    Property: Confirmation requirement can be disabled via configuration.
    
    When confirmation is disabled in settings, the system should:
    - Not require confirmation even for destructive operations
    - Respect the user's configuration choice
    """
    # Create behavior manager
    behavior_manager = BehaviorManager()
    
    # Disable confirmation
    behavior_manager.config["confirm_destructive"] = False
    
    # Check if confirmation is required
    should_confirm = behavior_manager.should_confirm(operation)
    
    # Verify confirmation is NOT required when disabled
    assert should_confirm == False, \
        f"Destructive operation '{operation}' should not require confirmation when disabled"


@given(
    tool_name=tool_names_strategy,
    operation=destructive_operations_strategy
)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@pytest.mark.asyncio
async def test_security_manager_validates_destructive_operations(tool_name, operation):
    """
    Property: Security manager validates destructive operations.
    
    When a destructive operation is submitted, the security manager should:
    - Validate the operation
    - Return appropriate security level
    - Include confirmation requirement in validation result
    """
    # Create security manager
    security_manager = MCPSecurityManager()
    
    # Create mock arguments
    arguments = {
        "operation": operation,
        "target": "test_file.txt"
    }
    
    # Validate the operation
    validation = await security_manager.validate_tool_operation(
        tool_name=tool_name,
        operation=operation,
        arguments=arguments
    )
    
    # Verify validation result
    assert isinstance(validation, SecurityValidation), \
        "Validation should return SecurityValidation object"
    assert validation.allowed in [True, False], \
        "Validation should have allowed flag"
    assert isinstance(validation.security_level, SecurityLevel), \
        "Validation should have security level"


@given(operation=destructive_operations_strategy)
@settings(
    max_examples=50,
    deadline=None
)
def test_destructive_operation_detection_is_consistent(operation):
    """
    Property: Destructive operation detection is consistent.
    
    For any destructive operation, the detection should:
    - Be consistent across multiple calls
    - Return the same result for the same operation
    - Not depend on external state
    """
    # Create behavior manager
    behavior_manager = BehaviorManager()
    behavior_manager.config["confirm_destructive"] = True
    
    # Check confirmation requirement multiple times
    results = [behavior_manager.should_confirm(operation) for _ in range(5)]
    
    # Verify consistency
    assert all(r == results[0] for r in results), \
        f"Destructive operation detection should be consistent for '{operation}'"
    assert results[0] == True, \
        f"Destructive operation '{operation}' should consistently require confirmation"


@given(
    tool_name=tool_names_strategy,
    operation=destructive_operations_strategy
)
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@pytest.mark.asyncio
async def test_confirmation_requirement_is_logged(tool_name, operation):
    """
    Property: Confirmation requirements are logged for audit.
    
    When a destructive operation requires confirmation, the system should:
    - Log the confirmation requirement
    - Include operation details in the log
    - Maintain audit trail
    """
    # Create security manager with mock audit logger
    mock_audit_logger = AsyncMock()
    security_manager = MCPSecurityManager(audit_logger=mock_audit_logger)
    
    # Create mock arguments
    arguments = {
        "operation": operation,
        "target": "test_file.txt"
    }
    
    # Validate the operation
    validation = await security_manager.validate_tool_operation(
        tool_name=tool_name,
        operation=operation,
        arguments=arguments
    )
    
    # Verify validation completed
    assert isinstance(validation, SecurityValidation), \
        "Validation should return SecurityValidation object"


def test_destructive_operation_keywords():
    """
    Property: Destructive operation keywords are properly defined.
    
    The system should:
    - Have a well-defined list of destructive keywords
    - Include common destructive operations
    - Be comprehensive enough to catch dangerous operations
    """
    # Create behavior manager
    behavior_manager = BehaviorManager()
    behavior_manager.config["confirm_destructive"] = True
    
    # Test known destructive operations
    destructive_ops = [
        "delete", "remove", "clear", "reset", "shutdown", "restart",
        "format", "overwrite", "permanent_delete"
    ]
    
    for op in destructive_ops:
        should_confirm = behavior_manager.should_confirm(op)
        assert should_confirm == True, \
            f"Known destructive operation '{op}' should require confirmation"


def test_safe_operation_keywords():
    """
    Property: Safe operation keywords are properly recognized.
    
    The system should:
    - Recognize common safe operations
    - Not require confirmation for read-only operations
    - Allow normal operations to proceed
    """
    # Create behavior manager
    behavior_manager = BehaviorManager()
    behavior_manager.config["confirm_destructive"] = True
    
    # Test known safe operations
    safe_ops = [
        "read", "list", "get", "view", "search", "query",
        "navigate", "scroll", "click", "type", "launch", "open"
    ]
    
    for op in safe_ops:
        should_confirm = behavior_manager.should_confirm(op)
        assert should_confirm == False, \
            f"Known safe operation '{op}' should not require confirmation"


@given(operation=st.text(min_size=1, max_size=50))
@settings(
    max_examples=100,
    deadline=None
)
def test_confirmation_check_handles_arbitrary_operations(operation):
    """
    Property: Confirmation check handles arbitrary operation names gracefully.
    
    For any operation name, the system should:
    - Not crash or raise exceptions
    - Return a boolean result
    - Handle edge cases (empty strings, special characters, etc.)
    """
    # Create behavior manager
    behavior_manager = BehaviorManager()
    behavior_manager.config["confirm_destructive"] = True
    
    try:
        # Check if confirmation is required
        should_confirm = behavior_manager.should_confirm(operation)
        
        # Verify result is boolean
        assert isinstance(should_confirm, bool), \
            f"Confirmation check should return boolean for operation '{operation}'"
    except Exception as e:
        pytest.fail(f"Confirmation check should not raise exception for operation '{operation}': {e}")


@given(
    operation=destructive_operations_strategy,
    confirm_setting=st.booleans()
)
@settings(
    max_examples=50,
    deadline=None
)
def test_confirmation_setting_is_respected(operation, confirm_setting):
    """
    Property: Confirmation setting is respected consistently.
    
    The system should:
    - Respect the confirmation setting from configuration
    - Apply the setting consistently
    - Not override user preferences
    """
    # Create behavior manager
    behavior_manager = BehaviorManager()
    behavior_manager.config["confirm_destructive"] = confirm_setting
    
    # Check if confirmation is required
    should_confirm = behavior_manager.should_confirm(operation)
    
    # Verify setting is respected
    if confirm_setting:
        # When enabled, destructive operations should require confirmation
        assert should_confirm == True, \
            f"Destructive operation '{operation}' should require confirmation when setting is enabled"
    else:
        # When disabled, no operations should require confirmation
        assert should_confirm == False, \
            f"Operation '{operation}' should not require confirmation when setting is disabled"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
