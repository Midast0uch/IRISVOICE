#!/usr/bin/env python3
"""Mock model-runner worker for supervisor tests (Phase 4.1).

Reads JSON control lines from stdin and writes JSON responses to stdout.
Implements the minimal supervisor protocol:

  {"type": "ping"}     -> {"type": "pong"}
  {"type": "health"}   -> {"type": "health", "rss_bytes": <int>}
  {"type": "die"}      -> sys.exit(1)   (simulates a crash to test restart)

No real model is loaded — this exists so the supervisor's restart + protocol
logic can be verified without CUDA.
"""

import json
import os
import sys


def main() -> None:
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        msg_type = msg.get("type")
        if msg_type == "ping":
            print(json.dumps({"type": "pong"}), flush=True)
        elif msg_type == "health":
            print(json.dumps({"type": "health", "rss_bytes": os.getpid()}), flush=True)
        elif msg_type == "die":
            sys.exit(1)
        else:
            print(json.dumps({"type": "unknown", "echo": msg_type}), flush=True)


if __name__ == "__main__":
    main()
