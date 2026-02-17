"""
Storage Manager - Disk usage, quick folders, cleanup, external drives
"""
import os
import shutil
import platform
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class DriveInfo:
    """Storage drive information"""
    path: str
    total: int
    used: int
    free: int
    percent_used: float
    filesystem: str
    is_removable: bool = False


class StorageManager:
    """
    Manages storage:
    - Disk usage monitoring
    - Quick folders (Desktop/Downloads/Documents)
    - Cleanup operations
    - External drive detection
    """
    
    _instance: Optional['StorageManager'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if StorageManager._initialized:
            return
        
        self._system = platform.system()
        self._quick_folders = {
            "Desktop": self._get_desktop_path(),
            "Downloads": self._get_downloads_path(),
            "Documents": self._get_documents_path(),
        }
        
        StorageManager._initialized = True
    
    def _get_desktop_path(self) -> Path:
        """Get Desktop folder path"""
        home = Path.home()
        if self._system == "Windows":
            return home / "Desktop"
        return home / "Desktop"
    
    def _get_downloads_path(self) -> Path:
        """Get Downloads folder path"""
        return Path.home() / "Downloads"
    
    def _get_documents_path(self) -> Path:
        """Get Documents folder path"""
        home = Path.home()
        if self._system == "Windows":
            return home / "Documents"
        return home / "Documents"
    
    def get_disk_usage(self, path: str = "/") -> Dict[str, Any]:
        """Get disk usage for a path"""
        try:
            total, used, free = shutil.disk_usage(path)
            
            return {
                "success": True,
                "path": path,
                "total_gb": round(total / (1024**3), 2),
                "used_gb": round(used / (1024**3), 2),
                "free_gb": round(free / (1024**3), 2),
                "percent_used": round((used / total) * 100, 1)
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_all_drives(self) -> List[Dict[str, Any]]:
        """Get all storage drives"""
        drives = []
        
        try:
            if self._system == "Windows":
                # Windows drives
                import string
                from ctypes import windll
                
                bitmask = windll.kernel32.GetLogicalDrives()
                for letter in string.ascii_uppercase:
                    if bitmask & 1:
                        drive = f"{letter}:\\"
                        try:
                            usage = self.get_disk_usage(drive)
                            if usage["success"]:
                                drives.append({
                                    "path": drive,
                                    **usage
                                })
                        except:
                            pass
                    bitmask >>= 1
                    
            elif self._system == "Darwin":
                # macOS - get mounted volumes
                volumes = Path("/Volumes")
                if volumes.exists():
                    for vol in volumes.iterdir():
                        try:
                            usage = self.get_disk_usage(str(vol))
                            if usage["success"]:
                                drives.append({
                                    "path": str(vol),
                                    "name": vol.name,
                                    **usage
                                })
                        except:
                            pass
                
                # Also get root
                root_usage = self.get_disk_usage("/")
                if root_usage["success"]:
                    drives.insert(0, {"path": "/", "name": "Macintosh HD", **root_usage})
                    
            else:  # Linux
                # Get from /proc/mounts or df
                result = subprocess.run(
                    ["df", "-h", "--output=source,size,used,avail,target"],
                    capture_output=True, text=True
                )
                for line in result.stdout.split("\n")[1:]:
                    parts = line.split()
                    if len(parts) >= 5 and parts[0].startswith("/"):
                        drives.append({
                            "path": parts[-1],
                            "device": parts[0],
                            "size": parts[1],
                            "used": parts[2],
                            "available": parts[3]
                        })
        
        except Exception as e:
            return [{"error": str(e)}]
        
        return drives
    
    def get_quick_folders(self) -> Dict[str, Any]:
        """Get quick folders info"""
        result = {}
        
        for name, path in self._quick_folders.items():
            try:
                if path.exists():
                    # Count files and get size
                    size = 0
                    file_count = 0
                    
                    for item in path.iterdir():
                        if item.is_file():
                            size += item.stat().st_size
                            file_count += 1
                        elif item.is_dir():
                            file_count += 1
                    
                    result[name] = {
                        "path": str(path),
                        "exists": True,
                        "size_mb": round(size / (1024**2), 2),
                        "item_count": file_count
                    }
                else:
                    result[name] = {"path": str(path), "exists": False}
            except Exception as e:
                result[name] = {"path": str(path), "error": str(e)}
        
        return result
    
    def cleanup_temp_files(self) -> Dict[str, Any]:
        """Clean up temporary files"""
        try:
            temp_dirs = []
            freed_space = 0
            
            if self._system == "Windows":
                temp_dirs.append(Path(os.environ.get("TEMP", "C:\\Windows\\Temp")))
                temp_dirs.append(Path(os.environ.get("TMP", "C:\\Windows\\Temp")))
            else:
                temp_dirs.append(Path("/tmp"))
                temp_dirs.append(Path.home() / ".cache")
            
            cleaned_files = 0
            for temp_dir in temp_dirs:
                if temp_dir.exists():
                    for item in temp_dir.iterdir():
                        try:
                            if item.is_file():
                                freed_space += item.stat().st_size
                                item.unlink()
                                cleaned_files += 1
                            elif item.is_dir():
                                shutil.rmtree(item)
                                cleaned_files += 1
                        except:
                            pass
            
            return {
                "success": True,
                "cleaned_files": cleaned_files,
                "freed_mb": round(freed_space / (1024**2), 2)
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_external_drives(self) -> List[Dict[str, Any]]:
        """Get external/removable drives"""
        drives = self.get_all_drives()
        # Filter for external drives (this is platform-specific)
        # For now, return all non-root drives
        external = []
        
        for drive in drives:
            path = drive.get("path", "")
            if self._system == "Windows":
                if path != "C:\\":
                    external.append(drive)
            elif self._system == "Darwin":
                if "/Volumes" in path:
                    external.append(drive)
            else:
                if path not in ["/", "/boot", "/home"]:
                    external.append(drive)
        
        return external
    
    def open_folder(self, path: str) -> Dict[str, Any]:
        """Open a folder in file manager"""
        try:
            folder_path = Path(path)
            if not folder_path.exists():
                return {"success": False, "error": "Folder does not exist"}
            
            if self._system == "Windows":
                os.startfile(str(folder_path))
            elif self._system == "Darwin":
                subprocess.Popen(["open", str(folder_path)])
            else:
                subprocess.Popen(["xdg-open", str(folder_path)])
            
            return {"success": True, "path": str(folder_path)}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_status(self) -> Dict[str, Any]:
        """Get storage manager status"""
        return {
            "drives": self.get_all_drives(),
            "quick_folders": self.get_quick_folders(),
            "external_drives": self.get_external_drives()
        }


def get_storage_manager() -> StorageManager:
    """Get the singleton StorageManager instance"""
    return StorageManager()
