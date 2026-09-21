"""Multi-synthesis ratchet test for the TTS worker (leak check).

Spawns the worker once, then runs N syntheses and reports private/rss after
each — a ratchet (linear growth) is the leak the audio-pipeline doc warns about
(MKL fast-MM, session-306). Read-only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

PROJECT = Path(__file__).resolve().parent.parent
PY = sys.executable


def mem(pid: int):
    try:
        p = psutil.Process(pid)
        mi = p.memory_info()
        private = getattr(mi, "private", None) or mi.rss
        return round(private / (1024 ** 2), 1), round(mi.rss / (1024 ** 2), 1)
    except Exception:
        return -1.0, -1.0


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    env = {
        **os.environ,
        "PYTHONPATH": str(PROJECT) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        "MKL_DISABLE_FAST_MM": os.environ.get("MKL_DISABLE_FAST_MM", "1"),
    }
    proc = subprocess.Popen(
        [PY, "-u", "-m", "backend.audio.tts_worker"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, cwd=str(PROJECT), env=env,
    )
    pid = proc.pid
    lines: list[str] = []
    lock = threading.Lock()

    def reader():
        assert proc.stdout is not None
        for line in proc.stdout:
            with lock:
                lines.append(line.strip())

    threading.Thread(target=reader, daemon=True).start()

    def wait_for(pred, timeout):
        end = time.time() + timeout
        while time.time() < end:
            with lock:
                for ln in lines:
                    if pred(ln):
                        return ln
            time.sleep(0.15)
        return None

    if not wait_for(lambda ln: '"status": "ready"' in ln, 240):
        print("TIMEOUT ready")
        proc.kill()
        return 1
    time.sleep(3)
    p, r = mem(pid)
    print(f"after-ready     private={p:>7} MB  rss={r:>7} MB", flush=True)

    text = ("Measuring the text to speech worker memory across repeated "
            "synthesis requests to detect any per-request growth or leak.")
    for i in range(1, n + 1):
        assert proc.stdin is not None
        proc.stdin.write(json.dumps({"action": "synthesize", "text": text, "id": i}) + "\n")
        proc.stdin.flush()
        if not wait_for(lambda ln, i=i: f'"id": {i}' in ln and '"type": "done"' in ln, 120):
            print(f"synth {i} TIMEOUT")
            break
        time.sleep(0.5)
        p, r = mem(pid)
        print(f"synth {i:>2}         private={p:>7} MB  rss={r:>7} MB", flush=True)

    time.sleep(20)
    p, r = mem(pid)
    print(f"+20s after last private={p:>7} MB  rss={r:>7} MB", flush=True)

    try:
        proc.stdin.write(json.dumps({"action": "shutdown"}) + "\n")
        proc.stdin.flush()
    except Exception:
        pass
    time.sleep(2)
    try:
        proc.kill()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
