"""Start uvicorn as a background process with proper logging and wait for it."""

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

base = Path(__file__).parent.resolve()
log_path = base / "backend" / "logs" / "uvicorn_live3.log"
log_path.parent.mkdir(parents=True, exist_ok=True)

log_out = open(log_path, "ab", buffering=0)

proc = subprocess.Popen(
    [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--log-level",
        "info",
    ],
    stdout=log_out,
    stderr=subprocess.STDOUT,
    cwd=str(base),
    env={
        **os.environ,
        # Raise memory caps — F5-TTS on CUDA uses ~1.6 GB RSS + backend baseline
        "IRIS_MEM_SOFT_MB": "2000",
        "IRIS_MEM_HARD_MB": "3200",
        # Limit CUDA eager pre-allocation so RSS stays closer to actual usage
        "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
    },
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
)
print(f"Started PID: {proc.pid}")

for i in range(40):
    time.sleep(1)
    try:
        resp = urllib.request.urlopen("http://localhost:8000/health", timeout=2)
        if resp.status == 200:
            print("Backend healthy!")
            break
    except Exception:
        pass
else:
    print("Backend did not start within 40s")
    sys.exit(1)
