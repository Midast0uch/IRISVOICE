"""
IRIS Developer Mode — CLI Toolkit
Provides CLI tool registration, subprocess management, and file watching
for IRIS developer mode. Activated when useLauncherMode returns 'developer'.
"""
from .cli_registry import CLIRegistry, CLITool, get_cli_registry
from .subprocess_manager import SubprocessManager, get_subprocess_manager
from .file_watcher import FileWatcher, get_file_watcher
from .orchestrator import DevOrchestrator, get_dev_orchestrator

__all__ = [
    "CLIRegistry", "CLITool", "get_cli_registry",
    "SubprocessManager", "get_subprocess_manager",
    "FileWatcher", "get_file_watcher",
    "DevOrchestrator", "get_dev_orchestrator",
]
