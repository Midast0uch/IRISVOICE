import asyncio, json, websockets, time

URI = "ws://127.0.0.1:8090/ws/iris"

async def run():
    out = []
    try:
        async with websockets.connect(URI, open_timeout=6, close_timeout=2) as ws:
            out.append("OK: connected at " + time.strftime("%H:%M:%S"))
            t0 = time.time()
            await ws.send(json.dumps({"type": "text_message", "payload": {"text": "Reply with just the word: PONG"}, "seq": 1}))
            for _ in range(40):
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 4))
                except asyncio.TimeoutError:
                    break
                t = m.get("type")
                if t == "chat_message":
                    p = m.get("payload", m)
                    content = p.get("content") or p.get("text") or ""
                    dt = round(time.time() - t0, 1)
                    out.append(f"RESPONSE [{dt}s]: {content[:150]!r}")
                    break
                if t == "text_response":
                    p = m.get("payload", {})
                    dt = round(time.time() - t0, 1)
                    out.append(f"RESPONSE [{dt}s]: sender={p.get('sender')} text={(p.get('text') or '')[:150]!r}")
                    break
                if t == "error":
                    out.append(f"ERROR [{round(time.time()-t0,1)}s]: {str(m)}")
                    break
            else:
                out.append(f"NO RESPONSE within timeout ({round(time.time()-t0,1)}s)")
    except Exception as e:
        out.append("EXC: " + repr(e))
    with open("C:/dev/IRISVOICE/logs/agenttest.log", "w") as f:
        f.write("\n".join(out))

asyncio.run(asyncio.wait_for(run(), timeout=60))
