"""
IRIS Backend Startup Script
Uses uvicorn programmatically to avoid subprocess Python path issues
"""
import os
import sys
import io
import signal
import asyncio
from pathlib import Path

# ── Force UTF-8 stdout/stderr BEFORE any other imports or logging ──
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

# ── Optional: periodic all-thread stack dump for diagnosing silent hangs ─────
# Off unless IRIS_FAULTHANDLER_DUMP is set to a positive number of seconds.
# A wedged worker thread (e.g. a DER step blocked inside asyncio.run, or an
# await that never returns) is otherwise INVISIBLE: the process stays alive,
# the gateway keeps answering pings, and no log line is ever emitted. This
# writes every thread's stack to faulthandler_dump.log on an interval so the
# blocking frame can be identified instead of inferred.
#   Usage:  set IRIS_FAULTHANDLER_DUMP=20  (dump every 20s)
try:
    _fh_every = float(os.environ.get("IRIS_FAULTHANDLER_DUMP", "0") or 0)
    if _fh_every > 0:
        import faulthandler as _faulthandler

        _fh_path = base_dir / "faulthandler_dump.log"
        _fh_file = open(_fh_path, "w", encoding="utf-8", errors="replace")
        _faulthandler.dump_traceback_later(_fh_every, repeat=True, file=_fh_file)
        print(f"   Faulthandler: dumping all thread stacks every {_fh_every:g}s -> {_fh_path}")
except Exception as _fh_exc:  # never let a diagnostic block startup
    print(f"   Faulthandler setup skipped: {_fh_exc}")

# ── Never trust or write stale bytecode ──────────────────────────────────────
# A prior incident had a running backend (PID 15768) executing OLD .pyc bytecode
# from __pycache__ while the source on disk already carried a fix — the edit was
# invisible at runtime. To make that structurally impossible:
#   1. Disable bytecode writing for this process (no .pyc is ever produced).
#   2. Export the env var so any subprocess/importlib cache is also disabled.
#   3. Purge any pre-existing __pycache__ so stale .pyc from before this guard
#      can never be served on the next launch (self-healing).
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
try:
    import shutil as _shutil
    _purged = 0
    # SCOPED to the project's own Python. rglob from base_dir walked the WHOLE
    # repo — node_modules, .next (which balloons to multi-GB on this machine)
    # and models/ (18 GB of weights). That walk did not finish in 300s when
    # measured, so the backend sat at ~24 MB RSS burning 7s of CPU and never
    # reached uvicorn: it looked like a hang and was really a directory crawl.
    # The guard's intent is unchanged — no IRIS .pyc is ever trusted or
    # written — because every project module lives under these roots.
    for _root in ("backend", "scripts"):
        _dir = Path(base_dir) / _root
        if not _dir.is_dir():
            continue
        for _cache in _dir.rglob("__pycache__"):
            try:
                _shutil.rmtree(_cache, ignore_errors=True)
                _purged += 1
            except Exception:
                pass
    if _purged:
        print(f"   Purged {_purged} stale __pycache__ dir(s) — bytecode cache disabled")
except Exception:
    pass

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
def _port_occupied(port: int) -> bool:
    """Return True if any process is LISTENING on *port* (TCP)."""
    import subprocess
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True
        )
        for line in result.stdout.splitlines():
            if f":{port} " in line and "LISTENING" in line:
                return True
    except Exception:
        pass
    return False


def _kill_port(port: int) -> None:
    """Terminate any process listening on *port* (Windows + Unix).

    Kills the whole process tree (uvicorn + workers) and verifies the port is
    actually freed, escalating to PowerShell if taskkill alone doesn't release
    it. We deliberately do NOT fall back to a different port: the backend must
    stay on the configured port (8090) so the frontend — which is hardcoded to
    8090 — can reach it. Silently drifting to 8091 is exactly what left the orb
    in a permanent "reconnecting" state (and produced the phantom inner glow).
    """
    import subprocess
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True
            )
            for line in result.stdout.splitlines():
                if f":{port} " in line and "LISTENING" in line:
                    parts = line.split()
                    pid = int(parts[-1])
                    if pid and pid != os.getpid():
                        # /T kills the process tree so uvicorn + child workers die.
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                                       capture_output=True)
                        # taskkill can be flaky from some shells — verify and
                        # escalate to PowerShell Stop-Process if still held.
                        if _port_occupied(port):
                            subprocess.run(
                                ["powershell", "-Command",
                                 f"Stop-Process -Id {pid} -Force -Confirm:$false"],
                                capture_output=True)
                        print(f"   Killed stale process PID {pid} on port {port}")
        else:
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
        print(f"   Warning: could not clear port {port}: {exc}")

_kill_port(BACKEND_PORT)

# Verify the configured port is actually free. We must NOT silently fall back
# to another port (e.g. 8091): the frontend is hardcoded to 8090, so a drift
# would leave the UI in a permanent "reconnecting" state. If the port is still
# occupied after the kill above, fail loudly so the operator can free it:
#   netstat -ano -p TCP | findstr :8090   -> note the PID -> taskkill /F /PID <pid>
if _port_occupied(BACKEND_PORT):
    print(f"   ERROR: port {BACKEND_PORT} is still occupied after kill attempt.")
    print(f"   Free it manually, then restart the backend.")
    print(f"     netstat -ano -p TCP | findstr :{BACKEND_PORT}")
    sys.exit(1)

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
