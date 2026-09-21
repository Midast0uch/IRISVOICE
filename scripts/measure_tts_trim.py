"""Decisive test: does EmptyWorkingSet (the trim the worker calls) actually
drop the TTS worker's resident footprint? Spawns the worker, waits ready,
then trims externally and measures before/after."""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

import psutil

PROJECT = Path(__file__).resolve().parent.parent
PY = sys.executable

PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_INFORMATION = 0x0400


def mem(pid: int):
    try:
        p = psutil.Process(pid)
        mi = p.memory_info()
        private = getattr(mi, "private", None) or mi.rss
        return round(private / (1024 ** 2), 1), round(mi.rss / (1024 ** 2), 1)
    except Exception:
        return -1.0, -1.0


def empty_working_set(pid: int) -> int:
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        return -1
    try:
        rc = ctypes.windll.psapi.EmptyWorkingSet(h)
        return rc
    finally:
        k32.CloseHandle(h)


def main() -> int:
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
    print(f"after-ready      private={p:>7} MB  rss={r:>7} MB", flush=True)

    rc = empty_working_set(pid)
    time.sleep(2)
    p, r = mem(pid)
    print(f"after-trim rc={rc} private={p:>7} MB  rss={r:>7} MB", flush=True)

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
