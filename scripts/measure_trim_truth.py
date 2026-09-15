"""Decisive: does memory_trim.trim_working_set() actually trim?

Allocates a large resident buffer, measures working set, calls the project's
trim_working_set(), measures again. Also compares the pseudo-handle path (what
memory_trim uses) vs a real OpenProcess handle.
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def ws_mb() -> float:
    return round(psutil.Process(os.getpid()).memory_info().rss / (1024 ** 2), 1)


def main() -> int:
    # Allocate ~600MB and touch it so it is resident.
    blob = bytearray(600 * 1024 * 1024)
    for i in range(0, len(blob), 4096):
        blob[i] = 1
    print(f"after-alloc        rss={ws_mb():>7} MB", flush=True)

    # ── Path 1: the project's trim (pseudo-handle via GetCurrentProcess) ──
    from backend.utils.memory_trim import trim_working_set
    trim_working_set()
    import time
    time.sleep(1)
    print(f"after trim_working_set() rss={ws_mb():>7} MB  (pseudo-handle path)", flush=True)

    # re-touch to make it resident again
    for i in range(0, len(blob), 4096):
        blob[i] = 2
    print(f"re-touched         rss={ws_mb():>7} MB", flush=True)

    # ── Path 2: explicit real handle ──
    k32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    psapi.EmptyWorkingSet.restype = ctypes.c_int
    psapi.EmptyWorkingSet.argtypes = [ctypes.c_void_p]
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    h = k32.OpenProcess(0x0100 | 0x0400, False, os.getpid())
    rc = psapi.EmptyWorkingSet(h)
    k32.CloseHandle(h)
    time.sleep(1)
    print(f"after real-handle EmptyWorkingSet rc={rc} rss={ws_mb():>7} MB", flush=True)

    _ = blob  # keep alive
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
