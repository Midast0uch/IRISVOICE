"""
Startup Manager - Handles auto-launch and startup behavior
"""
import os
import platform
import sys
from pathlib import Path
from typing import Dict, Any, Optional


class StartupManager:
    """
    Manages application startup behavior:
    - Auto-launch at system startup
    - Startup behavior (show/minimized/hidden)
    - Welcome message
    - Default state
    """
    
    _instance: Optional['StartupManager'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if StartupManager._initialized:
            return
        
        self._system = platform.system()
        self.config = {
            "launch_at_startup": False,
            "startup_behavior": "Show Widget",  # Show Widget / Start Minimized / Start Hidden
            "welcome_message": True,
            "default_state": "Collapsed",  # Collapsed / Expanded
        }
        
        StartupManager._initialized = True
    
    def update_config(self, **kwargs) -> None:
        """Update startup configuration"""
        for key, value in kwargs.items():
            if key in self.config:
                self.config[key] = value
        
        # Apply auto-launch setting immediately
        if "launch_at_startup" in kwargs:
            if kwargs["launch_at_startup"]:
                self.enable_auto_launch()
            else:
                self.disable_auto_launch()
    
    def get_config(self) -> Dict[str, Any]:
        """Get current startup configuration"""
        return self.config.copy()
    
    def enable_auto_launch(self) -> Dict[str, Any]:
        """Enable auto-launch at system startup"""
        try:
            if self._system == "Windows":
                return self._enable_windows_auto_launch()
            elif self._system == "Darwin":
                return self._enable_macos_auto_launch()
            else:  # Linux
                return self._enable_linux_auto_launch()
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def disable_auto_launch(self) -> Dict[str, Any]:
        """Disable auto-launch at system startup"""
        try:
            if self._system == "Windows":
                return self._disable_windows_auto_launch()
            elif self._system == "Darwin":
                return self._disable_macos_auto_launch()
            else:  # Linux
                return self._disable_linux_auto_launch()
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _enable_windows_auto_launch(self) -> Dict[str, Any]:
        """Enable auto-launch on Windows (Registry)"""
        try:
            import winreg
            
            # Get executable path
            exe_path = sys.executable
            if not exe_path.endswith(".exe"):
                # Development mode - use pythonw
                exe_path = f'"{exe_path}" -m iris'
            
            # Add to Run registry key
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, "IRIS", 0, winreg.REG_SZ, exe_path)
            
            return {"success": True, "message": "Auto-launch enabled for Windows"}
        except ImportError:
            return {"success": False, "error": "winreg not available"}
    
    def _disable_windows_auto_launch(self) -> Dict[str, Any]:
        """Disable auto-launch on Windows"""
        try:
            import winreg
            
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE) as key:
                try:
                    winreg.DeleteValue(key, "IRIS")
                except FileNotFoundError:
                    pass  # Already doesn't exist
            
            return {"success": True, "message": "Auto-launch disabled for Windows"}
        except ImportError:
            return {"success": False, "error": "winreg not available"}
    
    def _enable_macos_auto_launch(self) -> Dict[str, Any]:
        """Enable auto-launch on macOS (LaunchAgent)"""
        try:
            plist_path = Path.home() / "Library/LaunchAgents/com.iris.app.plist"
            
            plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.iris.app</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>-m</string>
        <string>iris</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>"""
            
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_text(plist_content)
            
            # Load the launch agent
            import subprocess
            subprocess.run(["launchctl", "load", str(plist_path)], check=False)
            
            return {"success": True, "message": "Auto-launch enabled for macOS"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _disable_macos_auto_launch(self) -> Dict[str, Any]:
        """Disable auto-launch on macOS"""
        try:
            plist_path = Path.home() / "Library/LaunchAgents/com.iris.app.plist"
            
            if plist_path.exists():
                import subprocess
                subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
                plist_path.unlink()
            
            return {"success": True, "message": "Auto-launch disabled for macOS"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _enable_linux_auto_launch(self) -> Dict[str, Any]:
        """Enable auto-launch on Linux (desktop entry)"""
        try:
            autostart_dir = Path.home() / ".config/autostart"
            autostart_dir.mkdir(parents=True, exist_ok=True)
            
            desktop_path = autostart_dir / "iris.desktop"
            
            desktop_content = f"""[Desktop Entry]
Type=Application
Name=IRIS
Exec={sys.executable} -m iris
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
"""
            
            desktop_path.write_text(desktop_content)
            desktop_path.chmod(0o755)
            
            return {"success": True, "message": "Auto-launch enabled for Linux"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _disable_linux_auto_launch(self) -> Dict[str, Any]:
        """Disable auto-launch on Linux"""
        try:
            desktop_path = Path.home() / ".config/autostart/iris.desktop"
            if desktop_path.exists():
                desktop_path.unlink()
            
            return {"success": True, "message": "Auto-launch disabled for Linux"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def is_auto_launch_enabled(self) -> bool:
        """Check if auto-launch is currently enabled"""
        try:
            if self._system == "Windows":
                import winreg
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                    try:
                        winreg.QueryValueEx(key, "IRIS")
                        return True
                    except FileNotFoundError:
                        return False
            elif self._system == "Darwin":
                plist_path = Path.home() / "Library/LaunchAgents/com.iris.app.plist"
                return plist_path.exists()
            else:  # Linux
                desktop_path = Path.home() / ".config/autostart/iris.desktop"
                return desktop_path.exists()
        except Exception:
            return False


def get_startup_manager() -> StartupManager:
    """Get the singleton StartupManager instance"""
    return StartupManager()
