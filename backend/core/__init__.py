"""
IRIS Backend Core Module

This module contains core infrastructure components for the IRIS backend:
- WebSocket management
- Session management
- State management
- Structured logging
"""

__all__ = [
    'get_websocket_manager',
    'get_session_manager',
    'get_state_manager',
    'get_structured_logger'
]

# Re-export managers from their original locations for backward compatibility
from backend.ws_manager import get_websocket_manager
from backend.sessions import get_session_manager
from backend.state_manager import get_state_manager

# Import structured logger
from backend.monitoring.structured_logger import get_structured_logger
