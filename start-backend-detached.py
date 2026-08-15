"""
Detached backend launcher for manual live testing.
Mirrors start_all.py's CREATE_NEW_PROCESS_GROUP so the backend survives
independently of the launching shell (avoids the tool-call teardown that
killed the directly-launched backend).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

base_dir = Path(__file__).resolve().parent
py = base_dir / "venv" / "Scripts" / "python.exe"


def main() -> int:
    import os
    os.chdir(base_dir)
    # Disable bytecode cache for the spawned backend too (inherited by child).
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    log_path = base_dir / "logs" / "backend_detached.log"
    log_fh = open(log_path, "ab", buffering=0)
    kwargs = {
        "cwd": str(base_dir),
        "stdout": log_fh,
        "stderr": subprocess.STDOUT,
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
    }
    proc = subprocess.Popen([str(py), "start-backend.py"], **kwargs)
    print(f"backend launched PID {proc.pid}, log -> {log_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
