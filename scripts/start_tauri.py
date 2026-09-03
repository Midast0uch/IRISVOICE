"""
IRIS — Tauri launch script.

Starts the backend, then launches `npx tauri dev` which runs the
Next.js frontend on port 3001 (see src-tauri/tauri.conf.json).

Environment variables (optional):
  IRIS_BACKEND_PORT   — backend port (default: 8090)
  IRIS_FRONTEND_PORT  — frontend port for Tauri (default: 3001, from tauri.conf.json)
"""

import os, sys, time, subprocess, signal
from pathlib import Path

BASE = Path(__file__).parent.parent.resolve()
os.chdir(BASE)
sys.path.insert(0, str(BASE))
os.environ["PYTHONPATH"] = str(BASE) + os.pathsep + os.environ.get("PYTHONPATH", "")

from dotenv import load_dotenv
load_dotenv(BASE / ".env")
load_dotenv(BASE / ".env.local", override=True)

BACKEND_PORT = int(os.environ.get("IRIS_BACKEND_PORT", 8090))
TAURI_FRONTEND_PORT = 3001  # matches src-tauri/tauri.conf.json

os.environ.setdefault("IRIS_BACKEND_PORT", str(BACKEND_PORT))
os.environ.setdefault("NEXT_PUBLIC_WS_URL", f"ws://localhost:{BACKEND_PORT}/ws/iris")

print(f"  Backend:  http://localhost:{BACKEND_PORT}")
print(f"  Tauri:    http://localhost:{TAURI_FRONTEND_PORT} (managed by Tauri)")

# ── Port cleanup ──────────────────────────────────────────────────────────
def _kill_port(port: int, label: str = "") -> None:
    import subprocess as _sp
    try:
        if sys.platform == "win32":
            r = _sp.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=5)
            for line in r.stdout.splitlines():
                if f":{port} " in line and "LISTENING" in line:
                    pid = int(line.split()[-1])
                    if pid and pid != os.getpid():
                        _sp.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=3)
                        print(f"   Killed PID {pid} on port {port}{label}")
        else:
            r = _sp.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True, timeout=5)
            for ps in r.stdout.strip().splitlines():
                pid = int(ps)
                if pid and pid != os.getpid():
                    os.kill(pid, signal.SIGTERM)
                    print(f"   Killed PID {pid} on port {port}{label}")
    except Exception as exc:
        print(f"   Warning: could not clear port {port}: {exc}")

for p in [BACKEND_PORT, TAURI_FRONTEND_PORT]:
    _kill_port(p)

# ── Start backend via uvicorn ─────────────────────────────────────────────
import uvicorn
import threading

def _run_backend():
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=BACKEND_PORT,
        log_level="info",
        reload=False,
    )

t = threading.Thread(target=_run_backend, daemon=True, name="iris-backend")
t.start()
time.sleep(2)

# ── Launch Tauri dev ──────────────────────────────────────────────────────
print("Starting Tauri dev...")
tauri_proc = subprocess.Popen(
    ["npx", "tauri", "dev"],
    cwd=str(BASE),
    env={**os.environ},
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)

try:
    tauri_proc.wait()
except KeyboardInterrupt:
    print("\nShutting down...")
    tauri_proc.terminate()
    tauri_proc.wait(timeout=5)
    sys.exit(0)
