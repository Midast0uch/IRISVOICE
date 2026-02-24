"""
Session-aware logging with correlation capabilities for IRISVOICE.

Provides logging that automatically injects session context and enables cross-session tracking.
"""

import asyncio
from typing import Dict, Any, Optional, List
from contextvars import ContextVar
from dataclasses import asdict
from datetime import datetime

from backend.monitoring.structured_logger import StructuredLogger, LogContext
from backend.sessions.session_manager import SessionManager


# Context variables for automatic session tracking
_current_session_id: ContextVar[Optional[str]] = ContextVar("session_id", default=None)
_current_workspace_id: ContextVar[Optional[str]] = ContextVar("workspace_id", default=None)
_current_user_id: ContextVar[Optional[str]] = ContextVar("user_id", default=None)
_current_request_id: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


class SessionAwareLogger:
    """Logger that automatically injects session context from context variables."""

    def __init__(self, base_logger: StructuredLogger, session_manager: Optional[SessionManager] = None):
        """
        Initialize session-aware logger.

        Args:
            base_logger: The underlying structured logger
            session_manager: Optional session manager for additional context
        """
        self.base_logger = base_logger
        self.session_manager = session_manager
        self._session_context_cache: Dict[str, Dict[str, Any]] = {}

    def _get_current_context(self) -> LogContext:
        """Get current context from context variables."""
        return LogContext(
            session_id=_current_session_id.get(),
            workspace_id=_current_workspace_id.get(),
            user_id=_current_user_id.get(),
            request_id=_current_request_id.get()
        )

    def _enrich_with_session_data(self, context: LogContext) -> LogContext:
        """Enrich context with additional session data if available."""
        if self.session_manager and context.session_id:
            session = self.session_manager.get_session(context.session_id)
            if session:
                # Add session-specific context
                if not context.workspace_id and hasattr(session, 'workspace_id'):
                    context.workspace_id = session.workspace_id
                if not context.user_id and hasattr(session, 'user_id'):
                    context.user_id = session.user_id

                # Cache session context for performance
                if context.session_id not in self._session_context_cache:
                    self._session_context_cache[context.session_id] = {
                        "session_type": getattr(session, 'session_type', 'unknown'),
                        "created_at": getattr(session, 'created_at', None),
                        "memory_usage": getattr(session, 'memory_usage', None)
                    }

        return context

    def debug(self, message: str, **kwargs) -> None:
        """Log debug message with session context."""
        context = self._get_current_context()
        enriched_context = self._enrich_with_session_data(context)
        self.base_logger.set_context(**asdict(enriched_context))
        self.base_logger.debug(message, **kwargs)

    def info(self, message: str, **kwargs) -> None:
        """Log info message with session context."""
        context = self._get_current_context()
        enriched_context = self._enrich_with_session_data(context)
        self.base_logger.set_context(**asdict(enriched_context))
        self.base_logger.info(message, **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        """Log warning message with session context."""
        context = self._get_current_context()
        enriched_context = self._enrich_with_session_data(context)
        self.base_logger.set_context(**asdict(enriched_context))
        self.base_logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs) -> None:
        """Log error message with session context."""
        context = self._get_current_context()
        enriched_context = self._enrich_with_session_data(context)
        self.base_logger.set_context(**asdict(enriched_context))
        self.base_logger.error(message, **kwargs)

    def critical(self, message: str, **kwargs) -> None:
        """Log critical message with session context."""
        context = self._get_current_context()
        enriched_context = self._enrich_with_session_data(context)
        self.base_logger.set_context(**asdict(enriched_context))
        self.base_logger.critical(message, **kwargs)

    def security_event(self, event_type: str, details: Dict[str, Any], **kwargs) -> None:
        """Log security event with session context."""
        context = self._get_current_context()
        enriched_context = self._enrich_with_session_data(context)
        enriched_context.security_level = "SECURITY_EVENT"
        self.base_logger.set_context(**asdict(enriched_context))
        self.base_logger.security_event(event_type, details, **kwargs)

    def session_event(self, event_type: str, session_id: str, details: Dict[str, Any], **kwargs) -> None:
        """Log session-specific event."""
        context = LogContext(session_id=session_id)
        enriched_context = self._enrich_with_session_data(context)
        self.base_logger.set_context(**asdict(enriched_context))
        
        kwargs.update({
            "session_event": True,
            "event_type": event_type,
            "details": details
        })
        self.base_logger.info(f"Session event: {event_type}", **kwargs)

    def clear_session_cache(self, session_id: str) -> None:
        """Clear cached session context."""
        if session_id in self._session_context_cache:
            del self._session_context_cache[session_id]


# Context management functions
async def set_session_context(session_id: str, workspace_id: Optional[str] = None,
                             user_id: Optional[str] = None, request_id: Optional[str] = None) -> None:
    """Set session context for the current async context."""
    _current_session_id.set(session_id)
    if workspace_id:
        _current_workspace_id.set(workspace_id)
    if user_id:
        _current_user_id.set(user_id)
    if request_id:
        _current_request_id.set(request_id)


def clear_session_context() -> None:
    """Clear all session context."""
    _current_session_id.set(None)
    _current_workspace_id.set(None)
    _current_user_id.set(None)
    _current_request_id.set(None)


def get_session_context() -> Dict[str, Any]:
    """Get current session context as a dictionary."""
    return {
        "session_id": _current_session_id.get(),
        "workspace_id": _current_workspace_id.get(),
        "user_id": _current_user_id.get(),
        "request_id": _current_request_id.get()
    }


# Decorator for automatic session context
async def with_session_logging(session_id: str, workspace_id: Optional[str] = None,
                              user_id: Optional[str] = None, request_id: Optional[str] = None):
    """Decorator that automatically sets session context for a function."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            await set_session_context(session_id, workspace_id, user_id, request_id)
            try:
                return await func(*args, **kwargs)
            finally:
                clear_session_context()
        return wrapper
    return decorator


# Example usage
if __name__ == "__main__":
    from backend.monitoring.structured_logger import configure_logging
    import asyncio

    async def example_usage():
        # Configure logging
        base_logger = configure_logging(log_level="INFO")
        session_logger = SessionAwareLogger(base_logger)

        # Set session context
        await set_session_context(
            session_id="session_123",
            workspace_id="workspace_456",
            user_id="user_789"
        )

        # Log messages with automatic session context
        session_logger.info("User logged in")
        session_logger.debug("Processing request")
        session_logger.warning("Rate limit approaching")

        # Log security event
        session_logger.security_event("permission_denied", {
            "resource": "/admin/settings",
            "required_permission": "admin"
        })

        # Clear context
        clear_session_context()
        session_logger.info("Session context cleared")

    # Run example
    asyncio.run(example_usage())