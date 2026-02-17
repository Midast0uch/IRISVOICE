"""
IRIS State Manager (Session-Aware)
Acts as a facade to the session-based state management system.
"""
import asyncio
from typing import Any, Dict, Optional, List

from .models import IRISState, Category, ConfirmedNode, ColorTheme
from .sessions import get_session_manager, SessionManager, IRISession


class StateManager:
    """
    Session-aware state manager for IRIS backend.
    Delegates state operations to the appropriate session's IsolatedStateManager.
    """
    
    def __init__(self, session_manager: Optional[SessionManager] = None):
        self._session_manager = session_manager or get_session_manager()
    
    async def _get_session_state_manager(self, session_id: str):
        """Get the isolated state manager for a session"""
        session = self._session_manager.get_session(session_id)
        if session and session.state_manager:
            return session.state_manager
        return None
    
    async def get_state(self, session_id: str) -> Optional[IRISState]:
        """Get a copy of the state for a session"""
        state_manager = await self._get_session_state_manager(session_id)
        if state_manager:
            return await state_manager.get_state_copy()
        return None
    
    # ========================================================================
    # State Modification Methods (Delegated)
    # ========================================================================
    
    async def set_category(self, session_id: str, category: Optional[Category]) -> None:
        """Set current category for a session"""
        state_manager = await self._get_session_state_manager(session_id)
        if state_manager:
            await state_manager.set_category(category)
    
    async def set_subnode(self, session_id: str, subnode_id: Optional[str]) -> None:
        """Set current subnode for a session"""
        state_manager = await self._get_session_state_manager(session_id)
        if state_manager:
            await state_manager.set_subnode(subnode_id)
    
    async def update_field(self, session_id: str, subnode_id: str, field_id: str, value: Any) -> bool:
        """Update a field value for a session"""
        state_manager = await self._get_session_state_manager(session_id)
        if state_manager:
            return await state_manager.update_field(subnode_id, field_id, value)
        return False
    
    async def confirm_subnode(self, session_id: str, category: str, subnode_id: str, values: Dict[str, Any]) -> Optional[float]:
        """Confirm a subnode for a session"""
        state_manager = await self._get_session_state_manager(session_id)
        if state_manager:
            return await state_manager.confirm_subnode(category, subnode_id, values)
        return None
    
    async def update_theme(self, session_id: str, glow_color: Optional[str] = None, font_color: Optional[str] = None, state_colors: Optional[dict] = None) -> None:
        """Update theme for a session"""
        state_manager = await self._get_session_state_manager(session_id)
        if state_manager:
            await state_manager.update_theme(glow_color, font_color, state_colors)
    
    async def clear_confirmed_nodes(self, session_id: str) -> None:
        """Clear all confirmed nodes for a session"""
        state_manager = await self._get_session_state_manager(session_id)
        if state_manager:
            await state_manager.clear_confirmed_nodes()
    
    # ========================================================================
    # Persistence Methods (Delegated)
    # ========================================================================
    
    async def initialize_session_state(self, session_id: str, persistence_dir: Optional[str] = None):
        """Initialize the state for a new session, including loading from persistence"""
        state_manager = await self._get_session_state_manager(session_id)
        if state_manager:
            await state_manager.initialize(persistence_dir)
    
    async def cleanup_session_state(self, session_id: str):
        """Clean up and persist state for a session"""
        state_manager = await self._get_session_state_manager(session_id)
        if state_manager:
            await state_manager.cleanup()
    
    # ========================================================================
    # Utility Methods (Delegated)
    # ========================================================================
    
    async def get_field_value(self, session_id: str, subnode_id: str, field_id: str, default: Any = None) -> Any:
        """Get a specific field value for a session"""
        state_manager = await self._get_session_state_manager(session_id)
        if state_manager:
            return await state_manager.get_field_value(subnode_id, field_id, default)
        return default
    
    async def get_subnode_field_values(self, session_id: str, subnode_id: str) -> Dict[str, Any]:
        """Get all field values for a subnode"""
        state_manager = await self._get_session_state_manager(session_id)
        if state_manager:
            return await state_manager.get_subnode_field_values(subnode_id)
        return {}

    async def get_memory_usage(self, session_id: str) -> int:
        """Get the memory usage of a session in bytes."""
        session = await self._get_session_state_manager(session_id)
        if session:
            return await session.get_memory_usage()
        return 0
    
    async def get_category_field_values(self, session_id: str, category: str) -> Dict[str, Dict[str, Any]]:
        """Get all field values for a category in a session"""
        state_manager = await self._get_session_state_manager(session_id)
        if state_manager:
            return await state_manager.get_category_field_values(category)
        return {}


# Global instance for convenience, but session-aware
_state_manager_instance: Optional[StateManager] = None

def get_state_manager() -> StateManager:
    """Get the global state manager facade"""
    global _state_manager_instance
    if _state_manager_instance is None:
        _state_manager_instance = StateManager()
    return _state_manager_instance
