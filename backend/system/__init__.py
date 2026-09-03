"""
IRIS System Module
OS integration for SYSTEM node - power, display, storage, network
"""

from .power import PowerManager, get_power_manager
from .display import DisplayManager, get_display_manager
from .storage import StorageManager, get_storage_manager
from .network import NetworkManager, get_network_manager

__all__ = [
    "PowerManager",
    "get_power_manager",
    "DisplayManager",
    "get_display_manager",
    "StorageManager",
    "get_storage_manager",
    "NetworkManager",
    "get_network_manager",
]
