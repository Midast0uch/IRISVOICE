"""
Configuration Loader for IRISVOICE Workspaces

Loads and manages workspace-specific configurations, including default configurations,
user overrides, and configuration validation.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, asdict
import aiofiles

logger = logging.getLogger(__name__)


@dataclass
class ConfigSection:
    """Represents a configuration section."""
    name: str
    settings: Dict[str, Any]
    description: str = ""
    version: str = "1.0"
    last_modified: datetime = None
    
    def __post_init__(self):
        if self.last_modified is None:
            self.last_modified = datetime.now()


@dataclass
class WorkspaceConfiguration:
    """Complete workspace configuration."""
    workspace_id: str
    version: str
    sections: Dict[str, ConfigSection]
    metadata: Dict[str, Any]
    created_at: datetime
    last_modified: datetime
    
    def get_section(self, section_name: str) -> Optional[ConfigSection]:
        """Get a configuration section."""
        return self.sections.get(section_name)
    
    def get_setting(self, section_name: str, setting_name: str, default: Any = None) -> Any:
        """Get a specific setting value."""
        section = self.get_section(section_name)
        if section and setting_name in section.settings:
            return section.settings[setting_name]
        return default
    
    def update_setting(self, section_name: str, setting_name: str, value: Any):
        """Update a specific setting value."""
        if section_name not in self.sections:
            self.sections[section_name] = ConfigSection(
                name=section_name,
                settings={}
            )
        
        self.sections[section_name].settings[setting_name] = value
        self.sections[section_name].last_modified = datetime.now()
        self.last_modified = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "workspace_id": self.workspace_id,
            "version": self.version,
            "sections": {
                name: {
                    "name": section.name,
                    "settings": section.settings,
                    "description": section.description,
                    "version": section.version,
                    "last_modified": section.last_modified.isoformat()
                }
                for name, section in self.sections.items()
            },
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "last_modified": self.last_modified.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkspaceConfiguration":
        """Create from dictionary."""
        sections = {}
        for name, section_data in data.get("sections", {}).items():
            sections[name] = ConfigSection(
                name=section_data["name"],
                settings=section_data["settings"],
                description=section_data.get("description", ""),
                version=section_data.get("version", "1.0"),
                last_modified=datetime.fromisoformat(section_data["last_modified"])
            )
        
        return cls(
            workspace_id=data["workspace_id"],
            version=data.get("version", "1.0"),
            sections=sections,
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]),
            last_modified=datetime.fromisoformat(data["last_modified"])
        )


class ConfigurationLoader:
    """Loads and manages workspace configurations."""
    
    def __init__(self, config_dir: Path):
        """Initialize configuration loader."""
        self.config_dir = config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Default configurations
        self.default_configs = self._load_default_configurations()
        
        logger.info(f"Configuration loader initialized at: {self.config_dir}")
    
    def _load_default_configurations(self) -> Dict[str, ConfigSection]:
        """Load default configuration sections."""
        return {
            "general": ConfigSection(
                name="general",
                description="General workspace settings",
                settings={
                    "auto_save": True,
                    "auto_backup": True,
                    "backup_interval_minutes": 30,
                    "max_backups": 10,
                    "cleanup_temp_files": True,
                    "temp_file_retention_days": 7
                },
                version="1.0"
            ),
            
            "security": ConfigSection(
                name="security",
                description="Security settings",
                settings={
                    "enable_security_checks": True,
                    "max_file_size_mb": 100,
                    "allowed_file_types": ["txt", "json", "yaml", "py", "md"],
                    "enable_audit_logging": True,
                    "audit_log_retention_days": 90,
                    "enable_rate_limiting": True,
                    "rate_limit_requests_per_minute": 60
                },
                version="1.0"
            ),
            
            "session": ConfigSection(
                name="session",
                description="Session management settings",
                settings={
                    "session_timeout_minutes": 60,
                    "max_concurrent_sessions": 5,
                    "enable_session_isolation": True,
                    "memory_limit_mb": 512,
                    "auto_cleanup_inactive": True,
                    "inactive_cleanup_interval_minutes": 15
                },
                version="1.0"
            ),
            
            "vision": ConfigSection(
                name="vision",
                description="Vision system settings",
                settings={
                    "enable_vision_system": True,
                    "screenshot_quality": 85,
                    "enable_arai_tree": True,
                    "max_screenshot_size_mb": 10,
                    "enable_snapshot_cache": True,
                    "snapshot_cache_size": 100,
                    "enable_action_allowlist": True,
                    "enable_sandboxed_execution": True
                },
                version="1.0"
            ),
            
            "automation": ConfigSection(
                name="automation",
                description="Automation settings",
                settings={
                    "enable_automation": True,
                    "max_actions_per_session": 1000,
                    "action_timeout_seconds": 30,
                    "enable_permission_system": True,
                    "auto_approve_safe_actions": True,
                    "enable_action_history": True,
                    "action_history_retention_days": 30
                },
                version="1.0"
            ),
            
            "gateway": ConfigSection(
                name="gateway",
                description="Gateway settings",
                settings={
                    "enable_gateway": True,
                    "enable_message_routing": True,
                    "enable_security_filtering": True,
                    "max_message_size_kb": 64,
                    "enable_rate_limiting": True,
                    "rate_limit_messages_per_second": 10
                },
                version="1.0"
            ),
            
            "workspace": ConfigSection(
                name="workspace",
                description="Workspace structure settings",
                settings={
                    "enable_workspace_isolation": True,
                    "default_workspace_type": "main",
                    "enable_config_versioning": True,
                    "max_workspaces_per_user": 10,
                    "enable_workspace_backup": True,
                    "workspace_backup_interval_hours": 24
                },
                version="1.0"
            )
        }
    
    async def create_configuration(self, workspace_id: str,
                                 workspace_type: str = "main",
                                 overrides: Optional[Dict[str, Dict[str, Any]]] = None) -> WorkspaceConfiguration:
        """Create a new workspace configuration."""
        if overrides is None:
            overrides = {}
        
        # Start with default configuration
        sections = {}
        for section_name, default_section in self.default_configs.items():
            # Apply workspace type specific overrides
            type_overrides = self._get_workspace_type_overrides(workspace_type, section_name)
            user_overrides = overrides.get(section_name, {})
            
            # Merge configurations
            merged_settings = default_section.settings.copy()
            merged_settings.update(type_overrides)
            merged_settings.update(user_overrides)
            
            sections[section_name] = ConfigSection(
                name=section_name,
                settings=merged_settings,
                description=default_section.description,
                version=default_section.version
            )
        
        # Create configuration
        config = WorkspaceConfiguration(
            workspace_id=workspace_id,
            version="1.0",
            sections=sections,
            metadata={
                "workspace_type": workspace_type,
                "created_by": "system",
                "configuration_source": "default_with_overrides"
            },
            created_at=datetime.now(),
            last_modified=datetime.now()
        )
        
        # Save configuration
        await self.save_configuration(config)
        
        logger.info(f"Created configuration for workspace: {workspace_id}")
        return config
    
    def _get_workspace_type_overrides(self, workspace_type: str, section_name: str) -> Dict[str, Any]:
        """Get workspace type specific configuration overrides."""
        overrides = {
            "main": {
                "session": {
                    "session_timeout_minutes": 120,
                    "max_concurrent_sessions": 10
                },
                "vision": {
                    "enable_vision_system": True,
                    "enable_arai_tree": True
                },
                "automation": {
                    "enable_automation": True,
                    "max_actions_per_session": 2000
                }
            },
            "vision": {
                "session": {
                    "session_timeout_minutes": 180,
                    "max_concurrent_sessions": 3
                },
                "vision": {
                    "enable_vision_system": True,
                    "screenshot_quality": 95,
                    "enable_arai_tree": True,
                    "max_screenshot_size_mb": 20
                },
                "automation": {
                    "enable_automation": True,
                    "max_actions_per_session": 5000
                }
            },
            "isolated": {
                "session": {
                    "session_timeout_minutes": 30,
                    "max_concurrent_sessions": 1
                },
                "security": {
                    "enable_security_checks": True,
                    "max_file_size_mb": 50,
                    "enable_audit_logging": True
                },
                "vision": {
                    "enable_vision_system": False,
                    "enable_arai_tree": False
                },
                "automation": {
                    "enable_automation": False,
                    "max_actions_per_session": 100
                }
            }
        }
        
        return overrides.get(workspace_type, {}).get(section_name, {})
    
    async def load_configuration(self, workspace_id: str) -> Optional[WorkspaceConfiguration]:
        """Load workspace configuration from disk."""
        config_file = self.config_dir / f"{workspace_id}_config.json"
        
        if not config_file.exists():
            logger.warning(f"Configuration file not found for workspace: {workspace_id}")
            return None
        
        try:
            async with aiofiles.open(config_file, 'r') as f:
                data = json.loads(await f.read())
            
            config = WorkspaceConfiguration.from_dict(data)
            logger.info(f"Loaded configuration for workspace: {workspace_id}")
            return config
        except Exception as e:
            logger.error(f"Failed to load configuration for workspace {workspace_id}: {e}")
            return None
    
    async def save_configuration(self, config: WorkspaceConfiguration):
        """Save workspace configuration to disk."""
        config_file = self.config_dir / f"{config.workspace_id}_config.json"
        
        try:
            async with aiofiles.open(config_file, 'w') as f:
                await f.write(json.dumps(config.to_dict(), indent=2))
            
            logger.info(f"Saved configuration for workspace: {config.workspace_id}")
        except Exception as e:
            logger.error(f"Failed to save configuration for workspace {config.workspace_id}: {e}")
            raise
    
    async def update_configuration(self, workspace_id: str, section_name: str,
                                 settings: Dict[str, Any]) -> bool:
        """Update specific configuration section."""
        config = await self.load_configuration(workspace_id)
        if not config:
            return False
        
        # Update section
        if section_name not in config.sections:
            config.sections[section_name] = ConfigSection(
                name=section_name,
                settings={}
            )
        
        config.sections[section_name].settings.update(settings)
        config.sections[section_name].last_modified = datetime.now()
        config.last_modified = datetime.now()
        
        # Save updated configuration
        await self.save_configuration(config)
        
        logger.info(f"Updated configuration section '{section_name}' for workspace: {workspace_id}")
        return True
    
    async def get_configuration_value(self, workspace_id: str, section_name: str,
                                    setting_name: str, default: Any = None) -> Any:
        """Get specific configuration value."""
        config = await self.load_configuration(workspace_id)
        if not config:
            return default
        
        return config.get_setting(section_name, setting_name, default)
    
    async def validate_configuration(self, config: WorkspaceConfiguration) -> List[str]:
        """Validate workspace configuration."""
        errors = []
        
        # Validate required sections
        required_sections = ["general", "security", "session"]
        for section_name in required_sections:
            if section_name not in config.sections:
                errors.append(f"Missing required section: {section_name}")
                continue
            
            section = config.sections[section_name]
            
            # Validate section-specific requirements
            if section_name == "general":
                if "auto_save" not in section.settings:
                    errors.append("Missing required setting: general.auto_save")
                if "backup_interval_minutes" not in section.settings:
                    errors.append("Missing required setting: general.backup_interval_minutes")
            
            elif section_name == "security":
                if "enable_security_checks" not in section.settings:
                    errors.append("Missing required setting: security.enable_security_checks")
                if "max_file_size_mb" not in section.settings:
                    errors.append("Missing required setting: security.max_file_size_mb")
            
            elif section_name == "session":
                if "session_timeout_minutes" not in section.settings:
                    errors.append("Missing required setting: session.session_timeout_minutes")
                if "max_concurrent_sessions" not in section.settings:
                    errors.append("Missing required setting: session.max_concurrent_sessions")
        
        # Validate data types
        for section_name, section in config.sections.items():
            for setting_name, value in section.settings.items():
                # Add specific validation rules here
                if setting_name.endswith("_minutes") or setting_name.endswith("_seconds"):
                    if not isinstance(value, (int, float)) or value < 0:
                        errors.append(f"Invalid value for {section_name}.{setting_name}: must be non-negative number")
                
                elif setting_name.endswith("_mb") or setting_name.endswith("_kb"):
                    if not isinstance(value, (int, float)) or value <= 0:
                        errors.append(f"Invalid value for {section_name}.{setting_name}: must be positive number")
                
                elif setting_name.startswith("enable_"):
                    if not isinstance(value, bool):
                        errors.append(f"Invalid value for {section_name}.{setting_name}: must be boolean")
                
                elif setting_name.endswith("_count") or setting_name.endswith("_size"):
                    if not isinstance(value, int) or value < 0:
                        errors.append(f"Invalid value for {section_name}.{setting_name}: must be non-negative integer")
        
        if not errors:
            logger.info(f"Configuration validation passed for workspace: {config.workspace_id}")
        else:
            logger.warning(f"Configuration validation failed for workspace {config.workspace_id}: {errors}")
        
        return errors
    
    async def export_configuration(self, workspace_id: str, export_path: Path) -> bool:
        """Export workspace configuration to a file."""
        config = await self.load_configuration(workspace_id)
        if not config:
            return False
        
        try:
            async with aiofiles.open(export_path, 'w') as f:
                await f.write(json.dumps(config.to_dict(), indent=2))
            
            logger.info(f"Exported configuration for workspace {workspace_id} to {export_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to export configuration for workspace {workspace_id}: {e}")
            return False
    
    async def import_configuration(self, import_path: Path, workspace_id: str) -> Optional[WorkspaceConfiguration]:
        """Import workspace configuration from a file."""
        try:
            async with aiofiles.open(import_path, 'r') as f:
                data = json.loads(await f.read())
            
            config = WorkspaceConfiguration.from_dict(data)
            config.workspace_id = workspace_id  # Update workspace ID
            config.created_at = datetime.now()  # Update creation time
            config.last_modified = datetime.now()
            
            # Save imported configuration
            await self.save_configuration(config)
            
            logger.info(f"Imported configuration for workspace: {workspace_id} from {import_path}")
            return config
        except Exception as e:
            logger.error(f"Failed to import configuration from {import_path}: {e}")
            return None