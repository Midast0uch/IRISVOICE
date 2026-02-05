"""
Power Manager - System power control and battery status
Handles shutdown, restart, sleep, lock screen, power profiles
"""
import os
import platform
import subprocess
from typing import Dict, Any, Optional
from enum import Enum


class PowerProfile(str, Enum):
    """Power profile options"""
    BALANCED = "Balanced"
    PERFORMANCE = "Performance"
    BATTERY = "Battery"


class PowerManager:
    """
    Manages system power functions:
    - Shutdown, restart, sleep, lock screen
    - Power profile switching
    - Battery status monitoring
    """
    
    _instance: Optional['PowerManager'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if PowerManager._initialized:
            return
        
        self._current_profile = PowerProfile.BALANCED
        self._system = platform.system()
        
        PowerManager._initialized = True
    
    def get_platform(self) -> str:
        """Get current platform"""
        return self._system
    
    async def shutdown(self, delay: int = 0) -> Dict[str, Any]:
        """Shutdown the system"""
        try:
            if self._system == "Windows":
                cmd = ["shutdown", "/s", "/t", str(delay)]
                if delay == 0:
                    cmd.append("/f")  # Force close applications
            elif self._system == "Darwin":  # macOS
                cmd = ["shutdown", "-h", "+" + str(delay)] if delay > 0 else ["shutdown", "-h", "now"]
            else:  # Linux
                cmd = ["shutdown", "-h", "+" + str(delay)] if delay > 0 else ["shutdown", "-h", "now"]
            
            subprocess.Popen(cmd, shell=(self._system == "Windows"))
            return {"success": True, "message": f"Shutdown initiated (delay: {delay}s)"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def restart(self, delay: int = 0) -> Dict[str, Any]:
        """Restart the system"""
        try:
            if self._system == "Windows":
                cmd = ["shutdown", "/r", "/t", str(delay)]
            elif self._system == "Darwin":
                cmd = ["shutdown", "-r", "+" + str(delay)] if delay > 0 else ["shutdown", "-r", "now"]
            else:  # Linux
                cmd = ["shutdown", "-r", "+" + str(delay)] if delay > 0 else ["shutdown", "-r", "now"]
            
            subprocess.Popen(cmd, shell=(self._system == "Windows"))
            return {"success": True, "message": f"Restart initiated (delay: {delay}s)"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def sleep(self) -> Dict[str, Any]:
        """Put system to sleep"""
        try:
            if self._system == "Windows":
                # Windows sleep command
                subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
            elif self._system == "Darwin":
                subprocess.Popen(["pmset", "sleepnow"])
            else:  # Linux
                subprocess.Popen(["systemctl", "suspend"])
            
            return {"success": True, "message": "Sleep initiated"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def lock_screen(self) -> Dict[str, Any]:
        """Lock the screen"""
        try:
            if self._system == "Windows":
                subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
            elif self._system == "Darwin":
                subprocess.Popen(["/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession", "-suspend"])
            else:  # Linux - try common lock commands
                for cmd in ["gnome-screensaver-command -l", "xscreensaver-command -lock", "i3lock", "slock"]:
                    try:
                        subprocess.Popen(cmd.split(), shell=False)
                        break
                    except:
                        continue
            
            return {"success": True, "message": "Screen locked"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def set_power_profile(self, profile: PowerProfile) -> Dict[str, Any]:
        """Set power profile (platform-specific implementation)"""
        try:
            self._current_profile = profile
            
            if self._system == "Windows":
                # Windows powercfg command
                guid_map = {
                    PowerProfile.BALANCED: "381b4222-f694-41f0-9685-ff5bb260df2e",
                    PowerProfile.PERFORMANCE: "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
                    PowerProfile.BATTERY: "a1841308-3541-4fab-bc81-f71556f20b4a"
                }
                guid = guid_map.get(profile, guid_map[PowerProfile.BALANCED])
                subprocess.Popen(["powercfg", "/setactive", guid])
                
            elif self._system == "Darwin":
                # macOS pmset for power profiles
                if profile == PowerProfile.PERFORMANCE:
                    subprocess.Popen(["pmset", "-a", "gpuswitch", "2"])  # Discrete GPU
                else:
                    subprocess.Popen(["pmset", "-a", "gpuswitch", "0"])  # Integrated
                    
            else:  # Linux
                # Try powerprofilesctl (GNOME) or tlp
                if profile == PowerProfile.PERFORMANCE:
                    subprocess.Popen(["powerprofilesctl", "set", "performance"], stderr=subprocess.DEVNULL)
                elif profile == PowerProfile.BATTERY:
                    subprocess.Popen(["powerprofilesctl", "set", "power-saver"], stderr=subprocess.DEVNULL)
                else:
                    subprocess.Popen(["powerprofilesctl", "set", "balanced"], stderr=subprocess.DEVNULL)
            
            return {"success": True, "profile": profile.value}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_battery_status(self) -> Dict[str, Any]:
        """Get battery status"""
        try:
            import psutil
            
            battery = psutil.sensors_battery()
            if battery is None:
                return {"success": True, "has_battery": False, "message": "No battery detected"}
            
            return {
                "success": True,
                "has_battery": True,
                "percent": battery.percent,
                "power_plugged": battery.power_plugged,
                "secs_left": battery.secs_left if battery.secs_left != -2 else None,
                "time_remaining": self._format_time(battery.secs_left) if battery.secs_left > 0 else "Unknown"
            }
            
        except ImportError:
            return {"success": False, "error": "psutil not installed"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _format_time(self, seconds: int) -> str:
        """Format seconds to human readable time"""
        if seconds < 0:
            return "Unknown"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"
    
    def get_status(self) -> Dict[str, Any]:
        """Get power manager status"""
        battery = self.get_battery_status()
        return {
            "platform": self._system,
            "power_profile": self._current_profile.value,
            "battery": battery if battery.get("success") else None
        }


def get_power_manager() -> PowerManager:
    """Get the singleton PowerManager instance"""
    return PowerManager()
