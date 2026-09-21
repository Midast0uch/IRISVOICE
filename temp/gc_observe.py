"""Bounded probe: capture the terminal frames of one live task.
Args: prompt out_path max_seconds. Exits on chat_message or timeout."""
import asyncio, json, sys, time
import websockets

async def main(prompt, out_path, max_seconds):
    sid = "gcweb_dev"
    uri = f"ws://127.0.0.1:8090/ws/gcprobe_dev?session_id={sid}"
    frames = []
    records = []
    t0 = time.time()
    async with websockets.connect(uri, open_timeout=10, close_timeout=3, ping_interval=None) as ws:
        await ws.send(json.dumps({"type": "set_web_mode", "payload": {"enabled": True}}))
        await asyncio.sleep(1.0)
        await ws.send(json.dumps({"type": "text_message", "payload": {"text": prompt}}))
        while time.time() - t0 < max_seconds:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
            except asyncio.TimeoutError:
                continue
            try:
                m = json.loads(raw)
            except Exception:
                continue
            t = m.get("type", "?")
            if t in ("system_status", "chat_heartbeat", "audio_envelope", "ping", "pong"):
                continue
            frames.append(t)
            el = round(time.time() - t0, 1)
            if t in ("task:start", "task:done", "task:fail", "chat_message", "task:progress"):
                rec = {"t": el, "type": t, "payload_keys": list((m.get("payload") or {}).keys()), "card_id": (m.get("payload") or {}).get("card_id"), "conversation_id": (m.get("payload") or {}).get("conversation_id")}
                records.append(rec)
                print(f"[{el:>5}s] {t} card_id={rec['card_id']} conv={rec['conversation_id']}",
                      flush=True)
            if t == "chat_message":
                break
            if time.time() - t0 >= max_seconds:
                break
    from collections import Counter
    summary = {"frame_counts": dict(Counter(frames)), "records": records}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    c = Counter(frames)
    print("done:", dict((k, c[k]) for k in ("task:start","task:done","task:fail","chat_message") if k in c))

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 120))
