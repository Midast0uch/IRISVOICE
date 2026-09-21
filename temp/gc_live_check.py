"""bounded capture of WS frames, run to write a clean evidence summary."""
import asyncio, json, sys, time
import websockets

OUT = r"C:\dev\IRISVOICE\temp\gc_all_frames.json"
SID = "gc-live-verify"
LAST_PTS = ["chat_message", "task:done", "task:fail"]

async def main(prompt):
    uri = f"ws://127.0.0.1:8090/ws/{SID}?session_id=session_{SID}"
    frames = []
    counts = {}
    events = []
    deadline = time.time() + 180
    try:
        async with websockets.connect(uri, open_timeout=10, close_timeout=3) as ws:
            await ws.send(json.dumps({"type": "set_web_mode", "payload": {"enabled": True}}))
            await asyncio.sleep(1.5)
            await ws.send(json.dumps({"type": "text_message", "payload": {"text": prompt}}))
            # drain frames, with per-frame timeout and overall deadline
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=15)
                except asyncio.TimeoutError:
                    continue
                try:
                    m = json.loads(raw)
                except Exception:
                    continue
                t = m.get("type") or m.get("event")
                if t in ("system_status", "chat_heartbeat", "audio_envelope"):
                    continue
                frames.append(m)
                counts[t] = counts.get(t, 0) + 1
                # record interesting frames with relevant fields
                if t in ("task:start", "task:progress", "task:done", "task:fail", "chat_message", "tool:call", "tool:result"):
                    p = m.get("payload") or {}
                    entry = {
                        "t": round(time.time() - (deadline - 180 + (deadline - time.time()))),
                        "type": t,
                        "card_id": p.get("card_id"),
                        "outcome": p.get("outcome"),
                        "conversation_id": p.get("conversation_id"),
                        "action": p.get("action"),
                    }
                    events.append(entry)
                    print(f"[{round(time.time() - (deadline - 180),2)}s] {t} card={entry['card_id']} outcome={entry['outcome']}", flush=True)
                # stop conditions
                if t == "chat_message":
                    break
    except Exception as e:
        print("ERR", e, flush=True)

    summary = {"frame_counts": counts, "events": events}
    with open(OUT, "w") as f:
        json.dump(summary, f, indent=2)
    print("\n[summary]")
    print(json.dumps(counts, indent=2))

asyncio.run(main(sys.argv[1]))
