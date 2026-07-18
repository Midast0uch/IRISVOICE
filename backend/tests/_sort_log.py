#!/usr/bin/env python3
"""Sort the live backend log into per-event-type files for easier debugging.

Reads backend_live_test.out, buckets the PLAIN-TEXT log lines
(the useful ones: capture_frame, PLAYBACK, SPEAK, TASK_CARD, State,
RECORDING, pong, STTPROC, etc.) into logs/by_type/<type>.log.

JSON-structured lines ({"timestamp":...}) are bucketed by their
"message" keyword too, so both formats are covered.

Run:  python backend/tests/_sort_log.py
"""
import sys, os, re, json

REPO = r"C:\dev\IRISVOICE"
SRC = os.path.join(REPO, "backend_live_test.out")
OUTDIR = os.path.join(REPO, "logs", "by_type")
os.makedirs(OUTDIR, exist_ok=True)

# Keyword -> bucket name. First match wins (order matters).
BUCKETS = [
    ("capture_frame", "capture_frame"),
    ("PLAYBACK", "tts_playback"),
    ("SPEAK intent", "tts_speak_intent"),
    ("STTPROC", "sttproc_chime"),
    ("TASK_CARD", "task_card"),
    ("skipping DER", "der_skip"),
    ("plan has", "der_skip"),
    ("der_steps", "der_routing"),
    ("path=", "der_routing"),
    ("State:", "voice_state"),
    ("RECORDING", "recording"),
    ("IDLE", "voice_state"),
    ("SPEAKING", "voice_state"),
    ("LISTENING", "voice_state"),
    ("pong", "ws_heartbeat"),
    ("ping", "ws_heartbeat"),
    ("Processing message", "ws_messages"),
    ("text_message", "ws_messages"),
    ("conversation_switched", "ws_ack"),
    ("sync_state", "ws_ack"),
    ("Generated:", "tts_generate"),
    ("Whisper", "stt_whisper"),
    ("Porcupine", "wake_word"),
    ("wake", "wake_word"),
    ("Error", "errors"),
    ("Traceback", "errors"),
    ("WARNING", "warnings"),
    ("RuntimeWarning", "warnings"),
    # ToolDecisionBox (REQ-5 / T15)
    ("TOOL_DECISION_FAIL", "tool_decision_fail"),
    ("TOOL_DECISION", "tool_decision"),
    ("TOOL_DISPATCH", "tool_dispatch"),
]

buckets = {}  # name -> list of lines


def classify(line: str) -> str:
    low = line.lower()
    for kw, name in BUCKETS:
        if kw.lower() in low:
            return name
    # JSON lines: try to read "message"
    if line.strip().startswith("{"):
        try:
            obj = json.loads(line)
            msg = str(obj.get("message", ""))
            for kw, name in BUCKETS:
                if kw.lower() in msg.lower():
                    return name
        except Exception:
            pass
    return "other"


def main():
    if not os.path.exists(SRC):
        print(f"source not found: {SRC}")
        sys.exit(1)
    with open(SRC, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            name = classify(line)
            buckets.setdefault(name, []).append(line)

    summary = []
    for name, lines in sorted(buckets.items()):
        path = os.path.join(OUTDIR, f"{name}.log")
        with open(path, "w", encoding="utf-8") as out:
            out.write("\n".join(lines) + "\n")
        summary.append((name, len(lines)))

    print(f"Sorted {sum(len(v) for v in buckets.values())} lines into {len(buckets)} buckets:")
    for name, n in summary:
        print(f"  {n:6d}  {name}")
    print(f"\nOutput dir: {OUTDIR}")


if __name__ == "__main__":
    main()
