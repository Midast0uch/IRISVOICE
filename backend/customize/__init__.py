"""
IRIS Customize Module
Personalization settings: startup, behavior, notifications
"""

from .startup import StartupManager, get_startup_manager
from .behavior import BehaviorManager, get_behavior_manager
from .notifications import NotificationManager, get_notification_manager

__all__ = [
    "StartupManager",
    "get_startup_manager",
    "BehaviorManager",
    "get_behavior_manager",
    "NotificationManager",
    "get_notification_manager",
]
