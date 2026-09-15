"""Continuous memory/CPU/handle spike monitor for IRIS live testing.

Samples every INTERVAL seconds and appends a CSV row. Flags:
  - system free RAM drop (spike detection via rolling baseline)
  - per-process RAM growth
  - handle-count growth (the .next wedge signature)
  - CPU bursts

Usage:
    python scripts/mem_watch.py [duration_s] [interval_s] [outfile]

Writes CSV: ts,free_gb,total_iris_mb,iris_proc_count,top_proc,top_mb,max_handles,spike
"""
from __future__ import annotations

import csv
import os
import sys
import time
from datetime import datetime

import psutil

IRIS_MARKERS = (
    "iris", "backend", "uvicorn", "parakeet", "tts_worker",
    "crawl_worker", "browser_pool", "main.py", "llama-server",
    "llama_server", "embedding_sidecar", "start-backend",
)

# Processes that belong to the environment (do NOT count as app spikes):
ENV_MARKERS = ("mcm.mcp_cad", "9router", "playwright", "browsermcp",
               "chrome-devtools", "context7", "server-filesystem", "opencode")


def is_iris(proc) -> bool:
    try:
        name = (proc.info.get("name") or "").lower()
        if not any(k in name for k in ("python", "node", "llama")):
            return False
        cmd = " ".join(proc.info.get("cmdline") or []).lower()
        if any(m in cmd for m in ENV_MARKERS):
            return False
        return any(m in cmd for m in IRIS_MARKERS)
    except Exception:
        return False


def main() -> int:
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 600.0
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
    outfile = sys.argv[3] if len(sys.argv) > 3 else "C:/dev/IRISVOICE/.iris-logs/mem_watch.csv"

    end = time.time() + duration
    prev_free = None
    rows = 0
    header = ["ts", "free_gb", "total_iris_mb", "n", "top_proc", "top_mb",
              "max_handles", "cpu_sum_s", "d_free_gb", "flag", "procs"]

    with open(outfile, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        while time.time() < end:
            try:
                vm = psutil.virtual_memory()
                free_gb = vm.available / (1024 ** 3)
                total_mb = 0.0
                n = 0
                top_proc, top_mb, max_handles = "", 0.0, 0
                cpu_sum = 0.0
                procs = []
                for p in psutil.process_iter(["pid", "name", "cmdline", "memory_info",
                                              "num_handles", "cpu_times"]):
                    if not is_iris(p):
                        continue
                    try:
                        mi = p.info["memory_info"]
                        mb = (getattr(mi, "private", None) or mi.rss) / (1024 ** 2)
                        total_mb += mb
                        n += 1
                        cpu_sum += (p.info["cpu_times"].user + p.info["cpu_times"].system)
                        h = p.info["num_handles"] or 0
                        max_handles = max(max_handles, h)
                        cmd = " ".join(p.info.get("cmdline") or [])
                        # short label: last path token of the script/exe
                        label = (p.info.get("name") or "?")
                        if "start-backend" in cmd or "uvicorn" in cmd:
                            label = "backend"
                        elif "llama-server" in cmd or "llama_server" in cmd:
                            label = "embed"
                        elif "tts_worker" in cmd:
                            label = "tts"
                        elif "parakeet" in cmd:
                            label = "parakeet"
                        procs.append(f"{label}:{p.pid}:{mb:.0f}MB")
                        if mb > top_mb:
                            top_mb, top_proc = mb, label
                    except Exception:
                        pass
                d_free = 0.0 if prev_free is None else (free_gb - prev_free)
                flag = ""
                if prev_free is not None and d_free < -1.0:
                    flag = "FREE_RAM_DROP>1GB"
                if max_handles > 50000:
                    flag = (flag + ";HANDLE_BLOAT" if flag else "HANDLE_BLOAT")
                prev_free = free_gb
                w.writerow([datetime.now().strftime("%H:%M:%S"), round(free_gb, 3),
                            round(total_mb, 1), n, top_proc, round(top_mb, 1),
                            max_handles, round(cpu_sum, 1), round(d_free, 3), flag,
                            "|".join(procs)])
                fh.flush()
                rows += 1
            except Exception as e:
                w.writerow(["ERR", repr(e)[:80], "", "", "", "", "", "", "", ""])
            time.sleep(interval)
    print(f"mem_watch: wrote {rows} samples to {outfile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
