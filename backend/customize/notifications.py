"""
Notification Manager - Handles DND mode, notification sounds, and banner style
"""
import platform
from typing import Dict, Any, Optional
from datetime import datetime, time


class NotificationManager:
    """
    Manages notification settings:
    - Do Not Disturb mode
    - DND schedule
    - Notification sounds
    - Banner style
    - App notification toggle
    """
    
    _instance: Optional['NotificationManager'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if NotificationManager._initialized:
            return
        
        self._system = platform.system()
        
        self.config = {
            "dnd_enabled": False,
            "dnd_schedule": "",  # Format: "22:00-07:00" or empty for manual
            "notification_sound": "Default",  # Default / Chime / Pulse / Silent
            "banner_style": "Native",  # Native / Custom / Minimal
            "app_notifications": True,
        }
        
        NotificationManager._initialized = True
    
    def update_config(self, **kwargs) -> None:
        """Update notification configuration"""
        for key, value in kwargs.items():
            if key in self.config:
                self.config[key] = value
    
    def get_config(self) -> Dict[str, Any]:
        """Get current notification configuration"""
        return self.config.copy()
    
    # ---------------------------------------------------------------------
    # DND (Do Not Disturb)
    # ---------------------------------------------------------------------
    
    def is_dnd_active(self) -> bool:
        """Check if DND is currently active"""
        if not self.config.get("dnd_enabled", False):
            return False
        
        schedule = self.config.get("dnd_schedule", "")
        if not schedule:
            return True  # Manual DND, always active when enabled
        
        # Check if current time is within schedule
        try:
            start_str, end_str = schedule.split("-")
            start_time = datetime.strptime(start_str.strip(), "%H:%M").time()
            end_time = datetime.strptime(end_str.strip(), "%H:%M").time()
            
            now = datetime.now().time()
            
            if start_time <= end_time:
                # Same day range (e.g., 09:00-17:00)
                return start_time <= now <= end_time
            else:
                # Overnight range (e.g., 22:00-07:00)
                return now >= start_time or now <= end_time
        except ValueError:
            return True  # Invalid schedule, treat as always on
    
    def enable_dnd(self, schedule: str = None) -> None:
        """Enable DND mode"""
        self.config["dnd_enabled"] = True
        if schedule is not None:
            self.config["dnd_schedule"] = schedule
    
    def disable_dnd(self) -> None:
        """Disable DND mode"""
        self.config["dnd_enabled"] = False
    
    # ---------------------------------------------------------------------
    # Notification Sounds
    # ---------------------------------------------------------------------
    
    def get_notification_sound(self) -> str:
        """Get configured notification sound"""
        return self.config.get("notification_sound", "Default")
    
    def play_notification_sound(self) -> bool:
        """Play the configured notification sound"""
        if self.is_dnd_active():
            return False
        
        sound = self.config.get("notification_sound", "Default")
        if sound == "Silent":
            return False
        
        # Platform-specific sound playing would go here
        # For now, just return True to indicate we would have played
        return True
    
    # ---------------------------------------------------------------------
    # Banner/Toast Notifications
    # ---------------------------------------------------------------------
    
    def get_banner_style(self) -> str:
        """Get configured banner style"""
        return self.config.get("banner_style", "Native")
    
    def should_show_notification(self) -> bool:
        """Check if notifications should be shown"""
        if not self.config.get("app_notifications", True):
            return False
        
        if self.is_dnd_active():
            return False
        
        return True
    
    def show_notification(self, title: str, message: str, icon: str = None) -> Dict[str, Any]:
        """
        Show a notification banner
        Returns success status
        """
        if not self.should_show_notification():
            return {"success": False, "reason": "notifications_disabled"}
        
        style = self.get_banner_style()
        
        try:
            if style == "Native":
                return self._show_native_notification(title, message, icon)
            elif style == "Custom":
                return self._show_custom_notification(title, message, icon)
            elif style == "Minimal":
                return self._show_minimal_notification(title, message)
            else:
                return {"success": False, "error": f"Unknown style: {style}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _show_native_notification(self, title: str, message: str, icon: str = None) -> Dict[str, Any]:
        """Show native OS notification"""
        if self._system == "Windows":
            try:
                from win10toast import ToastNotifier
                toast = ToastNotifier()
                toast.show_toast(title, message, icon_path=icon, duration=5)
                return {"success": True, "style": "native", "platform": "windows"}
            except ImportError:
                # Fallback to notification sound only
                self.play_notification_sound()
                return {"success": True, "style": "sound_only", "note": "win10toast not installed"}
        
        elif self._system == "Darwin":
            # macOS notification via osascript
            import subprocess
            script = f'display notification "{message}" with title "{title}"'
            subprocess.run(["osascript", "-e", script], check=False)
            return {"success": True, "style": "native", "platform": "macos"}
        
        else:  # Linux
            # Try notify2 or notify-send
            try:
                import subprocess
                subprocess.run([
                    "notify-send", 
                    "-a", "IRIS",
                    "-i", icon or "dialog-information",
                    title, 
                    message
                ], check=False)
                return {"success": True, "style": "native", "platform": "linux"}
            except Exception as e:
                return {"success": False, "error": str(e)}
    
    def _show_custom_notification(self, title: str, message: str, icon: str = None) -> Dict[str, Any]:
        """Show custom-styled notification (would integrate with frontend)"""
        # This would trigger a frontend notification component
        # For now, just record that we want to show one
        return {
            "success": True,
            "style": "custom",
            "title": title,
            "message": message,
            "icon": icon,
            "note": "Custom notifications require frontend integration"
        }
    
    def _show_minimal_notification(self, title: str, message: str) -> Dict[str, Any]:
        """Show minimal notification (sound only or subtle indicator)"""
        self.play_notification_sound()
        return {
            "success": True,
            "style": "minimal",
            "note": "Sound only notification"
        }


def get_notification_manager() -> NotificationManager:
    """Get the singleton NotificationManager instance"""
    return NotificationManager()
