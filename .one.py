"""Throwaway: send ONE long, multi-step, gather-heavy prompt.

WHY: the monitor consumers (sufficient / done / on_track) cannot be reached by
the light chain prompts, because a short simple command routes to QUICK mode
(der_loop.py:396-445) and those consumers need:
    done       -> queue.mode in (AGENTIC, FULL)   agent_kernel.py:18091
    on_track   -> mode == FULL and >=3 completed  agent_kernel.py:18169
    sufficient -> a FAILING GATHER tool           agent_kernel.py:12632/13805
This message is deliberately long and research-shaped so the classifier routes
it to FULL, and it reads several files so read_file (a gather tool) runs and the
queue reaches >=3 completed items. ONE turn is the experiment.
"""
from __future__ import annotations

import asyncio
import json
import socket
import time

CLIENT = "m1"
URL = f"ws://127.0.0.1:8090/ws/{CLIENT}?session_id={CLIENT}"

PROMPT = (
    "Investigate this codebase and report back. Read "
    "backend/agent/local_model_manager.py, backend/agent/der_loop.py and "
    "backend/inference_router.py, then explain step by step how a local "
    "model's context window is decided, from the selected profile through to "
    "the llama-server launch arguments. Verify that each file was actually "
    "read, compare the three files, and note any place where one layer "
    "overrides another. This is a multi-step research task - work through it "
    "in several steps rather than answering immediately."
)


async def main() -> int:
    import websockets

    with socket.create_connection(("127.0.0.1", 8082), timeout=3):
        print("local model server is up", flush=True)

    async with websockets.connect(URL, max_size=16 * 1024 * 1024) as ws:
        await ws.send(json.dumps({
            "type": "set_web_mode", "payload": {"enabled": True},
        }))
        await ws.send(json.dumps({
            "type": "text_message",
            "payload": {"text": PROMPT},
            "client_id": CLIENT, "seq": 1,
        }))
        t0 = time.monotonic()
        print(f"sent at {time.strftime('%H:%M:%S')} - waiting...", flush=True)

        deadline = t0 + 900
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=20)
            except asyncio.TimeoutError:
                print(f"  ...{time.monotonic() - t0:.0f}s", flush=True)
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            t = msg.get("type", "")
            if t == "ping":
                await ws.send(json.dumps({"type": "pong", "payload": {}}))
            elif t == "task:progress":
                p = msg.get("payload", {}) or {}
                print(f"  {time.monotonic() - t0:.0f}s progress: "
                      f"{str(p.get('message') or p.get('phase') or '')[:70]}",
                      flush=True)
            elif t in ("task:done", "task:fail", "chat_message"):
                print(f"RECEIVED {t} after {time.monotonic() - t0:.0f}s", flush=True)
                return 0
        print("timed out", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
