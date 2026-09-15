"""Measure the TTS worker subprocess memory (load -> synth -> post-synth).

Spawns the worker EXACTLY as TTSManager does (backend/agent/tts.py), then
reports private (commit) + working-set MB at each phase. Read-only: does not
modify source.
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


def mb(pid: int):
    try:
        p = psutil.Process(pid)
        mi = p.memory_info()
        private = getattr(mi, "private", None) or mi.rss
        rss = getattr(mi, "rss", 0)
        return round(private / (1024 ** 2), 1), round(rss / (1024 ** 2), 1)
    except Exception:
        return -1.0, -1.0


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
    print(f"worker pid={pid} spawned", flush=True)

    # Read stdout lines in a background thread so we can time the ready event.
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
            time.sleep(0.2)
        return None

    t0 = time.time()
    ready = wait_for(lambda ln: '"status": "ready"' in ln, 240)
    if not ready:
        print("TIMEOUT waiting for ready")
        proc.kill()
        return 1
    print(f"READY after {time.time()-t0:.1f}s", flush=True)
    print(f"  after-ready       private={mb(pid)[0]:>7} MB  rss={mb(pid)[1]:>7} MB", flush=True)
    time.sleep(5)
    print(f"  +5s idle          private={mb(pid)[0]:>7} MB  rss={mb(pid)[1]:>7} MB", flush=True)
    time.sleep(10)
    print(f"  +15s idle         private={mb(pid)[0]:>7} MB  rss={mb(pid)[1]:>7} MB", flush=True)

    text = ("The quick brown fox jumps over the lazy dog. "
            "This is a moderate length sentence used to measure the TTS worker "
            "memory behaviour during a normal synthesis request. It should "
            "produce a few seconds of audio and exercise the encode path fully.")
    before = len(lines)
    assert proc.stdin is not None
    proc.stdin.write(json.dumps({"action": "synthesize", "text": text, "id": 1}) + "\n")
    proc.stdin.flush()
    done = wait_for(lambda ln: '"type": "done"' in ln, 120)
    if done:
        print(f"SYNTH done: {done[:120]}", flush=True)
    else:
        print("SYNTH did not complete in 120s", flush=True)
    print(f"  post-synth        private={mb(pid)[0]:>7} MB  rss={mb(pid)[1]:>7} MB", flush=True)
    time.sleep(5)
    print(f"  +5s post-synth    private={mb(pid)[0]:>7} MB  rss={mb(pid)[1]:>7} MB", flush=True)
    time.sleep(15)
    print(f"  +20s post-synth   private={mb(pid)[0]:>7} MB  rss={mb(pid)[1]:>7} MB", flush=True)

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
