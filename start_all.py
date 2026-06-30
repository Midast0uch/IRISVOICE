"""
IRIS All-In-One Startup Script
Spawns Parakeet ASR + Backend + Frontend in sequence, waits for each to
become healthy, and tears them all down on Ctrl+C.

Why three services?
  * Parakeet  (port 8765) -- HuggingFace Parakeet TDT 0.6B on local GPU.
                              Isolated because torch/CUDA + asyncio are
                              happier in their own process.
  * Backend   (port 8090) -- FastAPI: wake word, TTS, orchestrator.
  * Frontend  (port 3000) -- Next.js dev server.

The script exits as soon as the last service prints "ready", so you can
hit the frontend immediately.  All three child processes share a process
group (Windows Job Object) so Ctrl+C kills them all.

Usage:
  venv\Scripts\python.exe start_all.py           # start everything
  venv\Scripts\python.exe start_all.py --no-fe   # backend + parakeet only
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

base_dir = Path(__file__).parent.resolve()


# ---------------------------------------------------------------------------
# Pretty printing
# ---------------------------------------------------------------------------
def _tag(tag: str, color: str) -> str:
    return f"\033[{color}m[{tag:<9}]\033[0m"


def _say(tag: str, msg: str, color: str = "36") -> None:
    """Print a timestamped, colored status line. Flush immediately so
    progress is visible even when a child is blocking stdout."""
    ts = time.strftime("%H:%M:%S")
    print(f"{ts} {_tag(tag, color)} {msg}", flush=True)


# ---------------------------------------------------------------------------
# Service definitions
# ---------------------------------------------------------------------------
class Service:
    """One background service.  Tracks its subprocess and lifecycle."""

    def __init__(self, name: str, cmd: list[str], cwd: Path,
                 health_url: Optional[str], port: int, color: str,
                 log_path: Path) -> None:
        self.name = name
        self.cmd = cmd
        self.cwd = cwd
        self.health_url = health_url
        self.port = port
        self.color = color
        self.log_path = log_path
        self.proc: Optional[subprocess.Popen] = None

    def start(self) -> None:
        """Spawn the subprocess, redirect output to its log file."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(self.log_path, "ab", buffering=0)
        kwargs = {
            "cwd": str(self.cwd),
            "stdout": log_fh,
            "stderr": subprocess.STDOUT,
        }
        if sys.platform == "win32":
            # CREATE_NEW_PROCESS_GROUP so Ctrl+C / kill reaches the child
            # and we can later terminate the whole group at once.
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        self.proc = subprocess.Popen(self.cmd, **kwargs)
        _say(self.name, f"started PID {self.proc.pid}, log -> {self.log_path.name}",
             self.color)

    def wait_ready(self, timeout: float = 120.0,
                   poll_interval: float = 1.0) -> bool:
        """Block until the service is reachable on its health URL,
        or the subprocess dies, or we hit the timeout."""
        if not self.health_url:
            _say(self.name, "no health URL — skipping wait", self.color)
            return True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc and self.proc.poll() is not None:
                _say(self.name, f"DIED before becoming ready (exit={self.proc.returncode})",
                     "31")
                return False
            try:
                with urllib.request.urlopen(self.health_url, timeout=2) as r:
                    if 200 <= r.status < 500:
                        _say(self.name, f"READY ({self.health_url})", "32")
                        return True
            except Exception:
                pass
            time.sleep(poll_interval)
        _say(self.name, f"TIMEOUT waiting for {self.health_url}", "31")
        return False

    def stop(self) -> None:
        if not self.proc or self.proc.poll() is not None:
            return
        _say(self.name, f"stopping PID {self.proc.pid}...", self.color)
        try:
            if sys.platform == "win32":
                # CTRL_BREAK_EVENT reaches the whole process group,
                # so child Python + uvicorn workers all shut down.
                self.proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _say(self.name, "did not exit in 10s, killing", "31")
                self.proc.kill()
                self.proc.wait(timeout=5)
        except Exception as exc:
            _say(self.name, f"stop error: {exc}", "31")


# ---------------------------------------------------------------------------
# Service registry
# ---------------------------------------------------------------------------
def _python_exe() -> str:
    """Resolve the venv Python (or fall back to current interpreter)."""
    candidates = [
        base_dir / "venv" / "Scripts" / "python.exe",
        base_dir / ".venv" / "Scripts" / "python.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return sys.executable


def _build_services(skip_frontend: bool) -> list[Service]:
    """Construct the service list in startup order."""
    py = _python_exe()
    logs = base_dir / "logs"
    services: list[Service] = []

    # 1. Parakeet (GPU ASR) -- start first so the backend can connect.
    services.append(Service(
        name="parakeet",
        cmd=[py, "-m", "backend.audio.parakeet_service"],
        cwd=base_dir,
        health_url="http://127.0.0.1:8765/healthz",
        port=8765,
        color="35",  # magenta
        log_path=logs / "parakeet.log",
    ))

    # 2. Backend (FastAPI) -- depends on parakeet being healthy.
    services.append(Service(
        name="backend",
        cmd=[py, "start-backend.py"],
        cwd=base_dir,
        health_url=None,  # /api/health doesn't exist; we use port-check instead
        port=8090,
        color="36",  # cyan
        log_path=logs / "backend.log",
    ))

    # 3. Frontend (Next.js dev) -- optional.
    if not skip_frontend:
        services.append(Service(
            name="frontend",
            cmd=["cmd", "/c", "npx", "next", "dev", "-H", "0.0.0.0"],
            cwd=base_dir,
            health_url="http://127.0.0.1:3000",
            port=3000,
            color="33",  # yellow
            log_path=logs / "frontend.log",
        ))

    return services


# ---------------------------------------------------------------------------
# Port-based readiness check (for backend, which has no /healthz)
# ---------------------------------------------------------------------------
def _wait_for_port(port: int, timeout: float = 90.0,
                   poll_interval: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}",
                                        timeout=2) as r:
                if 200 <= r.status < 500:
                    return True
        except Exception:
            pass
        time.sleep(poll_interval)
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    skip_frontend = "--no-fe" in flags

    print("=" * 64)
    _say("start_all", f"IRIS multi-service launcher", "1;36")
    _say("start_all", f"Project root: {base_dir}", "37")
    _say("start_all", f"Python:       {_python_exe()}", "37")
    if skip_frontend:
        _say("start_all", "Frontend will be SKIPPED (--no-fe)", "33")
    print("=" * 64)
    print()

    services = _build_services(skip_frontend=skip_frontend)

    # Start each in order, waiting for readiness before moving on.
    try:
        for svc in services:
            svc.start()
            if svc.health_url:
                ok = svc.wait_ready(timeout=180.0)
                if not ok:
                    _say("start_all",
                         f"{svc.name} did not become healthy — aborting",
                         "31")
                    return 1
            else:
                # Backend: wait for its TCP port instead of a health endpoint.
                _say("backend", f"waiting for port {svc.port}...", svc.color)
                if not _wait_for_port(svc.port, timeout=90.0):
                    _say("start_all",
                         f"{svc.name} did not bind port {svc.port} — aborting",
                         "31")
                    return 1
                _say("backend", f"READY (port {svc.port})", "32")

        print()
        _say("start_all", "All services up. Press Ctrl+C to stop everything.",
             "1;32")
        print()

        # Park on the keyboard interrupt; child services run in background.
        try:
            while True:
                time.sleep(1.0)
                # Detect if any service died and surface it.
                for svc in services:
                    if svc.proc and svc.proc.poll() is not None:
                        _say("start_all",
                             f"{svc.name} exited unexpectedly "
                             f"(code={svc.proc.returncode})",
                             "31")
                        raise KeyboardInterrupt
        except KeyboardInterrupt:
            _say("start_all", "Ctrl+C received, shutting down...", "33")

    finally:
        # Tear down in reverse order.
        for svc in reversed(services):
            svc.stop()
        _say("start_all", "All services stopped.", "32")

    return 0


if __name__ == "__main__":
    sys.exit(main())
