"""Keep the backend alive: restart it when the process dies.

WHY (measured 2026-11-02/03): the backend dies with a native access violation
(0xC0000005, exit code 3221225477) under heavy write traffic. The crash has
no Python traceback: the faulting thread is native (the writer thread inside
iris_core.dll), so the only recovery is a restart. Five deaths cost five
traffic batches.

WHAT IT DOES: it watches the pid file that iris_process_manager.py writes and
restarts the service when the process is gone. It does NOT restart on a 503
health answer: the TTS worker reloads itself after its own crash and the
backend stays healthy (measured 2026-11-03 03:52-03:56).

USAGE:
    python scripts/backend_watchdog.py            # run in the foreground
    python scripts/backend_watchdog.py --once     # one check, then exit
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PID_DIR = REPO_ROOT / ".iris-pids"
BACKEND_PID = PID_DIR / "backend.pid"
MANAGER = REPO_ROOT / "scripts" / "iris_process_manager.py"
PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
POLL_S = 30.0


def _pid_alive(pid: int) -> bool:
    """True when the pid exists (Windows: the process must answer a query)."""
    if pid <= 0:
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except Exception:
        return False
    return str(pid) in out


def _read_pid() -> int:
    try:
        return int(BACKEND_PID.read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def _restart(reason: str) -> bool:
    """Restart the backend through the manager (it owns the pid file)."""
    env = dict(os.environ)
    # The Oracle sample fraction must survive the restart: the calibration
    # traffic needs the sampled consumers to record rows.
    env.setdefault("IRIS_ORACLE_SAMPLE_FRACTION", "0.5")
    cmd = [str(PYTHON), str(MANAGER), "start", "--detach", "backend", "--",
           "python", "start-backend.py"]
    print(f"[watchdog] restarting the backend ({reason})", flush=True)
    try:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env,
                              capture_output=True, text=True, timeout=180)
    except Exception as exc:  # noqa: BLE001 - a failed restart must not kill the watchdog
        print(f"[watchdog] restart failed: {exc!r}", flush=True)
        return False
    if proc.returncode != 0:
        print(f"[watchdog] restart returned {proc.returncode}: "
              f"{(proc.stderr or proc.stdout or '')[-300:]}", flush=True)
        return False
    print("[watchdog] restart requested", flush=True)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true",
                    help="check once, restart if the backend is gone, then exit")
    args = ap.parse_args()

    while True:
        pid = _read_pid()
        if pid and not _pid_alive(pid):
            _restart(f"pid {pid} is gone")
        elif not pid:
            print("[watchdog] no backend pid file yet", flush=True)
        if args.once:
            return 0
        time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
