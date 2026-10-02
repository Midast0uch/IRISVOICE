"""Wait for the backend API, then load the local tool model the way the Models card does.

Run after starting the backend, before evals/run_evals.py:
    python evals/load_tool_model.py
Override the model with IRIS_TOOL_MODEL_PATH.
"""
import asyncio
import json
import os
import socket
import time
import urllib.request

import websockets

PATH = os.environ.get(
    "IRIS_TOOL_MODEL_PATH",
    r"C:\Users\midas\.lmstudio\models\LiquidAI\LFM2.5-2.6B-GGUF\LFM2.5-2.6B-QAD-Q4_0.gguf",
)
PORT = int(os.environ.get("IRIS_LOCAL_PORT", "8082"))


def api_ready() -> bool:
    try:
        urllib.request.urlopen("http://127.0.0.1:8090/api/mode", timeout=5).read()
        return True
    except Exception:
        return False


def port_open() -> bool:
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=1).close()
        return True
    except OSError:
        return False


async def main() -> None:
    t0 = time.time()
    while not api_ready():
        if time.time() - t0 > 300:
            print("API never became ready")
            return
        await asyncio.sleep(5)
    print("API ready after", round(time.time() - t0), "s")
    if port_open():
        print(f"tool model already serving on {PORT}")
        return
    async with websockets.connect("ws://127.0.0.1:8090/ws/eval-loader?session_id=eval-loader",
                                  max_size=2**24, ping_interval=None) as ws:
        await ws.send(json.dumps({"type": "load_local_model",
                                  "payload": {"model_path": PATH, "with_projector": False}}))
        # Hold the socket until the backend reports the model "loaded": the
        # handler registers the model (kernel wire, role binding, config) AFTER
        # the port opens, and closing the socket at port-open cancelled it
        # (2026-10-02: llama-server up on 8082, config still "unloaded").
        t1 = time.time()
        hold_until = None
        while time.time() - t1 < 400:
            if hold_until and time.time() > hold_until:
                return
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            except asyncio.TimeoutError:
                continue
            if m.get("type") == "ping":
                await ws.send(json.dumps({"type": "pong", "payload": {}}))
            elif m.get("type") == "local_model_status" and not hold_until:
                status = (m.get("payload") or {}).get("status")
                print("model", status, "after", round(time.time() - t1), "s")
                if status != "loaded":
                    return
                hold_until = time.time() + 30  # post-status registration
        if not hold_until:
            print("model never reported loaded")


if __name__ == "__main__":
    asyncio.run(main())
