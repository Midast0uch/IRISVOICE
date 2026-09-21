"""Bounded WS probe: does a web/research turn emit task:done?"""
import asyncio, json, sys, time
import websockets

WS = "ws://127.0.0.1:8090/ws/gcprobeA?session_id=session_gcprobeA"
PROMPT = "List the first three markdown file names in the docs folder."
OUT = sys.argv[1] if len(sys.argv) > 1 else r"C:\dev\IRISVOICE\temp\gc_probe_result.json"

async def main():
    frames = []
    async with websockets.connect(WS, open_timeout=10, close_timeout=3, ping_interval=None) as ws:
        await ws.send(json.dumps({"type": "set_web_mode", "payload": {"enabled": True}}))
        await asyncio.sleep(1.0)
        await ws.send(json.dumps({"type": "text_message", "payload": {"text": PROMPT}}))
        t0 = time.time()
        deadline = time.monotonic() + 90.0
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
            except asyncio.TimeoutError:
                continue
            try:
                m = json.loads(raw)
            except Exception:
                continue
            t = m.get("type") or "?"
            p = m.get("payload", {})
            frames.append({"t": round(time.time() - t0, 1), "type": t, "outcome": (p.get("outcome") if isinstance(p, dict) else None)})
            if t == "chat_message":
                break
    json.dump(frames, open(OUT, "w", encoding="utf-8"), indent=2)
    print("frames:", len(frames), "| terminal:", sum(1 for f in frames if f["type"] in ("task:done", "task:fail")))

asyncio.run(main())
