"""
Logging Configuration for IRIS Backend

This module provides centralized logging configuration for all backend components.
It sets up structured logging with JSON formatting, file rotation, and context injection.
"""

import os
from pathlib import Path
from typing import Optional

from backend.monitoring.structured_logger import configure_logging, StructuredLogger


# Default log directory
DEFAULT_LOG_DIR = Path(__file__).parent.parent / "logs"

# Log levels
LOG_LEVEL_DEBUG = "DEBUG"
LOG_LEVEL_INFO = "INFO"
LOG_LEVEL_WARNING = "WARNING"
LOG_LEVEL_ERROR = "ERROR"
LOG_LEVEL_CRITICAL = "CRITICAL"


def setup_backend_logging(
    log_level: Optional[str] = None,
    log_dir: Optional[Path] = None,
    enable_file_logging: bool = True
) -> StructuredLogger:
    """
    Set up logging for the IRIS backend.
    
    This function should be called once during backend initialization to configure
    the global logging system.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
                  Defaults to INFO, or reads from IRIS_LOG_LEVEL env var.
        log_dir: Directory for log files. Defaults to backend/logs/
        enable_file_logging: Whether to enable file logging (default: True)
    
    Returns:
        Configured StructuredLogger instance
    
    Example:
        >>> from backend.core.logging_config import setup_backend_logging
        >>> logger = setup_backend_logging(log_level="DEBUG")
        >>> logger.info("Backend initialized")
    """
    # Get log level from environment or use default
    if log_level is None:
        log_level = os.environ.get("IRIS_LOG_LEVEL", LOG_LEVEL_INFO)
    
    # Get log directory
    if log_dir is None:
        log_dir = Path(os.environ.get("IRIS_LOG_DIR", str(DEFAULT_LOG_DIR)))
    
    # Ensure log directory exists
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Configure logging
    if enable_file_logging:
        log_file = log_dir / "irisvoice.log"
        logger = configure_logging(log_level=log_level, log_file=log_file)
    else:
        logger = configure_logging(log_level=log_level)
    
    logger.info(
        "Logging configured",
        log_level=log_level,
        log_dir=str(log_dir) if enable_file_logging else None,
        file_logging_enabled=enable_file_logging
    )
    
    return logger


def get_component_logger(component_name: str) -> StructuredLogger:
    """
    Get a logger for a specific component with the component name set in context.
    
    Args:
        component_name: Name of the component (e.g., "websocket", "agent", "voice")
    
    Returns:
        StructuredLogger with component context set
    
    Example:
        >>> from backend.core.logging_config import get_component_logger
        >>> logger = get_component_logger("websocket")
        >>> logger.info("WebSocket connection established")
    """
    from backend.monitoring.structured_logger import get_logger
    
    logger = get_logger()
    logger.set_context(component=component_name)
    return logger


# Component-specific logger getters for convenience
def get_websocket_logger() -> StructuredLogger:
    """Get logger for WebSocket components."""
    return get_component_logger("websocket")


def get_session_logger() -> StructuredLogger:
    """Get logger for session management components."""
    return get_component_logger("session")


def get_state_logger() -> StructuredLogger:
    """Get logger for state management components."""
    return get_component_logger("state")


def get_agent_logger() -> StructuredLogger:
    """Get logger for agent components."""
    return get_component_logger("agent")


def get_voice_logger() -> StructuredLogger:
    """Get logger for voice processing components."""
    return get_component_logger("voice")


def get_tool_logger() -> StructuredLogger:
    """Get logger for tool/MCP components."""
    return get_component_logger("tools")


def get_gateway_logger() -> StructuredLogger:
    """Get logger for gateway/routing components."""
    return get_component_logger("gateway")


# Export all
__all__ = [
    'setup_backend_logging',
    'get_component_logger',
    'get_websocket_logger',
    'get_session_logger',
    'get_state_logger',
    'get_agent_logger',
    'get_voice_logger',
    'get_tool_logger',
    'get_gateway_logger',
    'LOG_LEVEL_DEBUG',
    'LOG_LEVEL_INFO',
    'LOG_LEVEL_WARNING',
    'LOG_LEVEL_ERROR',
    'LOG_LEVEL_CRITICAL',
]
