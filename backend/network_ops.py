"""Network operations for IRIS backend — Tailscale, QR codes, URL generation."""

import subprocess
import logging

logger = logging.getLogger("irisvoice")


def get_tailscale_status() -> dict:
    """Return Tailscale status if available."""
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode == 0:
            import json
            return json.loads(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    except Exception as e:
        logger.debug(f"[network_ops] tailscale status error: {e}")
    return {"TailscaleIPs": [], "Self": {"DNSName": ""}, "Peer": []}


def get_iris_urls(ip: str | None = None) -> dict:
    """Return local and Tailscale URLs for IRIS."""
    import socket

    local_ip = ip or "127.0.0.1"
    if not ip:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0)
            s.connect(("8.8.8.8", 1))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass

    tailscale_name = ""
    try:
        ts = get_tailscale_status()
        self_info = ts.get("Self", {})
        tailscale_name = self_info.get("DNSName", "").rstrip(".")
    except Exception:
        pass

    urls = {
        "local": f"http://{local_ip}:3000",
        "backend": f"http://{local_ip}:8000",
        "launcher": f"http://{local_ip}:3000/launcher",
    }
    if tailscale_name:
        urls["tailscale"] = f"http://{tailscale_name}:3000"

    return urls


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
