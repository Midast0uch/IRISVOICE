"""
IRIS Backend Startup Script
Uses uvicorn programmatically to avoid subprocess Python path issues
"""
import os
import sys

# ── Bulletproof UTF-8 mode from ANY shell ──────────────────────────────────
# On Windows a non-TTY / piped stdout uses a 'charmap' codec that cannot
# encode non-ASCII (e.g. the '→' arrow in some log lines). That raises
# UnicodeEncodeError and aborts backend startup depending on how the process
# was launched. Python's UTF-8 mode (PYTHONUTF8 / -X utf8) makes all stdio
# UTF-8 at the C level — the only reliable, shell-independent fix.
# If we weren't started in UTF-8 mode, re-exec ourselves with -X utf8 so the
# rest of this script (and uvicorn) always runs with UTF-8 stdio.
if not getattr(sys.flags, "utf8_mode", 0):
    import subprocess

    # Preserve PYTHONPATH / working dir; re-launch same interpreter + args.
    os.execl(sys.executable, sys.executable, "-X", "utf8", *sys.argv)
    # os.execl replaces the process; the line below is unreachable.
    raise SystemExit(subprocess.call([sys.executable, "-X", "utf8", *sys.argv]))

import io
import signal
import asyncio
from pathlib import Path

# ── Force UTF-8 stdout/stderr (belt-and-suspenders, in case -X utf8 is unavailable) ──
# On Windows a non-TTY / piped stdout uses a 'charmap' codec that cannot
# encode non-ASCII (e.g. the '→' arrow in some log lines). That raises
# UnicodeEncodeError and aborts backend startup depending on how the
# process was launched. Reconfiguring the streams to UTF-8 (errors="replace")
# makes startup reliable from any shell.
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    else:  # Python <3.7 fallback
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
except Exception:
    pass
try:
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    else:
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace"
        )
except Exception:
    pass

# Get the directory containing this script (project root)
base_dir = Path(__file__).parent.resolve()
os.chdir(base_dir)

# Add project root to Python path BEFORE any imports
sys.path.insert(0, str(base_dir))

# Set PYTHONPATH environment variable for subprocesses
os.environ['PYTHONPATH'] = str(base_dir) + os.pathsep + os.environ.get('PYTHONPATH', '')

# Load environment variables from .env file
from dotenv import load_dotenv
# Load .env (defaults), then .env.local (secrets override)
load_dotenv(base_dir / ".env")
load_dotenv(base_dir / ".env.local", override=True)

# Set HF_HUB_DISABLE_SYMLINKS_WARNING for HuggingFace
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')

# Ensure a CA bundle is configured for outbound HTTPS (httpx/requests).
# This machine's OpenSSL ships with no system CA bundle (cafile=None on
# Windows), which broke every cloud LLM call with CERTIFICATE_VERIFY_FAILED.
# If .env.local didn't already set these, resolve the certifi bundle here.
# Done before importing uvicorn/app so every outbound client picks it up.
if not os.environ.get('SSL_CERT_FILE') or not os.environ.get('REQUESTS_CA_BUNDLE'):
    try:
        import certifi
        _ca = certifi.where()
        os.environ.setdefault('SSL_CERT_FILE', _ca)
        os.environ.setdefault('REQUESTS_CA_BUNDLE', _ca)
        print(f"   TLS CA bundle resolved via certifi: {_ca}")
    except Exception as _ca_exc:
        print(f"   WARNING: could not resolve certifi CA bundle ({_ca_exc})")

# Now import and run uvicorn
import uvicorn

# ---------------------------------------------------------------------------
# Harden uvicorn's loggers against non-UTF-8 stdout (Windows charmap).
# Uvicorn installs its own "uvicorn"/"uvicorn.error"/"uvicorn.access"
# StreamHandlers that emit non-ASCII (e.g. the '→' arrow in port logs).
# On a piped/non-TTY stdout this raises UnicodeEncodeError. Reconfigure
# those handlers to UTF-8 so startup is clean from any shell.
# ---------------------------------------------------------------------------
def _harden_uvicorn_loggers() -> None:
    import logging

    for _name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        _log = logging.getLogger(_name)
        for _h in _log.handlers:
            _stream = getattr(_h, "stream", None)
            if _stream is None:
                continue
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_harden_uvicorn_loggers()

# Read backend port from config (env var override: IRIS_BACKEND_PORT)
try:
    from backend.iris_config import load_config
    _cfg = load_config()
    BACKEND_PORT: int = _cfg.ports.backend_port
except Exception as _exc:
    print(f"   Warning: could not load port config ({_exc}), using default port 8090")
    BACKEND_PORT = int(os.environ.get("IRIS_BACKEND_PORT", 8090))

# ---------------------------------------------------------------------------
# Port cleanup: kill any existing process holding our port so we never
# see "error while attempting to bind on address".
# ---------------------------------------------------------------------------
def _kill_port(port: int) -> None:
    """Terminate any process listening on *port* (Windows + Unix)."""
    import subprocess
    try:
        if sys.platform == "win32":
            # netstat -ano lists all TCP listeners; find our port, extract PID
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True
            )
            for line in result.stdout.splitlines():
                if f":{port} " in line and "LISTENING" in line:
                    parts = line.split()
                    pid = int(parts[-1])
                    if pid and pid != os.getpid():
                        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                       capture_output=True)
                        print(f"   Killed stale process PID {pid} on port {port}")
        else:
            # lsof -ti :<port> returns PID(s) listening on that port
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True
            )
            for pid_str in result.stdout.strip().splitlines():
                pid = int(pid_str)
                if pid and pid != os.getpid():
                    os.kill(pid, signal.SIGTERM)
                    print(f"   Killed stale process PID {pid} on port {port}")
    except Exception as exc:
        # Non-fatal: if we can't kill the old process, uvicorn will fail with
        # a clear bind error rather than silently misbehaving.
        print(f"   Warning: could not clear port {port}: {exc}")

_kill_port(BACKEND_PORT)

# After killing, verify port is free.  If still occupied, find the next free one.
try:
    from backend.utils.port_checker import resolve_ports as _resolve_ports
    _resolved = _resolve_ports("0.0.0.0", {"backend": BACKEND_PORT})
    if _resolved["backend"] != BACKEND_PORT:
        print(f"   Port {BACKEND_PORT} still occupied after kill — falling back to {_resolved['backend']}")
        BACKEND_PORT = _resolved["backend"]
except Exception:
    pass  # non-fatal: if port is really taken, uvicorn will fail with a clear error

# Global flag for graceful shutdown
shutdown_flag = False

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global shutdown_flag
    print(f"\nReceived signal {signum}, shutting down...")
    shutdown_flag = True
    sys.exit(0)

async def run_server():
    """Run the uvicorn server asynchronously"""
    host = os.environ.get("IRIS_BACKEND_HOST", "0.0.0.0")
    config = uvicorn.Config(
        "backend.main:app",
        host=host,
        port=BACKEND_PORT,
        reload=False,  # Disabled for Windows compatibility
        log_level="info"
    )
    server = uvicorn.Server(config)

    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print(f"Starting uvicorn server on http://{host}:{BACKEND_PORT}")
    print(f"  (If tailscale is active, your phone can reach this at http://<machine>.<tailnet>.ts.net:{BACKEND_PORT})")
    await server.serve()

def main():
    """Start the IRIS backend server"""
    print(">> Starting IRIS Backend...")
    print(f"   Python: {sys.executable}")
    print(f"   Base dir: {base_dir}")
    print(f"   Python path: {sys.path[0]}")
    print(f"   PYTHONPATH: {os.environ.get('PYTHONPATH', 'not set')}")
    print()
    
    try:
        print("Starting async server...")
        asyncio.run(run_server())
        print("Server stopped normally")
    except KeyboardInterrupt:
        print("\n\n[OK] Server stopped by user")
    except Exception as e:
        print(f"\n[ERROR] Error starting server: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
