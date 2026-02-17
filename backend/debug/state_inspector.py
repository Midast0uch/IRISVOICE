
import json
from typing import Dict, Any, Optional, List
from datetime import datetime

class StateInspector:
    """
    Provides tools for inspecting and analyzing session states in real-time.
    This tool helps debug state-related issues and understand session behavior.
    """

    def __init__(self, session_manager, state_manager):
        self.session_manager = session_manager
        self.state_manager = state_manager

    async def get_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Gets the complete state of a specific session."""
        session = self.session_manager.get_session(session_id)
        if not session:
            return None
        
        iris_state = await self.state_manager.get_state(session_id)
        if iris_state:
            # Convert IRISState to dict for inspection
            return iris_state.model_dump() if hasattr(iris_state, 'model_dump') else dict(iris_state)
        return None

    async def get_all_sessions_summary(self) -> Dict[str, Any]:
        """Gets a summary of all active sessions."""
        sessions = self.session_manager.sessions
        summary = {}
        
        for session_id, session in sessions.items():
            state = await self.get_session_state(session_id)
            summary[session_id] = {
                "session_type": session.session_type.name,
                "created_at": session.config.created_at.isoformat(),
                "last_accessed_at": session.config.last_accessed.isoformat(),
                "is_active": session.is_active,
                "memory_usage": await self.state_manager.get_memory_usage(session_id)
            }
        
        return summary

    async def compare_session_states(self, session_id1: str, session_id2: str) -> Dict[str, Any]:
        """Compares the states of two sessions."""
        state1 = await self.get_session_state(session_id1)
        state2 = await self.get_session_state(session_id2)
        
        if not state1 or not state2:
            return {"error": "One or both sessions not found"}
        
        differences = []
        all_keys = set(state1.keys()) | set(state2.keys())
        
        for key in all_keys:
            val1 = state1.get(key)
            val2 = state2.get(key)
            
            if val1 != val2:
                differences.append({
                    "key": key,
                    "session1_value": val1,
                    "session2_value": val2
                })
        
        return {
            "session1_id": session_id1,
            "session2_id": session_id2,
            "total_differences": len(differences),
            "differences": differences
        }

    async def query_state(self, session_id: str, query_path: str) -> Optional[Any]:
        """
        Queries a specific path within a session's state.
        Query path format: "field.subfield.key"
        """
        state = await self.get_session_state(session_id)
        if not state:
            return None
        
        parts = query_path.split('.')
        current = state
        
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        
        return current

    async def export_session_state(self, session_id: str, export_path: str) -> bool:
        """Exports a session's state to a JSON file."""
        state = await self.get_session_state(session_id)
        if not state:
            return False
        
        try:
            with open(export_path, 'w') as f:
                json.dump(state, f, indent=2, default=str)
            return True
        except (IOError, TypeError) as e:
            print(f"Error exporting session state: {e}")
            return False
