"""
Structured logging system for IRISVOICE.

Provides JSON-formatted logging with session context injection and security event tracking.
"""

import json
import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict


@dataclass
class LogContext:
    """Context information to be injected into log messages."""
    session_id: Optional[str] = None
    workspace_id: Optional[str] = None
    user_id: Optional[str] = None
    request_id: Optional[str] = None
    component: Optional[str] = None
    security_level: Optional[str] = None


class StructuredFormatter(logging.Formatter):
    """Custom formatter that outputs structured JSON logs."""

    def __init__(self, context: Optional[LogContext] = None):
        super().__init__()
        self.context = context or LogContext()

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON."""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add context information
        if self.context.session_id:
            log_entry["session_id"] = self.context.session_id
        if self.context.workspace_id:
            log_entry["workspace_id"] = self.context.workspace_id
        if self.context.user_id:
            log_entry["user_id"] = self.context.user_id
        if self.context.request_id:
            log_entry["request_id"] = self.context.request_id
        if self.context.component:
            log_entry["component"] = self.context.component
        if self.context.security_level:
            log_entry["security_level"] = self.context.security_level

        # Add exception information if present
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info)
            }

        # Add extra fields from record
        for key, value in record.__dict__.items():
            if key not in ("name", "msg", "args", "levelname", "levelno", "pathname", "filename",
                          "module", "lineno", "funcName", "created", "msecs", "relativeCreated",
                          "thread", "threadName", "processName", "process", "getMessage",
                          "exc_info", "exc_text", "stack_info") and not key.startswith("_"):
                log_entry[key] = value

        return json.dumps(log_entry, ensure_ascii=False)


class StructuredLogger:
    """Structured logging system with context injection."""

    def __init__(self, name: str, log_level: str = "INFO", log_file: Optional[Path] = None,
                 max_bytes: int = 10 * 1024 * 1024, backup_count: int = 5):
        """
        Initialize the structured logger.

        Args:
            name: Logger name
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            log_file: Optional log file path
            max_bytes: Maximum bytes per log file (for rotation)
            backup_count: Number of backup files to keep
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, log_level.upper()))
        self.context = LogContext()

        # Clear existing handlers to avoid duplicates
        self.logger.handlers.clear()

        # Create formatter
        formatter = StructuredFormatter(self.context)

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        # File handler if specified
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=max_bytes, backupCount=backup_count
            )
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    def set_context(self, **kwargs) -> None:
        """Set context information for subsequent log messages."""
        for key, value in kwargs.items():
            if hasattr(self.context, key):
                setattr(self.context, key, value)

    def clear_context(self) -> None:
        """Clear all context information."""
        self.context = LogContext()

    def debug(self, message: str, **kwargs) -> None:
        """Log a debug message."""
        self._log_with_extras(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs) -> None:
        """Log an info message."""
        self._log_with_extras(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        """Log a warning message."""
        self._log_with_extras(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs) -> None:
        """Log an error message."""
        self._log_with_extras(logging.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs) -> None:
        """Log a critical message."""
        self._log_with_extras(logging.CRITICAL, message, **kwargs)

    def security_event(self, event_type: str, details: Dict[str, Any], **kwargs) -> None:
        """Log a security event with structured details."""
        kwargs.update({
            "event_type": event_type,
            "security_event": True,
            "details": details
        })
        self._log_with_extras(logging.WARNING, f"Security event: {event_type}", **kwargs)

    def performance_metric(self, metric_name: str, value: float, unit: str, **kwargs) -> None:
        """Log a performance metric."""
        kwargs.update({
            "metric_name": metric_name,
            "metric_value": value,
            "metric_unit": unit,
            "performance_metric": True
        })
        self._log_with_extras(logging.INFO, f"Performance metric: {metric_name}={value}{unit}", **kwargs)

    def _log_with_extras(self, level: int, message: str, **kwargs) -> None:
        """Internal method to log with extra fields."""
        extra = kwargs.copy()
        self.logger.log(level, message, extra=extra)


# Global logger instance
_global_logger: Optional[StructuredLogger] = None


def get_logger(name: str = "irisvoice", **kwargs) -> StructuredLogger:
    """Get or create a global structured logger instance."""
    global _global_logger
    if _global_logger is None:
        _global_logger = StructuredLogger(name, **kwargs)
    return _global_logger


def configure_logging(log_level: str = "INFO", log_file: Optional[Path] = None,
                     log_dir: Optional[Path] = None) -> StructuredLogger:
    """
    Configure global logging settings.

    Args:
        log_level: Logging level
        log_file: Specific log file path
        log_dir: Log directory (will create irisvoice.log inside)

    Returns:
        Configured logger instance
    """
    if log_dir and not log_file:
        log_file = log_dir / "irisvoice.log"

    return get_logger(log_level=log_level, log_file=log_file)


# Example usage and testing
if __name__ == "__main__":
    # Configure logging
    logger = configure_logging(log_level="DEBUG")

    # Set context
    logger.set_context(session_id="test_session_123", workspace_id="workspace_456")

    # Log various message types
    logger.info("Application started successfully")
    logger.debug("Debug information", extra_field="extra_value")
    logger.warning("This is a warning")

    # Log security event
    logger.security_event("unauthorized_access_attempt", {
        "user_id": "unknown_user",
        "resource": "/admin/config",
        "ip_address": "192.168.1.100"
    })

    # Log performance metric
    logger.performance_metric("response_time", 125.5, "ms")

    # Clear context
    logger.clear_context()
    logger.info("Context cleared")