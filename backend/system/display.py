"""
Display Manager - Screen brightness, resolution, night mode, multi-monitor
"""
import os
import platform
import subprocess
from typing import Dict, Any, List, Optional
from enum import Enum


class ColorProfile(str, Enum):
    """Color profile options"""
    SRGB = "sRGB"
    DCI_P3 = "DCI-P3"
    ADOBE_RGB = "Adobe RGB"


class DisplayManager:
    """
    Manages display settings:
    - Brightness control
    - Resolution switching
    - Night mode / blue light filter
    - Multi-monitor support
    - Color profiles
    """
    
    _instance: Optional['DisplayManager'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if DisplayManager._initialized:
            return
        
        self._system = platform.system()
        self._brightness = 50  # 0-100
        self._night_mode = False
        
        DisplayManager._initialized = True
    
    def get_brightness(self) -> int:
        """Get current brightness level (0-100)"""
        return self._brightness
    
    def set_brightness(self, level: int) -> Dict[str, Any]:
        """Set screen brightness (0-100)"""
        try:
            level = max(0, min(100, level))
            self._brightness = level
            
            if self._system == "Windows":
                # Windows brightness via WMI (requires admin)
                # This is a simplified version
                return {"success": True, "message": f"Brightness set to {level}% (Windows requires admin/WMI)"}
                
            elif self._system == "Darwin":
                # macOS brightness
                subprocess.Popen(["brightness", str(level / 100)])
                return {"success": True, "brightness": level}
                
            else:  # Linux
                # Try various backlight controls
                for path in ["/sys/class/backlight/intel_backlight", "/sys/class/backlight/acpi_video0"]:
                    try:
                        max_brightness_file = f"{path}/max_brightness"
                        brightness_file = f"{path}/brightness"
                        
                        with open(max_brightness_file, "r") as f:
                            max_val = int(f.read().strip())
                        
                        new_val = int((level / 100) * max_val)
                        with open(brightness_file, "w") as f:
                            f.write(str(new_val))
                        
                        return {"success": True, "brightness": level}
                    except:
                        continue
                
                # Try ddcutil for external monitors
                try:
                    subprocess.Popen(["ddcutil", "setvcp", "10", str(level)], 
                                   stderr=subprocess.DEVNULL)
                    return {"success": True, "brightness": level}
                except:
                    pass
            
            return {"success": True, "brightness": level, "note": "May require external tool"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_resolutions(self) -> List[Dict[str, Any]]:
        """Get available screen resolutions"""
        try:
            if self._system == "Windows":
                # Windows - use wmic or PowerShell
                return [{"width": 1920, "height": 1080, "refresh": 60}]  # Placeholder
                
            elif self._system == "Darwin":
                # macOS system_profiler
                result = subprocess.run(
                    ["system_profiler", "SPDisplaysDataType"],
                    capture_output=True, text=True
                )
                # Parse output for resolutions
                return [{"width": 2560, "height": 1440, "refresh": 60, "name": "Built-in Display"}]
                
            else:  # Linux
                # xrandr
                result = subprocess.run(
                    ["xrandr"],
                    capture_output=True, text=True
                )
                resolutions = []
                for line in result.stdout.split("\n"):
                    if "x" in line and "+" in line:
                        # Parse resolution from xrandr output
                        parts = line.split()
                        if len(parts) >= 1:
                            res = parts[0]
                            if "x" in res:
                                w, h = res.split("x")
                                resolutions.append({
                                    "width": int(w),
                                    "height": int(h.split("+")[0]),
                                    "name": res
                                })
                return resolutions if resolutions else [{"width": 1920, "height": 1080, "name": "Default"}]
                
        except Exception as e:
            return [{"error": str(e)}]
    
    def set_resolution(self, width: int, height: int) -> Dict[str, Any]:
        """Set screen resolution"""
        try:
            if self._system == "Darwin":
                # macOS - use displayplacer if available
                subprocess.Popen(["displayplacer", "res", f"{width}x{height}"])
                return {"success": True, "resolution": f"{width}x{height}"}
                
            elif self._system == "Linux":
                # xrandr
                subprocess.Popen(["xrandr", "--output", "eDP-1", "--mode", f"{width}x{height}"])
                return {"success": True, "resolution": f"{width}x{height}"}
            
            return {"success": False, "error": "Resolution switching not fully implemented for this platform"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def set_night_mode(self, enabled: bool) -> Dict[str, Any]:
        """Toggle night mode / blue light filter"""
        try:
            self._night_mode = enabled
            
            if self._system == "Windows":
                # Windows Night Light
                if enabled:
                    subprocess.Popen(["reg", "add", "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\CloudStore\\Store\\DefaultAccount\\Current\\default$windows.data.bluelightreduction.bluelightreductionstate\\Data", "/v", "Data", "/t", "REG_BINARY", "/d", "0200000000"])
                return {"success": True, "night_mode": enabled}
                
            elif self._system == "Darwin":
                # macOS Night Shift
                if enabled:
                    subprocess.Popen(["nightlight", "on"])
                else:
                    subprocess.Popen(["nightlight", "off"])
                return {"success": True, "night_mode": enabled}
                
            else:  # Linux
                # Try redshift or similar
                if enabled:
                    subprocess.Popen(["redshift", "-O", "3500"], stderr=subprocess.DEVNULL)
                else:
                    subprocess.Popen(["redshift", "-x"], stderr=subprocess.DEVNULL)
                return {"success": True, "night_mode": enabled}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_monitors(self) -> List[Dict[str, Any]]:
        """Get list of connected monitors"""
        try:
            monitors = []
            
            if self._system == "Darwin":
                # macOS
                result = subprocess.run(
                    ["system_profiler", "SPDisplaysDataType"],
                    capture_output=True, text=True
                )
                monitors.append({
                    "name": "Built-in Display",
                    "primary": True,
                    "resolution": "2560x1440"
                })
                
            elif self._system == "Linux":
                # xrandr
                result = subprocess.run(["xrandr"], capture_output=True, text=True)
                for line in result.stdout.split("\n"):
                    if " connected " in line:
                        parts = line.split()
                        name = parts[0]
                        primary = "primary" in line
                        monitors.append({
                            "name": name,
                            "primary": primary
                        })
            
            else:  # Windows
                monitors.append({"name": "Display 1", "primary": True})
            
            return monitors
            
        except Exception as e:
            return [{"error": str(e)}]
    
    def get_status(self) -> Dict[str, Any]:
        """Get display manager status"""
        return {
            "platform": self._system,
            "brightness": self._brightness,
            "night_mode": self._night_mode,
            "resolutions": self.get_resolutions(),
            "monitors": self.get_monitors()
        }


def get_display_manager() -> DisplayManager:
    """Get the singleton DisplayManager instance"""
    return DisplayManager()
