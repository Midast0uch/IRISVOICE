#!/usr/bin/env python3
"""
Agent Exceptions

Custom exceptions for the agent system with proper error codes and messages.
"""

from typing import Any, Dict, List, Optional
from enum import Enum


class ErrorCode(Enum):
    """Error codes for the agent system."""
    # Model errors (1000-1099)
    MODEL_NOT_FOUND = 1001
    MODEL_LOAD_FAILED = 1002
    MODEL_NOT_LOADED = 1003
    MODEL_GENERATION_FAILED = 1004

    # Communication errors (2000-2099)
    COMMUNICATION_FAILED = 2001
    MESSAGE_PARSE_ERROR = 2002
    TIMEOUT = 2003
    INVALID_REQUEST = 2004
    REQUEST_REJECTED = 2005

    # Tool errors (3000-3099)
    TOOL_NOT_FOUND = 3001
    TOOL_EXECUTION_FAILED = 3002
    TOOL_VALIDATION_FAILED = 3003
    TOOL_TIMEOUT = 3004

    # Configuration errors (4000-4099)
    CONFIG_NOT_FOUND = 4001
    CONFIG_INVALID = 4002
    CONFIG_LOAD_FAILED = 4003

    # System errors (5000-5099)
    INITIALIZATION_FAILED = 5001
    RESOURCE_UNAVAILABLE = 5002
    INTERNAL_ERROR = 5003


class AgentException(Exception):
    """Base exception for agent system."""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary."""
        return {
            "error": self.message,
            "code": self.code.value,
            "code_name": self.code.name,
            "details": self.details
        }


class ModelLoadError(AgentException):
    """Raised when a model fails to load."""

    def __init__(self, model_id: str, reason: str, details: Optional[Dict] = None):
        super().__init__(
            message=f"Failed to load model '{model_id}': {reason}",
            code=ErrorCode.MODEL_LOAD_FAILED,
            details=details or {"model_id": model_id, "reason": reason}
        )


class ModelNotFoundError(AgentException):
    """Raised when a requested model is not found."""

    def __init__(self, model_id: str, available_models: Optional[List[str]] = None):
        super().__init__(
            message=f"Model '{model_id}' not found",
            code=ErrorCode.MODEL_NOT_FOUND,
            details={"model_id": model_id, "available_models": available_models or []}
        )


class ModelNotLoadedError(AgentException):
    """Raised when attempting to use a model that hasn't been loaded."""

    def __init__(self, model_id: str):
        super().__init__(
            message=f"Model '{model_id}' is not loaded",
            code=ErrorCode.MODEL_NOT_LOADED,
            details={"model_id": model_id}
        )


class ModelGenerationError(AgentException):
    """Raised when model generation fails."""

    def __init__(self, model_id: str, reason: str):
        super().__init__(
            message=f"Generation failed for model '{model_id}': {reason}",
            code=ErrorCode.MODEL_GENERATION_FAILED,
            details={"model_id": model_id, "reason": reason}
        )


class CommunicationError(AgentException):
    """Raised when inter-model communication fails."""

    def __init__(self, reason: str, from_model: str = "", to_model: str = ""):
        super().__init__(
            message=f"Communication failed: {reason}",
            code=ErrorCode.COMMUNICATION_FAILED,
            details={"from_model": from_model, "to_model": to_model}
        )


class MessageParseError(AgentException):
    """Raised when a message cannot be parsed."""

    def __init__(self, raw_message: str, reason: str):
        super().__init__(
            message=f"Failed to parse message: {reason}",
            code=ErrorCode.MESSAGE_PARSE_ERROR,
            details={"raw_message": raw_message[:200]}  # Truncate for logging
        )


class TimeoutError(AgentException):
    """Raised when an operation times out."""

    def __init__(self, operation: str, timeout_seconds: float):
        super().__init__(
            message=f"Operation '{operation}' timed out after {timeout_seconds}s",
            code=ErrorCode.TIMEOUT,
            details={"operation": operation, "timeout_seconds": timeout_seconds}
        )


class InvalidRequestError(AgentException):
    """Raised when a request is invalid or malformed."""

    def __init__(self, reason: str, request_id: str = ""):
        super().__init__(
            message=f"Invalid request: {reason}",
            code=ErrorCode.INVALID_REQUEST,
            details={"request_id": request_id}
        )


class ToolNotFoundError(AgentException):
    """Raised when a requested tool is not found."""

    def __init__(self, tool_name: str, available_tools: Optional[List[str]] = None):
        super().__init__(
            message=f"Tool '{tool_name}' not found",
            code=ErrorCode.TOOL_NOT_FOUND,
            details={"tool_name": tool_name, "available_tools": available_tools or []}
        )


class ToolExecutionError(AgentException):
    """Raised when tool execution fails."""

    def __init__(self, tool_name: str, reason: str):
        super().__init__(
            message=f"Tool '{tool_name}' execution failed: {reason}",
            code=ErrorCode.TOOL_EXECUTION_FAILED,
            details={"tool_name": tool_name, "reason": reason}
        )


class ToolValidationError(AgentException):
    """Raised when tool parameter validation fails."""

    def __init__(self, tool_name: str, reason: str, invalid_params: Optional[List[str]] = None):
        super().__init__(
            message=f"Tool '{tool_name}' validation failed: {reason}",
            code=ErrorCode.TOOL_VALIDATION_FAILED,
            details={"tool_name": tool_name, "invalid_params": invalid_params or []}
        )


class ConfigError(AgentException):
    """Raised when there's a configuration error."""

    def __init__(self, reason: str, config_path: str = ""):
        super().__init__(
            message=f"Configuration error: {reason}",
            code=ErrorCode.CONFIG_INVALID,
            details={"config_path": config_path}
        )


class InitializationError(AgentException):
    """Raised when system initialization fails."""

    def __init__(self, component: str, reason: str):
        super().__init__(
            message=f"Failed to initialize {component}: {reason}",
            code=ErrorCode.INITIALIZATION_FAILED,
            details={"component": component, "reason": reason}
        )


# Helper function to format exception for JSON response
def format_exception_for_response(exc: Exception) -> Dict[str, Any]:
    """Format an exception for JSON response."""
    if isinstance(exc, AgentException):
        return exc.to_dict()

    return {
        "error": str(exc),
        "code": ErrorCode.INTERNAL_ERROR.value,
        "code_name": ErrorCode.INTERNAL_ERROR.name,
        "details": {"type": type(exc).__name__}
    }
