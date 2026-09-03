
"""
Session Configuration Management

Provides session-specific configuration management with inheritance
from workspace configurations and per-session overrides.
"""

import logging
from typing import Dict, Any, Optional
from backend.config.config_loader import ConfigurationLoader
from backend.sessions.session_manager import SessionManager

logger = logging.getLogger(__name__)


class SessionConfigurationManager:
    """Manages per-session configuration with workspace inheritance."""

    def __init__(self, config_loader: ConfigurationLoader, session_manager: SessionManager):
        """Initialize session configuration manager."""
        self.config_loader = config_loader
        self.session_manager = session_manager
        self.session_configs: Dict[str, Dict[str, Any]] = {}

        logger.info("Session configuration manager initialized.")

    async def get_session_config(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get the complete configuration for a session."""
        if session_id in self.session_configs:
            return self.session_configs[session_id].copy()

        # Load workspace configuration
        session = self.session_manager.get_session(session_id)
        if not session:
            logger.error(f"Session {session_id} not found.")
            return None

        workspace_config = await self.config_loader.load_configuration(session_id)
        if not workspace_config:
            logger.warning(f"No workspace configuration found for session {session_id}.")
            return self._get_default_session_config()

        # Merge workspace config with session-specific overrides
        session_config = workspace_config.to_dict()
        if session_id in self.session_configs:
            session_config.update(self.session_configs[session_id])

        return session_config

    async def update_session_config(self, session_id: str, updates: Dict[str, Any]) -> bool:
        """Update session-specific configuration overrides."""
        try:
            if session_id not in self.session_configs:
                self.session_configs[session_id] = {}

            self.session_configs[session_id].update(updates)
            logger.info(f"Updated session configuration for {session_id}.")
            return True
        except Exception as e:
            logger.error(f"Failed to update session configuration for {session_id}: {e}")
            return False

    async def reset_session_config(self, session_id: str) -> bool:
        """Reset session configuration to workspace defaults."""
        try:
            if session_id in self.session_configs:
                del self.session_configs[session_id]
                logger.info(f"Reset session configuration for {session_id} to workspace defaults.")
                return True
            return True  # Nothing to reset
        except Exception as e:
            logger.error(f"Failed to reset session configuration for {session_id}: {e}")
            return False

    async def get_session_setting(self, session_id: str, section: str, setting: str, default: Any = None) -> Any:
        """Get a specific setting for a session."""
        session_config = await self.get_session_config(session_id)
        if not session_config:
            return default

        # Check session-specific overrides first
        if session_id in self.session_configs:
            session_overrides = self.session_configs[session_id]
            if section in session_overrides and setting in session_overrides[section]:
                return session_overrides[section][setting]

        # Fall back to workspace configuration
        if section in session_config.get("sections", {}):
            return session_config["sections"][section].get("settings", {}).get(setting, default)

        return default

    async def set_session_setting(self, session_id: str, section: str, setting: str, value: Any) -> bool:
        """Set a specific setting for a session."""
        try:
            if session_id not in self.session_configs:
                self.session_configs[session_id] = {}

            if section not in self.session_configs[session_id]:
                self.session_configs[session_id][section] = {}

            self.session_configs[session_id][section][setting] = value
            logger.info(f"Set session setting {section}.{setting} for {session_id}.")
            return True
        except Exception as e:
            logger.error(f"Failed to set session setting for {session_id}: {e}")
            return False

    def _get_default_session_config(self) -> Dict[str, Any]:
        """Get default session configuration."""
        return {
            "session": {
                "session_timeout_minutes": 60,
                "max_concurrent_sessions": 5,
                "enable_session_isolation": True,
                "memory_limit_mb": 512,
                "auto_cleanup_inactive": True,
                "inactive_cleanup_interval_minutes": 15
            },
            "security": {
                "enable_security_checks": True,
                "max_file_size_mb": 100,
                "allowed_file_types": ["txt", "json", "yaml", "py", "md"],
                "enable_audit_logging": True,
                "audit_log_retention_days": 90,
                "enable_rate_limiting": True,
                "rate_limit_requests_per_minute": 60
            }
        }

    async def cleanup_session_config(self, session_id: str):
        """Clean up session configuration when session is destroyed."""
        if session_id in self.session_configs:
            del self.session_configs[session_id]
            logger.info(f"Cleaned up session configuration for {session_id}.")
