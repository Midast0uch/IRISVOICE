"""
Behavior Manager - Handles confirmation dialogs, undo history, error handling
"""
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
import time


@dataclass
class UndoAction:
    """A record of an action that can be undone"""
    id: str
    action_type: str
    description: str
    timestamp: float
    data: Dict[str, Any] = field(default_factory=dict)


class BehaviorManager:
    """
    Manages application behavior settings:
    - Confirmation dialogs for destructive actions
    - Undo/redo history
    - Error notification preferences
    - Auto-save settings
    """
    
    _instance: Optional['BehaviorManager'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, max_undo: int = 50):
        if BehaviorManager._initialized:
            return
        
        self.config = {
            "confirm_destructive": True,
            "undo_history": 10,
            "error_notifications": "Popup",  # Popup / Banner / Silent
            "auto_save": True,
        }
        
        # Undo/redo stacks
        self._undo_stack: List[UndoAction] = []
        self._redo_stack: List[UndoAction] = []
        self._max_undo = max_undo
        
        BehaviorManager._initialized = True
    
    def update_config(self, **kwargs) -> None:
        """Update behavior configuration"""
        for key, value in kwargs.items():
            if key in self.config:
                self.config[key] = value
        
        # Update max_undo if changed
        if "undo_history" in kwargs:
            self._max_undo = max(0, min(50, int(kwargs["undo_history"])))
    
    def get_config(self) -> Dict[str, Any]:
        """Get current behavior configuration"""
        return self.config.copy()
    
    # ---------------------------------------------------------------------
    # Confirmation Dialogs
    # ---------------------------------------------------------------------
    
    def should_confirm(self, action_type: str) -> bool:
        """Check if a confirmation dialog should be shown"""
        if not self.config.get("confirm_destructive", True):
            return False
        
        destructive_actions = [
            "delete", "remove", "clear", "reset", "shutdown", "restart",
            "format", "overwrite", "permanent_delete"
        ]
        
        return any(d in action_type.lower() for d in destructive_actions)
    
    # ---------------------------------------------------------------------
    # Undo/Redo System
    # ---------------------------------------------------------------------
    
    def record_action(self, action_type: str, description: str, data: Dict[str, Any] = None) -> str:
        """Record an action for potential undo"""
        import uuid
        
        action = UndoAction(
            id=str(uuid.uuid4())[:8],
            action_type=action_type,
            description=description,
            timestamp=time.time(),
            data=data or {}
        )
        
        self._undo_stack.append(action)
        
        # Clear redo stack when new action is recorded
        self._redo_stack.clear()
        
        # Trim undo stack if needed
        if len(self._undo_stack) > self._max_undo:
            self._undo_stack = self._undo_stack[-self._max_undo:]
        
        return action.id
    
    def can_undo(self) -> bool:
        """Check if undo is available"""
        return len(self._undo_stack) > 0
    
    def can_redo(self) -> bool:
        """Check if redo is available"""
        return len(self._redo_stack) > 0
    
    def undo(self) -> Optional[UndoAction]:
        """Pop and return the last action for undoing"""
        if not self._undo_stack:
            return None
        
        action = self._undo_stack.pop()
        self._redo_stack.append(action)
        return action
    
    def redo(self) -> Optional[UndoAction]:
        """Pop and return the last undone action for redoing"""
        if not self._redo_stack:
            return None
        
        action = self._redo_stack.pop()
        self._undo_stack.append(action)
        return action
    
    def get_undo_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent undoable actions"""
        actions = self._undo_stack[-limit:]
        return [
            {
                "id": a.id,
                "type": a.action_type,
                "description": a.description,
                "timestamp": a.timestamp
            }
            for a in reversed(actions)  # Most recent first
        ]
    
    def clear_history(self) -> None:
        """Clear all undo/redo history"""
        self._undo_stack.clear()
        self._redo_stack.clear()
    
    # ---------------------------------------------------------------------
    # Error Handling
    # ---------------------------------------------------------------------
    
    def get_error_notification_type(self) -> str:
        """Get preferred error notification type"""
        return self.config.get("error_notifications", "Popup")
    
    def should_auto_save(self) -> bool:
        """Check if auto-save is enabled"""
        return self.config.get("auto_save", True)


def get_behavior_manager() -> BehaviorManager:
    """Get the singleton BehaviorManager instance"""
    return BehaviorManager()
