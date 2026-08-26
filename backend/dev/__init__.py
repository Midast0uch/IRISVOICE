"""
IRIS Developer Mode — dev toolkit
Provides subprocess management and file watching for IRIS developer mode.
Activated when useLauncherMode returns 'developer'.

REQ-0 (D7): the external CLI registry (cli_tools.yaml / cli_registry.py) was
removed — dev_cli routes to IRIS's own AgentKernel via orchestrator.py.
"""
from .subprocess_manager import SubprocessManager, get_subprocess_manager
from .file_watcher import FileWatcher, get_file_watcher
from .orchestrator import DevOrchestrator, get_dev_orchestrator

__all__ = [
    "SubprocessManager", "get_subprocess_manager",
    "FileWatcher", "get_file_watcher",
    "DevOrchestrator", "get_dev_orchestrator",
]
