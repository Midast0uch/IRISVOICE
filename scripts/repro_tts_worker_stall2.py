"""Repro 2: bisect WHERE the Pocket-TTS worker stalls on long text.

Same as repro 1 except stderr goes to a FILE instead of an unread pipe, so a
full stderr buffer cannot block the worker. If long texts complete here but
hang in repro 1, the unread stderr pipe is the cause.

Each synthesis is bounded by a watchdog thread that reports how many chunks
arrived before the stall, so we learn whether the worker dies mid-sentence.
"""
import base64
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
PY = PROJECT / ".venv" / "Scripts" / "python.exe"
ERR_LOG = PROJECT / "scripts" / "_repro_worker_stderr.log"

BASE = (
    "Algorithms are step-by-step instructions for solving all kinds of "
    "problems, not just the ones that live inside a computer. You already "
    "use them every day without calling them algorithms. A recipe is an "
    "algorithm, and so is the order in which you get ready in the morning. "
    "An algorithm has three important properties that make it useful. "
    "First, it has clear inputs, like the ingredients in a recipe. Second, "
    "it has a finite sequence of unambiguous steps, so there is never any "
    "guessing about what comes next. Third, it produces an output, like a "
    "finished cake that you can actually eat. "
)
LENGTHS = [121, 300, 500, 700, 853, 964]
PER_TEXT_TIMEOUT = 45


def build(n: int) -> str:
    out = BASE
    while len(out) < n:
        out += BASE
    return out[:n].rsplit(" ", 1)[0] + "."


def main() -> int:
    env = {**os.environ, "PYTHONPATH": str(PROJECT)}
    err_fh = open(ERR_LOG, "w", buffering=1)
    t_spawn = time.monotonic()
    proc = subprocess.Popen(
        [str(PY), "-u", "-m", "backend.audio.tts_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=err_fh,          # file, never fills a pipe
        text=True,
        cwd=str(PROJECT),
        env=env,
    )
    while True:
        line = proc.stdout.readline().strip()
        if not line:
            print("[repro2] EOF waiting for ready", flush=True)
            return 1
        if json.loads(line).get("status") == "ready":
            break
    print(f"[repro2] READY at +{time.monotonic()-t_spawn:.1f}s "
          f"(stderr -> {ERR_LOG.name})\n", flush=True)

    stalled = []
    for n in LENGTHS:
        text = build(n)
        t0 = time.monotonic()
        proc.stdin.write(json.dumps(
            {"action": "synthesize", "text": text, "id": 1}) + "\n")
        proc.stdin.flush()
        chunks = 0
        samples = 0
        first = None
        hit = threading.Event()

        def watchdog():
            hit.wait(PER_TEXT_TIMEOUT)

        threading.Thread(target=watchdog, daemon=True).start()
        # readline blocks; use a plain loop and rely on the OS — the watchdog
        # only reports if we come back. Instead, poll via a reader thread.
        box = {}

        def reader():
            nonlocal chunks, samples, first
            while True:
                line = proc.stdout.readline()
                if not line:
                    box["eof"] = True
                    return
                msg = json.loads(line)
                mt = msg.get("type")
                if mt == "chunk":
                    if first is None:
                        first = time.monotonic() - t0
                    chunks += 1
                    samples += len(base64.b64decode(msg.get("data", ""))) // 4
                elif mt == "done":
                    box["done"] = time.monotonic() - t0
                    return
                elif mt == "error":
                    box["error"] = msg.get("error")
                    return

        rt = threading.Thread(target=reader, daemon=True)
        rt.start()
        rt.join(PER_TEXT_TIMEOUT)
        if rt.is_alive():
            stalled.append(n)
            print(f"[{n:4d}] STALL — no completion after {PER_TEXT_TIMEOUT}s; "
                  f"chunks={chunks} samples={samples} first=+{first}s "
                  f"({samples/24000:.1f}s audio)", flush=True)
            print(f"[{n:4d}] -> worker is wedged; abandoning this run.",
                  flush=True)
            break
        print(f"[{n:4d}] chunks={chunks} samples={samples} "
              f"first=+{first}s total=+{box.get('done', -1):.1f}s "
              f"({samples/24000:.1f}s audio)", flush=True)

    proc.stdin.write(json.dumps({"action": "shutdown"}) + "\n")
    proc.stdin.flush()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    err_fh.close()
    print(f"\n[repro2] stalled lengths: {stalled or 'none'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
