"""Measure the combined private memory of all IRIS backend processes (REQ-7).

Usage:
    python scripts/measure_memory.py                 # print a per-process table
    python scripts/measure_memory.py --assert-idle   # also assert total <= 4.0 GB

Identifies IRIS processes by matching the command line of python processes for
the known backend entry points (uvicorn/main.py, parakeet_worker, tts_worker,
crawl_worker, browser_pool). On Windows reports Private Bytes (psutil
``memory_info().private``) and Working Set (``memory_info().wset``); on other
platforms falls back to RSS for both columns.

Exit code is 0 when the idle assertion passes (or no assertion was requested),
1 when the total exceeds the 4.0 GB warm-idle baseline.
"""

from __future__ import annotations

import argparse
import os
import sys

# Warm-idle gate (decision 9, 2026-09-06): TTS early-spawns at boot, so the
# baseline covers the warm state (measured 3.74 GB). Env override wins.
IDLE_BUDGET_GB = float(os.environ.get("IRIS_IDLE_MEMORY_GB", "4.0"))

# Command-line fragments that identify an IRIS backend process.
_IRIS_MARKERS = (
    "iris",
    "backend",
    "uvicorn",
    "parakeet",
    "tts_worker",
    "crawl_worker",
    "browser_pool",
    "main.py",
)


def _is_iris_process(proc) -> bool:
    """True when a psutil Process looks like an IRIS backend process."""
    try:
        name = (proc.name() or "").lower()
        if "python" not in name and "pythonservice" not in name:
            return False
        cmdline = " ".join(proc.cmdline() or []).lower()
        return any(m in cmdline for m in _IRIS_MARKERS)
    except Exception:  # noqa: BLE001 — a vanished process is not IRIS
        return False


def _mem_mb(proc) -> tuple[float, float]:
    """Return (private_bytes_mb, working_set_mb) for a process."""
    try:
        info = proc.memory_info()
        if sys.platform == "win32":
            private = getattr(info, "private", None)
            wset = getattr(info, "wset", None)
            if private is not None and wset is not None:
                return private / (1024**2), wset / (1024**2)
        # Non-Windows fallback: RSS approximates both columns.
        rss = getattr(info, "rss", 0) or 0
        return rss / (1024**2), rss / (1024**2)
    except Exception:  # noqa: BLE001 — a vanished process reports 0
        return 0.0, 0.0


def measure() -> list[dict]:
    """Return a list of {pid, name, private_mb, wset_mb} for IRIS processes."""
    import psutil

    rows: list[dict] = []
    for proc in psutil.process_iter(["pid", "name"]):
        if not _is_iris_process(proc):
            continue
        private_mb, wset_mb = _mem_mb(proc)
        rows.append(
            {
                "pid": proc.pid,
                "name": proc.name(),
                "private_mb": private_mb,
                "wset_mb": wset_mb,
            }
        )
    rows.sort(key=lambda r: r["private_mb"], reverse=True)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--assert-idle",
        action="store_true",
        help="assert total private memory <= %.1f GB (exit 1 on failure)" % IDLE_BUDGET_GB,
    )
    args = parser.parse_args()

    rows = measure()
    if not rows:
        print("No IRIS backend processes found (is the backend running?).")
        return 0 if not args.assert_idle else 1

    print(f"{'PID':>7}  {'Process':<24} {'Private MB':>12} {'WorkingSet MB':>14}")
    print("-" * 62)
    total_private = 0.0
    total_wset = 0.0
    for r in rows:
        total_private += r["private_mb"]
        total_wset += r["wset_mb"]
        print(
            f"{r['pid']:>7}  {r['name']:<24} {r['private_mb']:>12.1f} {r['wset_mb']:>14.1f}"
        )
    print("-" * 62)
    print(f"TOTAL private: {total_private / 1024:.2f} GB | working set: {total_wset / 1024:.2f} GB")

    if args.assert_idle:
        total_gb = total_private / 1024
        ok = total_gb <= IDLE_BUDGET_GB
        print(
            f"IDLE ASSERT: total private {total_gb:.2f} GB "
            f"{'<= ' if ok else '> '}{IDLE_BUDGET_GB:.1f} GB -> "
            f"{'PASS' if ok else 'FAIL'}"
        )
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())