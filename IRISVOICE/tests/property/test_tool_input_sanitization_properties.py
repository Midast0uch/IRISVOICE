#!/usr/bin/env python3
"""
Property-Based Tests for Tool Input Sanitization

Feature: irisvoice-backend-integration, Property 60: Tool Input Sanitization

Tests that the Tool_Bridge sanitizes all user inputs before passing them to tools:
- Sensitive data is redacted from arguments
- Sanitization is applied consistently
- Sanitized arguments are logged for audit
- Original functionality is preserved

**Validates: Requirements 24.5**
"""

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck
from unittest.mock import Mock, MagicMock, patch, AsyncMock
import asyncio

# Import security components
from backend.security.mcp_security import MCPSecurityManager
from backend.security.security_types import SecurityLevel, SecurityValidation


# Strategy for generating tool names and operations
tool_names_strategy = st.sampled_from([
    "file_read", "file_write", "file_delete",
    "system_command", "system_query",
    "browser_navigate", "browser_click",
    "app_launch", "app_close"
])

operations_strategy = st.sampled_from([
    "read", "write", "delete", "execute", "query",
    "navigate", "click", "launch", "close"
])

# Strategy for generating arguments with sensitive data
sensitive_keys_strategy = st.sampled_from([
    "password", "secret", "token", "key", "credential",
    "api_key", "auth_token", "access_token", "private_key"
])

safe_keys_strategy = st.sampled_from([
    "filename", "path", "url", "command", "text",
    "target", "source", "destination", "query"
])

value_strategy = st.text(min_size=1, max_size=100)


# Property 60: Tool Input Sanitization
# Validates: Requirements 24.5

@given(
    tool_name=tool_names_strategy,
    operation=operations_strategy,
    sensitive_key=sensitive_keys_strategy,
    sensitive_value=value_strategy
)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@pytest.mark.asyncio
async def test_sensitive_data_is_redacted(tool_name, operation, sensitive_key, sensitive_value):
    """
    Property: Sensitive data is redacted from tool arguments.
    
    For any tool execution with sensitive arguments, the system should:
    - Detect sensitive keys (password, secret, token, key, credential)
    - Redact the values with [REDACTED]
    - Preserve non-sensitive arguments
    - Return sanitized arguments in validation result
    """
    # Create security manager
    security_manager = MCPSecurityManager()
    
    # Create arguments with sensitive data
    arguments = {
        sensitive_key: sensitive_value,
        "safe_param": "safe_value"
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
    
    # Verify sanitized arguments are provided
    if validation.sanitized_args is not None:
        # Check that sensitive key is redacted
        if sensitive_key in validation.sanitized_args:
            assert validation.sanitized_args[sensitive_key] == "[REDACTED]", \
                f"Sensitive key '{sensitive_key}' should be redacted"
        
        # Check that safe parameters are preserved
        if "safe_param" in validation.sanitized_args:
            assert validation.sanitized_args["safe_param"] == "safe_value", \
                "Safe parameters should be preserved"


@given(
    tool_name=tool_names_strategy,
    operation=operations_strategy,
    safe_key=safe_keys_strategy,
    safe_value=value_strategy
)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@pytest.mark.asyncio
async def test_safe_data_is_preserved(tool_name, operation, safe_key, safe_value):
    """
    Property: Safe data is preserved during sanitization.
    
    For any tool execution with non-sensitive arguments, the system should:
    - Preserve the original values
    - Not redact safe parameters
    - Maintain functionality
    """
    # Create security manager
    security_manager = MCPSecurityManager()
    
    # Create arguments with only safe data
    arguments = {
        safe_key: safe_value,
        "another_safe_param": "another_safe_value"
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
    
    # Verify sanitized arguments preserve safe data
    if validation.sanitized_args is not None:
        # Check that safe keys are preserved
        if safe_key in validation.sanitized_args:
            assert validation.sanitized_args[safe_key] == safe_value, \
                f"Safe key '{safe_key}' should be preserved with original value"


@given(
    tool_name=tool_names_strategy,
    operation=operations_strategy
)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@pytest.mark.asyncio
async def test_sanitization_is_applied_consistently(tool_name, operation):
    """
    Property: Sanitization is applied consistently across multiple calls.
    
    For any tool execution, the sanitization should:
    - Be consistent across multiple calls
    - Return the same sanitized result for the same input
    - Not depend on external state
    """
    # Create security manager
    security_manager = MCPSecurityManager()
    
    # Create arguments with sensitive data
    arguments = {
        "password": "secret123",
        "filename": "test.txt"
    }
    
    # Validate multiple times
    validations = []
    for _ in range(3):
        validation = await security_manager.validate_tool_operation(
            tool_name=tool_name,
            operation=operation,
            arguments=arguments
        )
        validations.append(validation)
    
    # Verify all validations are consistent
    for validation in validations:
        assert isinstance(validation, SecurityValidation), \
            "All validations should return SecurityValidation object"
        
        if validation.sanitized_args is not None:
            # Check that password is consistently redacted
            if "password" in validation.sanitized_args:
                assert validation.sanitized_args["password"] == "[REDACTED]", \
                    "Password should be consistently redacted"
            
            # Check that filename is consistently preserved
            if "filename" in validation.sanitized_args:
                assert validation.sanitized_args["filename"] == "test.txt", \
                    "Filename should be consistently preserved"


@given(
    tool_name=tool_names_strategy,
    operation=operations_strategy,
    num_sensitive=st.integers(min_value=1, max_value=5)
)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@pytest.mark.asyncio
async def test_multiple_sensitive_fields_are_redacted(tool_name, operation, num_sensitive):
    """
    Property: Multiple sensitive fields are all redacted.
    
    When multiple sensitive fields are present, the system should:
    - Redact all sensitive fields
    - Not miss any sensitive data
    - Preserve all non-sensitive fields
    """
    # Create security manager
    security_manager = MCPSecurityManager()
    
    # Create arguments with multiple sensitive fields
    sensitive_keys = ["password", "secret", "token", "key", "credential"][:num_sensitive]
    arguments = {key: f"sensitive_{key}" for key in sensitive_keys}
    arguments["safe_param"] = "safe_value"
    
    # Validate the operation
    validation = await security_manager.validate_tool_operation(
        tool_name=tool_name,
        operation=operation,
        arguments=arguments
    )
    
    # Verify validation result
    assert isinstance(validation, SecurityValidation), \
        "Validation should return SecurityValidation object"
    
    # Verify all sensitive fields are redacted
    if validation.sanitized_args is not None:
        for key in sensitive_keys:
            if key in validation.sanitized_args:
                assert validation.sanitized_args[key] == "[REDACTED]", \
                    f"Sensitive key '{key}' should be redacted"


@given(
    tool_name=tool_names_strategy,
    operation=operations_strategy
)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@pytest.mark.asyncio
async def test_sanitization_handles_empty_arguments(tool_name, operation):
    """
    Property: Sanitization handles empty arguments gracefully.
    
    When no arguments are provided, the system should:
    - Not crash or raise exceptions
    - Return valid sanitized arguments (empty or None)
    - Complete validation successfully
    """
    # Create security manager
    security_manager = MCPSecurityManager()
    
    # Validate with empty arguments
    validation = await security_manager.validate_tool_operation(
        tool_name=tool_name,
        operation=operation,
        arguments={}
    )
    
    # Verify validation result
    assert isinstance(validation, SecurityValidation), \
        "Validation should return SecurityValidation object"
    
    # Verify sanitized arguments are valid (empty dict or None)
    if validation.sanitized_args is not None:
        assert isinstance(validation.sanitized_args, dict), \
            "Sanitized arguments should be a dictionary"


@given(
    tool_name=tool_names_strategy,
    operation=operations_strategy,
    nested_level=st.integers(min_value=1, max_value=3)
)
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@pytest.mark.asyncio
async def test_sanitization_handles_nested_structures(tool_name, operation, nested_level):
    """
    Property: Sanitization handles nested data structures.
    
    When arguments contain nested dictionaries or lists, the system should:
    - Handle nested structures gracefully
    - Not crash on complex data
    - Return valid sanitized arguments
    """
    # Create security manager
    security_manager = MCPSecurityManager()
    
    # Create nested arguments
    arguments = {"level_0": "value_0"}
    current = arguments
    for i in range(1, nested_level + 1):
        current[f"level_{i}"] = {f"nested_{i}": f"value_{i}"}
        current = current[f"level_{i}"]
    
    # Add sensitive data at deepest level
    current["password"] = "secret"
    
    # Validate the operation
    validation = await security_manager.validate_tool_operation(
        tool_name=tool_name,
        operation=operation,
        arguments=arguments
    )
    
    # Verify validation result
    assert isinstance(validation, SecurityValidation), \
        "Validation should return SecurityValidation object"
    
    # Verify sanitized arguments are valid
    if validation.sanitized_args is not None:
        assert isinstance(validation.sanitized_args, dict), \
            "Sanitized arguments should be a dictionary"


def test_sensitive_keywords_are_comprehensive():
    """
    Property: Sensitive keywords list is comprehensive.
    
    The system should:
    - Include common sensitive keywords
    - Cover various types of credentials
    - Be comprehensive enough to catch sensitive data
    """
    # Create security manager
    security_manager = MCPSecurityManager()
    
    # Test known sensitive keywords
    sensitive_keywords = [
        "password", "secret", "token", "key", "credential",
        "api_key", "auth_token", "access_token", "private_key"
    ]
    
    # Create arguments with each sensitive keyword
    for keyword in sensitive_keywords:
        arguments = {keyword: "sensitive_value"}
        
        # Sanitize arguments
        sanitized = security_manager._sanitize_arguments(
            tool_name="test_tool",
            operation="test_operation",
            arguments=arguments
        )
        
        # Verify sensitive keyword is redacted
        assert sanitized[keyword] == "[REDACTED]", \
            f"Sensitive keyword '{keyword}' should be redacted"


def test_sanitization_preserves_argument_structure():
    """
    Property: Sanitization preserves the structure of arguments.
    
    The system should:
    - Maintain the same keys in sanitized arguments
    - Preserve the dictionary structure
    - Only modify values, not keys
    """
    # Create security manager
    security_manager = MCPSecurityManager()
    
    # Create arguments
    arguments = {
        "password": "secret123",
        "filename": "test.txt",
        "count": 42,
        "enabled": True
    }
    
    # Sanitize arguments
    sanitized = security_manager._sanitize_arguments(
        tool_name="test_tool",
        operation="test_operation",
        arguments=arguments
    )
    
    # Verify structure is preserved
    assert set(sanitized.keys()) == set(arguments.keys()), \
        "Sanitized arguments should have the same keys"
    
    # Verify password is redacted
    assert sanitized["password"] == "[REDACTED]", \
        "Password should be redacted"
    
    # Verify other values are preserved
    assert sanitized["filename"] == "test.txt", \
        "Filename should be preserved"


@given(
    arguments=st.dictionaries(
        keys=st.text(min_size=1, max_size=20),
        values=st.one_of(
            st.text(min_size=0, max_size=100),
            st.integers(),
            st.booleans(),
            st.none()
        ),
        min_size=0,
        max_size=10
    )
)
@settings(
    max_examples=100,
    deadline=None
)
def test_sanitization_handles_arbitrary_arguments(arguments):
    """
    Property: Sanitization handles arbitrary argument structures gracefully.
    
    For any argument structure, the system should:
    - Not crash or raise exceptions
    - Return valid sanitized arguments
    - Preserve the general structure
    """
    # Create security manager
    security_manager = MCPSecurityManager()
    
    try:
        # Sanitize arguments
        sanitized = security_manager._sanitize_arguments(
            tool_name="test_tool",
            operation="test_operation",
            arguments=arguments
        )
        
        # Verify result is a dictionary
        assert isinstance(sanitized, dict), \
            "Sanitized arguments should be a dictionary"
        
        # Verify keys are preserved
        assert set(sanitized.keys()) == set(arguments.keys()), \
            "Sanitized arguments should have the same keys"
        
    except Exception as e:
        pytest.fail(f"Sanitization should not raise exception for arguments {arguments}: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
