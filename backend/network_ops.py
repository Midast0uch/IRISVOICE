"""Network operations for IRIS backend — Tailscale, QR codes, URL generation."""

import subprocess
import logging
import socket
import os

logger = logging.getLogger("irisvoice")


TAILSCALE_BINARY = "tailscale"


def _find_tailscale() -> str | None:
    """Return the Tailscale binary path, or None if not installed."""
    import shutil
    path = shutil.which(TAILSCALE_BINARY)
    if path:
        return path
    # Common install paths on Windows
    win_paths = [
        r"C:\Program Files\Tailscale\tailscale.exe",
        r"C:\Program Files (x86)\Tailscale\tailscale.exe",
    ]
    for p in win_paths:
        if os.path.exists(p):
            return p
    return None


def _tailscale_service_running() -> bool:
    """Check if the Tailscale Windows service is running."""
    try:
        result = subprocess.run(
            ["sc", "query", "Tailscale"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        return "RUNNING" in result.stdout
    except Exception:
        return False


def get_tailscale_status() -> dict:
    """Return Tailscale status if available.

    Returns a dict with:
        installed: bool
        service_running: bool
        connected: bool
        raw: dict  # raw tailscale status JSON when connected
    """
    binary = _find_tailscale()
    if not binary:
        return {
            "installed": False,
            "service_running": False,
            "connected": False,
            "raw": {},
        }

    service_running = _tailscale_service_running()
    if not service_running:
        return {
            "installed": True,
            "service_running": False,
            "connected": False,
            "raw": {},
        }

    try:
        result = subprocess.run(
            [binary, "status", "--json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode == 0:
            import json
            raw = json.loads(result.stdout)
            ips = raw.get("TailscaleIPs", []) or []
            connected = len(ips) > 0
            return {
                "installed": True,
                "service_running": True,
                "connected": connected,
                "raw": raw,
            }
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    except Exception as e:
        logger.debug(f"[network_ops] tailscale status error: {e}")

    return {
        "installed": True,
        "service_running": True,
        "connected": False,
        "raw": {},
    }


def start_tailscale_service() -> dict:
    """Start the Tailscale Windows service if it is not already running.

    Returns a dict with:
        started: bool          # True if we actually started it this call
        service_running: bool  # True if the service is running afterwards
        error: str | None      # human-readable error, or None on success
    """
    binary = _find_tailscale()
    if not binary:
        return {
            "started": False,
            "service_running": False,
            "error": "Tailscale is not installed.",
        }

    # Already running — nothing to do.
    if _tailscale_service_running():
        return {"started": False, "service_running": True, "error": None}

    try:
        result = subprocess.run(
            ["sc", "start", "Tailscale"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        running = _tailscale_service_running()
        if running or "RUNNING" in (result.stdout or "").upper():
            return {"started": True, "service_running": True, "error": None}
        return {
            "started": False,
            "service_running": running,
            "error": (
                (result.stderr or result.stdout or "Failed to start Tailscale service.")
                .strip()
            ),
        }
    except Exception as e:
        logger.warning(f"[network_ops] failed to start Tailscale service: {e}")
        return {
            "started": False,
            "service_running": _tailscale_service_running(),
            "error": str(e),
        }


def get_local_ip() -> str:
    """Return the local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        s.connect(("8.8.8.8", 1))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "127.0.0.1"


def get_backend_port() -> int:
    """Return the configured backend port.

    Env var IRIS_BACKEND_PORT overrides the value from iris_config, so the
    port is never hardcoded and always stays in sync with the running server.
    """
    env_port = os.environ.get("IRIS_BACKEND_PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            pass
    try:
        from backend.iris_config import load_config
        return int(load_config().ports.backend_port)
    except Exception:
        return 8090


def get_iris_urls(ip: str | None = None) -> dict:
    """Return local and Tailscale URLs for IRIS."""
    local_ip = ip or get_local_ip()

    tailscale_name = ""
    tailscale_ip = None
    try:
        ts = get_tailscale_status()
        if ts.get("connected"):
            raw = ts.get("raw", {})
            self_info = raw.get("Self", {}) or {}
            tailscale_name = self_info.get("DNSName", "").rstrip(".")
            ips = raw.get("TailscaleIPs", []) or []
            tailscale_ip = ips[0] if ips else None
    except Exception:
        pass

    bp = get_backend_port()
    urls = {
        "local": f"http://{local_ip}:8080",
        "backend": f"http://{local_ip}:{bp}",
        "launcher": f"http://{local_ip}:8080",
        "chat": f"http://{local_ip}:3000",
        "api": f"http://{local_ip}:{bp}",
    }
    if tailscale_ip:
        urls["tailscale"] = f"http://{tailscale_ip}:8080"
    if tailscale_name:
        urls["tailscale_magicdns"] = f"http://{tailscale_name}:8080"
    # Widget (spotlight chat) via Tailscale — ?remote=1 forces mobile-optimized view, ?mode=personal disables developer terminal
    if tailscale_ip:
        urls["widget_tailscale"] = f"http://{tailscale_ip}:3000/?remote=1&mode=personal"
    if tailscale_name:
        urls["widget_magicdns"] = f"http://{tailscale_name}:3000/?remote=1&mode=personal"

    return urls


def get_formatted_network_status() -> dict:
    """Return formatted network status matching the frontend TailscalePage contract."""
    ts = get_tailscale_status()
    raw = ts.get("raw", {})

    # Tailscale IPs
    tailscale_ips = raw.get("TailscaleIPs", []) or []
    ip = tailscale_ips[0] if tailscale_ips else None

    # Self info
    self_info = raw.get("Self", {}) or {}
    machine_name = self_info.get("HostName", "") or self_info.get("DNSName", "").rstrip(".")
    dns_name = self_info.get("DNSName", "")
    tailnet_name = ""
    if dns_name:
        parts = dns_name.rstrip(".").split(".")
        if len(parts) >= 2:
            tailnet_name = ".".join(parts[1:])

    connected = ts.get("connected", False) or bool(ip)

    # Determine the human-readable status
    if not ts.get("installed"):
        detected_state = "not_installed"
    elif not ts.get("service_running"):
        detected_state = "stopped"
    elif connected:
        detected_state = "connected"
    else:
        detected_state = "not_connected"

    return {
        "_detected_state": detected_state,
        "tailscale": {
            "connected": connected,
            "ip": ip,
            "machine_name": machine_name,
            "tailnet_name": tailnet_name,
        },
        "urls": get_iris_urls(),
    }


def generate_qr_png(data: str, size: int = 256) -> bytes:
    """Generate a QR code PNG for the given data."""
    try:
        import qrcode
        from io import BytesIO

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img = img.resize((size, size))
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        logger.warning("[network_ops] qrcode module not installed, returning empty PNG")
        return b""
    except Exception as e:
        logger.error(f"[network_ops] QR generation failed: {e}")
        return b""
