"""
Network Manager - WiFi, Ethernet, VPN, bandwidth monitoring
"""
import platform
import subprocess
import socket
from typing import Dict, Any, List, Optional
from enum import Enum


class VPNType(str, Enum):
    """VPN connection types"""
    NONE = "None"
    WORK = "Work"
    PERSONAL = "Personal"


class NetworkManager:
    """
    Manages network settings:
    - WiFi toggle
    - Ethernet status
    - VPN connections
    - Bandwidth monitoring
    """
    
    _instance: Optional['NetworkManager'] = None
    _initialized: bool = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if NetworkManager._initialized:
            return
        
        self._system = platform.system()
        self._wifi_enabled = True
        self._current_vpn = VPNType.NONE
        self._bandwidth_stats = {"download": 0, "upload": 0}
        
        NetworkManager._initialized = True
    
    def get_platform(self) -> str:
        """Get current platform"""
        return self._system
    
    def get_wifi_status(self) -> Dict[str, Any]:
        """Get WiFi status"""
        try:
            if self._system == "Windows":
                # Use netsh to check WiFi status
                result = subprocess.run(
                    ["netsh", "wlan", "show", "interfaces"],
                    capture_output=True, text=True, shell=False
                )
                connected = "State" in result.stdout and "connected" in result.stdout.lower()
                
                # Extract SSID if connected
                ssid = None
                for line in result.stdout.split("\n"):
                    if "SSID" in line and "BSSID" not in line:
                        ssid = line.split(":", 1)[1].strip()
                        break
                
                return {
                    "success": True,
                    "enabled": self._wifi_enabled,
                    "connected": connected,
                    "ssid": ssid,
                    "interface": "WiFi"
                }
                
            elif self._system == "Darwin":
                # macOS - use airport or networksetup
                result = subprocess.run(
                    ["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"],
                    capture_output=True, text=True
                )
                connected = " SSID" in result.stdout
                
                ssid = None
                for line in result.stdout.split("\n"):
                    if " SSID" in line and "BSSID" not in line:
                        ssid = line.split(":", 1)[1].strip()
                        break
                
                return {
                    "success": True,
                    "enabled": self._wifi_enabled,
                    "connected": connected,
                    "ssid": ssid
                }
                
            else:  # Linux
                # Try nmcli
                result = subprocess.run(
                    ["nmcli", "connection", "show", "--active"],
                    capture_output=True, text=True
                )
                connected = "wifi" in result.stdout.lower()
                
                return {
                    "success": True,
                    "enabled": self._wifi_enabled,
                    "connected": connected
                }
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def set_wifi_enabled(self, enabled: bool) -> Dict[str, Any]:
        """Enable/disable WiFi"""
        try:
            self._wifi_enabled = enabled
            
            if self._system == "Windows":
                # Use netsh to enable/disable WiFi interface
                action = "enabled" if enabled else "disabled"
                # This requires admin privileges
                subprocess.Popen(
                    ["netsh", "interface", "set", "interface", "Wi-Fi", "admin=" + action],
                    shell=False
                )
                
            elif self._system == "Darwin":
                # macOS - use networksetup
                action = "on" if enabled else "off"
                subprocess.Popen(
                    ["networksetup", "-setairportpower", "en0", action],
                    shell=False
                )
                
            else:  # Linux
                # Use nmcli or rfkill
                if enabled:
                    subprocess.Popen(["nmcli", "radio", "wifi", "on"], shell=False)
                else:
                    subprocess.Popen(["nmcli", "radio", "wifi", "off"], shell=False)
            
            return {
                "success": True,
                "enabled": enabled,
                "message": f"WiFi {'enabled' if enabled else 'disabled'}"
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_ethernet_status(self) -> Dict[str, Any]:
        """Get Ethernet connection status"""
        try:
            if self._system == "Windows":
                result = subprocess.run(
                    ["netsh", "interface", "show", "interface"],
                    capture_output=True, text=True
                )
                connected = "Connected" in result.stdout and "Ethernet" in result.stdout
                
            elif self._system == "Darwin":
                # Check if en0 or en1 is active
                result = subprocess.run(
                    ["ifconfig", "en0"],
                    capture_output=True, text=True
                )
                connected = "status: active" in result.stdout
                
            else:  # Linux
                result = subprocess.run(
                    ["nmcli", "device", "status"],
                    capture_output=True, text=True
                )
                connected = "ethernet" in result.stdout.lower() and "connected" in result.stdout.lower()
            
            return {
                "success": True,
                "connected": connected,
                "interface": "Ethernet"
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def connect_vpn(self, vpn_type: VPNType) -> Dict[str, Any]:
        """Connect to VPN"""
        try:
            self._current_vpn = vpn_type
            
            if vpn_type == VPNType.NONE:
                # Disconnect any active VPN
                if self._system == "Windows":
                    subprocess.Popen(["rasdial", "/disconnect"], shell=False)
                elif self._system == "Darwin":
                    # macOS - disconnect VPN
                    pass
                else:
                    subprocess.Popen(["nmcli", "connection", "down", "vpn"], shell=False)
                
                return {"success": True, "connected": False, "vpn": "None"}
            
            # Connect to specific VPN (would need configuration)
            vpn_name = vpn_type.value
            
            if self._system == "Windows":
                # Would use rasdial with VPN name
                pass
            elif self._system == "Darwin":
                # Would use networksetup
                pass
            else:
                subprocess.Popen(["nmcli", "connection", "up", vpn_name.lower()], shell=False)
            
            return {
                "success": True,
                "connected": True,
                "vpn": vpn_type.value
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_bandwidth_usage(self) -> Dict[str, Any]:
        """Get current bandwidth usage"""
        try:
            # This is a simplified version - real implementation would track over time
            import psutil
            
            net_io = psutil.net_io_counters()
            
            return {
                "success": True,
                "download_mbps": round(net_io.bytes_recv / 1024 / 1024, 2),
                "upload_mbps": round(net_io.bytes_sent / 1024 / 1024, 2),
                "packets_recv": net_io.packets_recv,
                "packets_sent": net_io.packets_sent,
                "err_in": net_io.errin,
                "err_out": net_io.errout
            }
            
        except ImportError:
            return {"success": False, "error": "psutil not installed"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def test_connection(self, host: str = "8.8.8.8", port: int = 53, timeout: int = 3) -> Dict[str, Any]:
        """Test network connectivity"""
        try:
            socket.setdefaulttimeout(timeout)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex((host, port))
            sock.close()
            
            if result == 0:
                return {
                    "success": True,
                    "connected": True,
                    "host": host,
                    "port": port,
                    "latency_ms": None  # Would need actual ping for latency
                }
            else:
                return {
                    "success": True,
                    "connected": False,
                    "host": host,
                    "port": port,
                    "error_code": result
                }
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_network_info(self) -> Dict[str, Any]:
        """Get network interface information"""
        try:
            import psutil
            
            interfaces = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            
            result = {}
            for name, addrs in interfaces.items():
                result[name] = {
                    "addresses": [
                        {
                            "address": addr.address,
                            "family": str(addr.family),
                            "netmask": addr.netmask,
                            "broadcast": addr.broadcast
                        }
                        for addr in addrs
                    ],
                    "is_up": stats.get(name, {}).isup if name in stats else False,
                    "speed": stats.get(name, {}).speed if name in stats else None
                }
            
            return {"success": True, "interfaces": result}
            
        except ImportError:
            return {"success": False, "error": "psutil not installed"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_status(self) -> Dict[str, Any]:
        """Get network manager status"""
        wifi = self.get_wifi_status()
        ethernet = self.get_ethernet_status()
        bandwidth = self.get_bandwidth_usage()
        connection_test = self.test_connection()
        
        return {
            "platform": self._system,
            "wifi": wifi if wifi.get("success") else None,
            "ethernet": ethernet if ethernet.get("success") else None,
            "bandwidth": bandwidth if bandwidth.get("success") else None,
            "current_vpn": self._current_vpn.value,
            "internet_connected": connection_test.get("connected", False)
        }


def get_network_manager() -> NetworkManager:
    """Get the singleton NetworkManager instance"""
    return NetworkManager()
