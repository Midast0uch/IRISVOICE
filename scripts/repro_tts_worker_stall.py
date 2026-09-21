"""Repro: is the Pocket-TTS worker STUCK or merely SLOW on long text?

Mirrors TTSManager._spawn_worker() exactly: stderr=subprocess.PIPE and
NEVER read (that is the production condition we suspect causes a silent
hang once the OS pipe buffer fills).

Reports, per text: time-to-first-chunk, total synthesis time, chunk count,
and how many bytes landed in the unread stderr pipe.
"""
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
PY = PROJECT / ".venv" / "Scripts" / "python.exe"
if not PY.exists():
    PY = Path(sys.executable)

TEXTS = [
    ("short-14", "Just a second."),
    ("med-129", "Sure thing. Here is a friendly, non-technical introduction to "
                "algorithms, plus a quick example you can try at home today."),
    ("long-853", ""),
    ("long-964", ""),
]
# Real payloads taken from the failing session log (same length class).
TEXTS[2] = ("long-853", (
    "but I need some details about what you want. What was accomplished Confirmed "
    "that the wake word fires and the audio pipeline is healthy. What is still open "
    "is whether the TTS worker can survive a long synthesis without going silent. "
    "Here is the thing: a long response gets split into sentences, and each sentence "
    "is synthesized separately by the Pocket-TTS streaming API. Between sentences we "
    "insert a short silence so the pacing sounds natural. After the last sentence we "
    "append a trailing silence so the final word is not clipped. All of that audio is "
    "base64 encoded and written to stdout as one JSON object per line. The parent "
    "process reads those lines and pushes them into a bounded queue. If the queue is "
    "full the producer blocks. That is the part we suspect. We need to know whether "
    "the worker itself ever stalls, or whether it is simply slow. Please tell me what "
    "you would like me to cover: topic, difficulty, length, and format."
)[:853])
TEXTS[3] = ("long-964", (
    "algorithms are step-by-step instructions for solving all kinds of problems, not "
    "just the ones that live inside a computer. You already use them every day without "
    "calling them algorithms. A recipe is an algorithm. The order in which you get "
    "ready in the morning is an algorithm. So is the way you decide which checkout "
    "line to join at the grocery store. An algorithm has three important properties. "
    "First, it has clear inputs, like the ingredients in a recipe. Second, it has a "
    "finite sequence of unambiguous steps, so there is no guessing about what comes "
    "next. Third, it produces an output, like a finished cake. Once you start seeing "
    "algorithms this way, you notice them everywhere. Sorting your music library, "
    "finding the fastest route home, deciding which emails to answer first: all "
    "algorithms. The interesting question is never whether an algorithm exists. It is "
    "whether the one you picked is fast enough and simple enough for the job you "
    "actually have. That is what computer scientists spend their time on, and it is "
    "what we can dig into together if you would like to go deeper."
)[:964])


def main() -> int:
    print(f"[repro] python={PY}", flush=True)
    env = {**os.environ, "PYTHONPATH": str(PROJECT)}
    t_spawn = time.monotonic()
    proc = subprocess.Popen(
        [str(PY), "-m", "backend.audio.tts_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,   # production condition: NEVER read
        text=True,
        cwd=str(PROJECT),
        env=env,
    )
    line = proc.stdout.readline().strip()
    print(f"[repro] first line after {time.monotonic()-t_spawn:.1f}s: {line[:120]}",
          flush=True)
    while True:
        line = proc.stdout.readline().strip()
        if not line:
            print("[repro] EOF waiting for ready", flush=True)
            break
        msg = json.loads(line)
        print(f"[repro] status={msg.get('status')} "
              f"at +{time.monotonic()-t_spawn:.1f}s", flush=True)
        if msg.get("status") in ("ready", "error"):
            break
    if msg.get("status") != "ready":
        print("[repro] worker never became ready", flush=True)
        return 1
    print(f"[repro] READY at +{time.monotonic()-t_spawn:.1f}s\n", flush=True)

    for label, text in TEXTS:
        t0 = time.monotonic()
        proc.stdin.write(json.dumps(
            {"action": "synthesize", "text": text, "id": 1}) + "\n")
        proc.stdin.flush()
        chunks = 0
        total_samples = 0
        first = None
        last = None
        while True:
            line = proc.stdout.readline()
            if not line:
                print(f"[{label}] EOF (worker died) at "
                      f"+{time.monotonic()-t0:.1f}s after {chunks} chunks",
                      flush=True)
                break
            last = time.monotonic() - t0
            msg = json.loads(line)
            if msg.get("type") == "chunk":
                if first is None:
                    first = time.monotonic() - t0
                chunks += 1
                total_samples += len(base64.b64decode(msg.get("data", ""))) // 4
            elif msg.get("type") == "done":
                break
            elif msg.get("type") == "error":
                print(f"[{label}] ERROR: {msg.get('error')}", flush=True)
                break
        print(f"[{label}] chars={len(text)} chunks={chunks} "
              f"samples={total_samples} first_chunk=+{first}s "
              f"total=+{last:.1f}s "
              f"({total_samples/24000:.1f}s audio)", flush=True)

    # How much did the unread stderr pipe accumulate?
    proc.stdin.write(json.dumps({"action": "shutdown"}) + "\n")
    proc.stdin.flush()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
    try:
        os.set_blocking(proc.stderr.fileno(), False)
        err = proc.stderr.read() or ""
    except Exception as exc:
        err = f"<unreadable: {exc}>"
    print(f"\n[repro] unread stderr bytes buffered: {len(err)}", flush=True)
    print("[repro] --- worker stderr (tail) ---", flush=True)
    print("\n".join(err.splitlines()[-25:]), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
