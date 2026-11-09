"""Periodic all-thread stack dump that is safe to leave running.

`faulthandler.dump_traceback_later(repeat=True)` was the in-process stall
diagnostic (IRIS_STACK_DUMP_S, IRIS_FAULTHANDLER_DUMP). Its watchdog is a
NATIVE thread that walks every other thread's frames WITHOUT the GIL, while
those threads run. MEASURED 2026-11-09 from the Windows Application log
(event 1000, 90 days): Python crashed 2 times in the stack-dump code before
the dumper was added (2026-09-29) and 80 times after - python313.dll
0x2b3b99/0x2b3b7c/0x2b45b3 and python314.dll 0x2ab7db/0x314e9b/0x314206, all
in traceback.c / _PyObject_IsFreed, the faulting thread with no Python frame.
That was the "native 0xC0000005 every ~30 min under load".

This sampler is a Python thread: it holds the GIL while it takes
`sys._current_frames()` and walks the frame objects it now references, so a
frame cannot be freed under it. The output keeps the faulthandler text format
(`Timeout (0:00:04)!`, `Thread 0x... (most recent call first):`,
`  File "...", line N in name`) that scripts/stackdump_summary.py parses.
"""
from __future__ import annotations

import sys
import threading
import time
import traceback

_STARTED = set()


def _dump(out, every_s: float, me: int) -> None:
    secs = int(every_s)
    out.write(f"Timeout ({secs // 3600}:{secs // 60 % 60:02d}:{secs % 60:02d})!\n")
    for ident, frame in sys._current_frames().items():
        if ident == me:
            continue
        out.write(f"Thread 0x{ident:08x} (most recent call first):\n")
        for fs in reversed(traceback.extract_stack(frame)):
            out.write(f'  File "{fs.filename}", line {fs.lineno} in {fs.name}\n')
        out.write("\n")
    out.flush()


def start(out, every_s: float, name: str = "stack-sampler") -> bool:
    """Dump every thread's stack to the open text file ``out`` every
    ``every_s`` seconds, on a daemon thread. One sampler per file. Returns
    False (and starts nothing) for a non-positive interval. A failed dump is
    written to the file and the sampler keeps going; it never raises."""
    try:
        every_s = float(every_s)
    except (TypeError, ValueError):
        return False
    if every_s <= 0 or id(out) in _STARTED:
        return False
    _STARTED.add(id(out))

    def _run() -> None:
        me = threading.get_ident()
        while True:
            time.sleep(every_s)
            try:
                _dump(out, every_s, me)
            except Exception as exc:  # noqa: BLE001 - a diagnostic never kills the process
                try:
                    out.write(f"[stack-sampler] dump failed: {exc!r}\n")
                    out.flush()
                except Exception:  # noqa: BLE001 - the file is gone; stop quietly
                    return

    threading.Thread(target=_run, name=name, daemon=True).start()
    return True
