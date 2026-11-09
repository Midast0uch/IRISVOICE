"""The periodic stack dump is a GIL-holding sampler, never faulthandler's watchdog.

MEASURED 2026-11-09 (Windows Application log, event 1000, 90 days): Python
crashed 2 times in its stack-dump code before the periodic dumper was added
(2026-09-29) and 80 times after - all in traceback.c / _PyObject_IsFreed, on
a thread with no Python frame: faulthandler.dump_traceback_later's native
watchdog walking live frames without the GIL. Pins:
  * no backend entry point starts faulthandler.dump_traceback_later again;
  * the sampler writes the format scripts/stackdump_summary.py parses.
"""
import re
import threading
import time
from pathlib import Path

from backend.utils import stack_sampler

_ROOT = Path(__file__).resolve().parents[3]


def test_no_entry_point_uses_the_native_watchdog():
    for rel in ("start-backend.py", "backend/audio/tts_worker.py", "backend/main.py"):
        src = (_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        assert "dump_traceback_later(" not in code, rel


def test_the_sampler_writes_the_faulthandler_format(tmp_path):
    out = open(tmp_path / "stackdump.log", "w", encoding="utf-8")
    stop = threading.Event()

    def _parked():
        stop.wait(5)

    threading.Thread(target=_parked, name="parked", daemon=True).start()
    assert stack_sampler.start(out, 0.05) is True
    assert stack_sampler.start(out, 0.05) is False, "one sampler per file"
    time.sleep(0.4)
    stop.set()
    text = (tmp_path / "stackdump.log").read_text(encoding="utf-8")
    assert re.search(r"^Timeout \(0:00:\d+(?:\.\d+)?\)!", text, flags=re.M)
    assert re.search(r"^Thread 0x[0-9a-f]+ \(most recent call first\):$", text, flags=re.M)
    assert re.search(r'^  File ".+", line \d+ in _parked$', text, flags=re.M)


def test_a_bad_interval_starts_nothing(tmp_path):
    out = open(tmp_path / "x.log", "w", encoding="utf-8")
    assert stack_sampler.start(out, 0) is False
    assert stack_sampler.start(out, "nope") is False
