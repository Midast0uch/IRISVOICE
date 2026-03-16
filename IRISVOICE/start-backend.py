"""
IRIS Backend Startup Script
Uses uvicorn programmatically to avoid subprocess Python path issues
"""
import os
import sys
import signal
import asyncio
from pathlib import Path

# Get the directory containing this script (project root)
base_dir = Path(__file__).parent.resolve()
os.chdir(base_dir)

# Add project root to Python path BEFORE any imports
sys.path.insert(0, str(base_dir))

# Set PYTHONPATH environment variable for subprocesses
os.environ['PYTHONPATH'] = str(base_dir) + os.pathsep + os.environ.get('PYTHONPATH', '')

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv(base_dir / ".env")

# Set HF_HUB_DISABLE_SYMLINKS_WARNING for HuggingFace
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')

# Now import and run uvicorn
import uvicorn

# ---------------------------------------------------------------------------
# Port cleanup: kill any existing process holding port 8000 so we never
# see "error while attempting to bind on address ('127.0.0.1', 8000)".
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

_kill_port(8000)

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
    config = uvicorn.Config(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,  # Disabled for Windows compatibility
        log_level="info"
    )
    server = uvicorn.Server(config)
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("Starting uvicorn server...")
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
