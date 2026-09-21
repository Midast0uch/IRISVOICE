"""Test whether a LARGE synthesis spikes the TTS worker (doc's known risk:
~0.15-0.19 MB/char in native arenas; +1082 MB for 7500 chars)."""
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
    nchars = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
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
    time.sleep(2)
    p, r = mem(pid)
    print(f"after-ready ({nchars} char test)  private={p:>7} MB  rss={r:>7} MB", flush=True)

    # A long but sentence-structured text of ~nchars.
    base = "This is a sentence used to exercise the text to speech worker. "
    text = (base * (nchars // len(base) + 1))[:nchars]
    assert proc.stdin is not None
    proc.stdin.write(json.dumps({"action": "synthesize", "text": text, "id": 1}) + "\n")
    proc.stdin.flush()
    if wait_for(lambda ln: '"type": "done"' in ln, 240):
        print("synth done", flush=True)
    else:
        print("synth TIMEOUT", flush=True)
    p, r = mem(pid)
    print(f"post-synth              private={p:>7} MB  rss={r:>7} MB", flush=True)
    time.sleep(10)
    p, r = mem(pid)
    print(f"+10s post-synth         private={p:>7} MB  rss={r:>7} MB", flush=True)

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
