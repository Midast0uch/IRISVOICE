"""
Handles session-specific configuration loading and management.
"""
import json
from pathlib import Path
from typing import Dict, Any, Optional
from .session_types import SessionType

class SessionConfigLoader:
    """Loads and manages session-specific configuration."""
    
    def __init__(self, config_dir: Path = None):
        self.config_dir = config_dir or Path("config/sessions")
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._configs: Dict[str, Dict[str, Any]] = {}
    
    def load_config(self, session_type: SessionType) -> Dict[str, Any]:
        """Load configuration for a specific session type."""
        config_file = self.config_dir / f"{session_type.name.lower()}_config.json"
        
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading config for {session_type.name}: {e}")
                return self._get_default_config(session_type)
        else:
            return self._get_default_config(session_type)
    
    def save_config(self, session_type: SessionType, config: Dict[str, Any]) -> bool:
        """Save configuration for a specific session type."""
        config_file = self.config_dir / f"{session_type.name.lower()}_config.json"
        
        try:
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
            return True
        except IOError as e:
            print(f"Error saving config for {session_type.name}: {e}")
            return False
    
    def get_session_config(self, session_id: str, session_type: SessionType) -> Dict[str, Any]:
        """Get configuration for a specific session."""
        cache_key = f"{session_id}_{session_type.name}"
        
        if cache_key not in self._configs:
            base_config = self.load_config(session_type)
            self._configs[cache_key] = base_config.copy()
        
        return self._configs[cache_key]
    
    def update_session_config(self, session_id: str, session_type: SessionType, 
                            updates: Dict[str, Any]) -> bool:
        """Update configuration for a specific session."""
        cache_key = f"{session_id}_{session_type.name}"
        
        if cache_key not in self._configs:
            self._configs[cache_key] = self.load_config(session_type)
        
        self._configs[cache_key].update(updates)
        return True
    
    def _get_default_config(self, session_type: SessionType) -> Dict[str, Any]:
        """Get default configuration for a session type."""
        defaults = {
            SessionType.MAIN: {
                "name": "Main Session",
                "description": "Full access session with all features enabled",
                "features": {
                    "file_management": True,
                    "gui_automation": True,
                    "system_commands": True,
                    "vision": True,
                    "web_access": True
                },
                "limits": {
                    "max_memory_mb": 512,
                    "max_file_size_mb": 100,
                    "max_concurrent_operations": 10
                },
                "security": {
                    "require_confirmation": False,
                    "allow_dangerous_commands": True,
                    "log_all_operations": True
                }
            },
            SessionType.VISION: {
                "name": "Vision Session",
                "description": "Session optimized for vision and automation tasks",
                "features": {
                    "file_management": True,
                    "gui_automation": True,
                    "system_commands": False,
                    "vision": True,
                    "web_access": False
                },
                "limits": {
                    "max_memory_mb": 256,
                    "max_file_size_mb": 50,
                    "max_concurrent_operations": 5
                },
                "security": {
                    "require_confirmation": True,
                    "allow_dangerous_commands": False,
                    "log_all_operations": True
                }
            },
            SessionType.ISOLATED: {
                "name": "Isolated Session",
                "description": "Restricted session for safe operations",
                "features": {
                    "file_management": True,
                    "gui_automation": False,
                    "system_commands": False,
                    "vision": False,
                    "web_access": False
                },
                "limits": {
                    "max_memory_mb": 128,
                    "max_file_size_mb": 10,
                    "max_concurrent_operations": 2
                },
                "security": {
                    "require_confirmation": True,
                    "allow_dangerous_commands": False,
                    "log_all_operations": True
                }
            }
        }
        
        return defaults.get(session_type, defaults[SessionType.MAIN])
