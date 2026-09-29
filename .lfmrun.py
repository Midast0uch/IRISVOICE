"""Throwaway: load the LFM 2.6B through the app and bind both roles to it.

The owner's local model of choice is LFM 2.6B. NOT granite3, NOT LFM 8B.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket

MODEL = (
    r"C:\Users\midas\.lmstudio\models\LiquidAI\LFM2.5-2.6B-GGUF"
    r"\LFM2.5-2.6B-QAD-Q4_0.gguf"
)
NAME = "LFM2.5-2.6B-QAD-Q4_0"
CLIENT = "lfmrun"
URL = f"ws://127.0.0.1:8090/ws/{CLIENT}"

# The load handler defaults `profile` to "balanced" (= 32768 ctx for this
# model) when the payload omits it. That default WEDGES the server on this
# 8 GB RTX 3070: measured 2026-09-27, twice - the load reports status True,
# then /health, /props and /v1/models all time out and the process CPU clock
# freezes (10.40625 -> 10.40625 across 6 s), so it is idle-but-silent rather
# than decoding. Always send an explicit profile.
PROFILE = os.environ.get("IRIS_LOAD_PROFILE", "performance")


def _server_serving(host: str = "127.0.0.1", port: int = 8082) -> bool:
    """True when the app's local model server accepts connections.

    SESSION 364 - WHY THE LOAD CONFIRMATION MUST NOT DEPEND ON AN EVENT: the app
    does NOT reliably emit `local_model_status` with loaded=True. The only one
    this session ever saw was the BOOT RESET ("Reset stale local_model_status=
    'loaded' -> 'unloaded'"), so watching for that event made this script burn
    BOTH 240 s attempts and exit 2 (8m 7s) while the server was ALREADY serving.
    The cost is not just wall clock: the `set_model_selection` bind below never
    ran, and that bind is what registers the local model for IN-PROCESS
    inference - without it every tool decision fails with
    "No local model loaded for in-process inference".

    A TCP connect answers whether the port is accepting connections - and cannot
    contend for the model lock (this llama-server build's /health and /props
    handlers BLOCK while a slot is busy).

    SESSION 365 - BUT A TCP CONNECT IS NOT A READINESS CHECK. Measured live:
    this returned True and the script printed "server is SERVING (port probe) -
    load confirmed" while `curl /v1/models` was still 503 "Loading model", then
    reported "bind not confirmed". llama-server BINDS THE PORT BEFORE THE
    WEIGHTS ARE IN, so an open socket only proves the process started - and
    declaring the load confirmed early costs exactly what this function exists
    to prevent: the `set_model_selection` bind below is skipped, and without it
    every tool decision fails with "No local model loaded for in-process
    inference".

    `/v1/models` is the readiness signal that does NOT block: measured returning
    503 promptly while loading and 200 once ready, unlike /health and /props.
    Any non-503 answer counts as ready, so a future 2xx/4xx shape cannot be
    mistaken for "still loading".
    """
    try:
        with socket.create_connection((host, port), timeout=3):
            pass
    except Exception:
        return False
    try:
        import urllib.error
        import urllib.request

        try:
            with urllib.request.urlopen(
                f"http://{host}:{port}/v1/models", timeout=3
            ) as _r:
                return _r.status != 503
        except urllib.error.HTTPError as _he:
            return _he.code != 503
    except Exception:
        return False


async def main() -> int:
    import websockets

    print("exists:", os.path.exists(MODEL), flush=True)
    async with websockets.connect(URL, max_size=16 * 1024 * 1024) as ws:
        # ONE RETRY (measured 2026-09-27). The first load after a backend
        # restart can lose a race with the backend's OWN start-up work: the
        # TTS worker spawn, the Whisper warm-up and the embedding sidecar all
        # come up within the same minute, and the GPU/CPU are busy. Observed:
        # the first load reported no completion at all, while an identical
        # retry 8 minutes later loaded in 23 s. A single retry makes that a
        # non-event.
        #
        # WHY THE ERROR MUST BE READ, not waited out: the app DOES report a
        # failed load - as local_model_loading with status="error" and
        # "Server did not start within timeout" (iris_gateway.py:9596-9604).
        # This script used to watch ONLY local_model_status, so it ignored that
        # error and sat in silence until its own 240 s deadline expired - which
        # is what made the load path LOOK flaky and silent. Read both event
        # kinds and stop at once when the app says it failed.
        loaded = False
        for attempt in (1, 2):
            await ws.send(json.dumps({
                "type": "load_local_model",
                "payload": {"model_path": MODEL, "with_projector": False,
                            "profile": PROFILE},
                "client_id": CLIENT, "seq": attempt,
            }))
            print(f"load attempt {attempt} sent (profile={PROFILE})", flush=True)

            loop = asyncio.get_event_loop()
            end = loop.time() + 240
            loaded = False
            while loop.time() < end and not loaded:
                # Port probe FIRST, every iteration: the load is confirmed by the
                # server actually serving, not by an event that may never come.
                if await asyncio.to_thread(_server_serving):
                    print("server is SERVING (port probe) - load confirmed", flush=True)
                    loaded = True
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=15)
                except asyncio.TimeoutError:
                    print("  ...still waiting", flush=True)
                    continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                t = msg.get("type", "")
                if t == "local_model_status":
                    loaded = bool(msg.get("payload", {}).get("loaded"))
                    print("status:", loaded, flush=True)
                elif t == "local_model_loading":
                    pl = msg.get("payload", {}) or {}
                    st = pl.get("status", "")
                    if st == "error":
                        print("LOAD FAILED:", pl.get("error", ""), flush=True)
                        break
                    if st in ("starting", "switching", "loading", "ready"):
                        print(f"  {st}: {pl.get('msg', '') or pl.get('phase', '')}",
                              flush=True)
                elif "error" in t:
                    print("LOAD ERROR:", json.dumps(msg)[:200], flush=True)
                    break
            if loaded:
                break
            if attempt == 1:
                print("retrying the load once...", flush=True)
                await asyncio.sleep(3)

        if not loaded:
            print("load not confirmed after 2 attempts", flush=True)
            return 2
        await ws.send(json.dumps({
            "type": "set_model_selection",
            "payload": {
                "reasoning_model": NAME,
                "tool_execution_model": NAME,
                "model_provider": f"local:{NAME}",
            },
            "client_id": CLIENT, "seq": 2,
        }))
        end = loop.time() + 30
        while loop.time() < end:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=6)
            except asyncio.TimeoutError:
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get("type") == "model_selection_updated":
                print("BOUND ok", flush=True)
                return 0
        print("bind not confirmed", flush=True)
        return 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
