"""
IRISVOICE Configuration Module

Provides workspace management and configuration loading functionality
for the IRISVOICE application.
"""

from .workspace_manager import WorkspaceManager, WorkspaceConfig, DirectoryStructure
from .config_loader import ConfigurationLoader, WorkspaceConfiguration, ConfigSection
from .hot_reload import HotReloadManager, ConfigChangeHandler
from .session_config import SessionConfigurationManager
from .version_control import ConfigurationVersionControl, ConfigVersion, ConfigChange

__all__ = [
    "WorkspaceManager",
    "WorkspaceConfig", 
    "DirectoryStructure",
    "ConfigurationLoader",
    "WorkspaceConfiguration",
    "ConfigSection",
    "HotReloadManager",
    "ConfigChangeHandler",
    "SessionConfigurationManager",
    "ConfigurationVersionControl",
    "ConfigVersion",
    "ConfigChange"
]