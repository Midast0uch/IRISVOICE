"""
IRIS Backend Idle Memory Profiler
Records RSS/VMS/CPU% of all iris-backend* and IRIS-related Python processes
every 5 seconds for 5 minutes.  Writes a CSV to backend/logs/.

Usage (while backend is running):
    python scripts/profile_backend_idle.py

Output: backend/logs/idle_profile_<UTC>.csv
"""
import csv
import datetime
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DURATION_S = 300   # 5 minutes
INTERVAL_S = 5     # sample every 5 s
OUT_DIR = Path(__file__).parent.parent / "backend" / "logs"

try:
    import psutil
except ImportError:
    print("[ERROR] psutil not installed.  Run: pip install psutil")
    sys.exit(1)


def _is_iris_process(proc: psutil.Process) -> bool:
    """Return True if this process is the IRIS backend."""
    try:
        name = (proc.name() or "").lower()
        if "iris-backend" in name:
            return True
        cmdline = " ".join(proc.cmdline()).lower()
        return "backend.main" in cmdline or "start-backend" in cmdline
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    out_path = OUT_DIR / f"idle_profile_{ts}.csv"

    print(f"Profiling for {DURATION_S}s → {out_path}")
    print("Make sure the backend is running and DO NOT interact with IRIS during this run.")
    print()

    # Initialise CPU% counters (first call returns 0.0)
    all_procs = [p for p in psutil.process_iter() if _is_iris_process(p)]
    for p in all_procs:
        try:
            p.cpu_percent(interval=None)
        except Exception:
            pass

    with out_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "elapsed_s", "ts", "pid", "name",
            "rss_mb", "vms_mb", "cpu_pct",
            "num_threads", "status",
        ])

        end = time.monotonic() + DURATION_S
        t0 = time.monotonic()
        samples = 0

        while time.monotonic() < end:
            elapsed = time.monotonic() - t0
            now_ts = datetime.datetime.utcnow().isoformat()

            procs = [p for p in psutil.process_iter() if _is_iris_process(p)]
            if not procs:
                print(f"  t={elapsed:.0f}s  No matching processes — is backend running?")
            else:
                for p in procs:
                    try:
                        mi = p.memory_info()
                        cpu = p.cpu_percent(interval=None)
                        writer.writerow([
                            f"{elapsed:.1f}",
                            now_ts,
                            p.pid,
                            p.name(),
                            f"{mi.rss / 1e6:.1f}",
                            f"{mi.vms / 1e6:.1f}",
                            f"{cpu:.1f}",
                            p.num_threads(),
                            p.status(),
                        ])
                        if samples % 6 == 0:  # print every ~30 s
                            print(f"  t={elapsed:5.0f}s  PID={p.pid}  RSS={mi.rss/1e6:.0f}MB"
                                  f"  CPU={cpu:.1f}%  threads={p.num_threads()}")
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

            f.flush()
            samples += 1
            time.sleep(INTERVAL_S)

    # --- Summary ---
    print(f"\nDone. CSV written to: {out_path}")
    _print_summary(out_path)


def _print_summary(path: Path) -> None:
    """Print min/max/mean RSS from the CSV."""
    rows = []
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rows.append(float(row["rss_mb"]))
            except (ValueError, KeyError):
                pass
    if not rows:
        print("No data collected.")
        return
    print(f"\nRSS Summary over {DURATION_S}s idle:")
    print(f"  Min : {min(rows):.0f} MB")
    print(f"  Max : {max(rows):.0f} MB")
    print(f"  Mean: {sum(rows)/len(rows):.0f} MB")
    print(f"  Δ   : {max(rows)-min(rows):.0f} MB  (should be small for idle; large delta = memory churn)")


if __name__ == "__main__":
    main()
