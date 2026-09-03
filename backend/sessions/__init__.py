"""
IRIS Session Management Module
Provides session-based state isolation and memory management
"""
from .session_manager import (
    SessionManager,
    IRISession,
    SessionConfig,
    get_session_manager,
    create_session_manager
)
from .state_isolation import IsolatedStateManager
from .memory_bounds import (
    MemoryBounds,
    MemoryTracker,
    GlobalMemoryManager,
    MemorySnapshot,
    get_global_memory_manager
)

__all__ = [
    "SessionManager",
    "IRISession", 
    "SessionConfig",
    "get_session_manager",
    "create_session_manager",
    "IsolatedStateManager",
    "MemoryBounds",
    "MemoryTracker", 
    "GlobalMemoryManager",
    "MemorySnapshot",
    "get_global_memory_manager"
]