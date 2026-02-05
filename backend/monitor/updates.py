"""
Update Manager - Version checking and update channel management
"""
import json
from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime, timedelta
import httpx


class UpdateManager:
    """
    Manages application updates:
    - Update channel management (Stable/Beta/Nightly)
    - Version checking
    - Changelog retrieval
    """
    
    _instance: Optional['UpdateManager'] = None
    _initialized: bool = False
    
    # Current version
    CURRENT_VERSION = "0.1.0"
    
    # Update URLs by channel
    UPDATE_URLS = {
        "Stable": "https://api.github.com/repos/iris/iris/releases/latest",
        "Beta": "https://api.github.com/repos/iris/iris/releases",
        "Nightly": "https://nightly.iris.dev/version"
    }
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if UpdateManager._initialized:
            return
        
        self.config = {
            "update_channel": "Stable",
            "auto_update": True,
            "last_check": None
        }
        
        self._last_check_result: Optional[Dict[str, Any]] = None
        
        UpdateManager._initialized = True
    
    def update_config(self, **kwargs) -> None:
        """Update configuration"""
        for key, value in kwargs.items():
            if key in self.config:
                self.config[key] = value
    
    def get_config(self) -> Dict[str, Any]:
        """Get current configuration"""
        return self.config.copy()
    
    def get_current_version(self) -> str:
        """Get current application version"""
        return self.CURRENT_VERSION
    
    async def check_for_updates(self) -> Dict[str, Any]:
        """Check for available updates"""
        channel = self.config.get("update_channel", "Stable")
        
        try:
            # In a real implementation, this would fetch from the update URL
            # For now, return mock data
            
            # Simulate API call
            await self._simulate_network_delay()
            
            # Mock response
            if channel == "Stable":
                latest_version = "0.1.1"
                update_available = latest_version != self.CURRENT_VERSION
            elif channel == "Beta":
                latest_version = "0.2.0-beta.1"
                update_available = True
            else:  # Nightly
                latest_version = "0.2.0-dev.20240201"
                update_available = True
            
            result = {
                "success": True,
                "current_version": self.CURRENT_VERSION,
                "latest_version": latest_version,
                "update_available": update_available,
                "channel": channel,
                "download_url": f"https://github.com/iris/iris/releases/tag/v{latest_version}" if update_available else None
            }
            
            self._last_check_result = result
            self.config["last_check"] = datetime.now().isoformat()
            
            return result
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "current_version": self.CURRENT_VERSION
            }
    
    async def _simulate_network_delay(self):
        """Simulate network delay for demo"""
        import asyncio
        await asyncio.sleep(0.5)
    
    def get_changelog(self, version: str = None) -> Dict[str, Any]:
        """Get changelog for a version"""
        # Mock changelog
        changelogs = {
            "0.1.1": [
                "Fixed audio pipeline stability issues",
                "Improved wake word detection accuracy",
                "Added support for custom themes"
            ],
            "0.2.0-beta.1": [
                "New MCP workflow engine",
                "Enhanced voice cloning capabilities",
                "Performance improvements"
            ],
            "0.2.0-dev.20240201": [
                "Experimental multi-agent support",
                "New neural voice synthesis",
                "Breaking API changes"
            ]
        }
        
        if version:
            return {
                "version": version,
                "changes": changelogs.get(version, ["No changelog available"])
            }
        else:
            return {
                "current": self.CURRENT_VERSION,
                "changelogs": changelogs
            }
    
    def get_update_channels(self) -> Dict[str, Any]:
        """Get available update channels"""
        return {
            "channels": [
                {
                    "name": "Stable",
                    "description": "Tested and reliable releases",
                    "recommended": True
                },
                {
                    "name": "Beta",
                    "description": "Early access to new features",
                    "recommended": False
                },
                {
                    "name": "Nightly",
                    "description": "Latest development builds",
                    "recommended": False,
                    "warning": "May be unstable"
                }
            ],
            "current": self.config.get("update_channel", "Stable")
        }


def get_update_manager() -> UpdateManager:
    """Get the singleton UpdateManager instance"""
    return UpdateManager()
