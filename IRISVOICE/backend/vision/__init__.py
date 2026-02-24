"""
IRIS Vision Module — MiniCPM-o Integration
Provides visual understanding, screen-aware conversation, and proactive monitoring.
"""
from .minicpm_client import MiniCPMClient, get_minicpm_client
from .screen_capture import ScreenCapture, get_screen_capture
from .screen_monitor import ScreenMonitor, get_screen_monitor

__all__ = [
    "MiniCPMClient",
    "get_minicpm_client",
    "ScreenCapture",
    "get_screen_capture",
    "ScreenMonitor",
    "get_screen_monitor",
]
