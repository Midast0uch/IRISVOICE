"""Summarise logs/stackdump.log — where did the time go?

The backend writes an in-process thread dump every N seconds when started with
IRIS_STACK_DUMP_S=N (start-backend.py). This prints, per dump inside a time
window, every thread that is inside IRIS code, innermost frames first — so a
stall shows up as the same frames repeating across consecutive dumps.

    python scripts/stackdump_summary.py 21:06:28 21:07:06
    python scripts/stackdump_summary.py 21:06:28 21:07:06 --grep calculate_eml
    python scripts/stackdump_summary.py 21:06:28 21:07:06 --all   # keep idle waits

Why this exists (execution audit, 2026-09-29): every answer-path stall found
that week — a 16-84 s EML count on an unindexed table, a 40 s recall sort, a
~90-thread ledger write storm, a TTS model load inside a turn — was invisible
in the log and obvious in two or three consecutive dumps. NEVER sample the
backend from outside instead (py-spy / asyncio ps killed it and Claude Code).
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path

# Threads that are always parked and never the answer to "where did it go".
_IDLE = (
    "_drain_stderr", "_read_stdout", "_reaper_loop", "_poll_device_changes",
    "_fragment_worker_loop", "conversation_context_store.py", "_read_line",
    "asyncio\\windows_events.py", "_watch_loop", "speech_lanes.py:1298",
    "violawake", "status_snapshot", "dev_worktree",
    "get <- backend\\utils\\durability_queue.py",   # an idle lane worker
)


def _short(path: str) -> str:
    return path.split("IRISVOICE\\")[-1].split("Lib\\")[-1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("start", help="HH:MM:SS (local time of the dump day)")
    ap.add_argument("end", help="HH:MM:SS")
    ap.add_argument("--file", default=str(Path(__file__).resolve().parents[1] / "logs" / "stackdump.log"))
    ap.add_argument("--grep", help="only threads whose stack contains this text")
    ap.add_argument("--all", action="store_true", help="also show parked/idle threads")
    ap.add_argument("--depth", type=int, default=7, help="frames per thread (innermost first)")
    args = ap.parse_args()

    text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    first, rest = text.split("\n", 1)
    start = float(first.split()[1])                       # "start_epoch <epoch>"
    period = None
    m = re.search(r"^Timeout \(0:00:(\d+(?:\.\d+)?)\)!", rest, flags=re.M)
    period = float(m.group(1)) if m else 4.0
    day = dt.datetime.fromtimestamp(start).date()
    t0 = dt.datetime.combine(day, dt.time.fromisoformat(args.start)).timestamp()
    t1 = dt.datetime.combine(day, dt.time.fromisoformat(args.end)).timestamp()
    dumps = re.split(r"^Timeout \(0:00:[\d.]+\)!\s*$", rest, flags=re.M)

    for k, d in enumerate(dumps):
        ts = start + period * k
        if not (t0 <= ts <= t1):
            continue
        lines = []
        for block in re.split(r"^(?=(?:Current thread|Thread) 0x)", d, flags=re.M):
            frames = re.findall(r'File "([^"]+)", line (\d+) in (\S+)', block)
            if not any("IRISVOICE" in f for f, _, _ in frames):
                continue
            chain = " <- ".join(f"{_short(f)}:{ln} {fn}" for f, ln, fn in frames[: args.depth])
            if not args.all and any(s in chain for s in _IDLE):
                continue
            if args.grep and args.grep not in block:
                continue
            lines.append("   " + chain)
        print(f"[{dt.datetime.fromtimestamp(ts):%H:%M:%S}] dump {k}")
        for line in lines:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
