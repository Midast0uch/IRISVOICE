import asyncio, json, websockets

URI = "ws://127.0.0.1:8090/ws/iris"

async def run():
    out = []
    try:
        async with websockets.connect(URI, open_timeout=6, close_timeout=2) as ws:
            out.append("CONNECTED")

            # NORMAL path: plain text_message, web OFF
            await ws.send(json.dumps({"type": "set_web_mode", "payload": {"enabled": False}, "seq": 1}))
            await ws.send(json.dumps({"type": "text_message", "payload": {"text": "What is 2 plus 2?"}, "seq": 2}))
            for _ in range(60):
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 4))
                except asyncio.TimeoutError:
                    break
                t = m.get("type")
                if t == "text_response":
                    p = m.get("payload", {})
                    out.append(f"NORMAL text_response sender={p.get('sender')} text={(p.get('text') or '')[:90]!r}")
                    break
                if t == "crawler_started":
                    out.append("NORMAL BUG: crawler started on plain text!")
                    break
                if t == "error":
                    out.append(f"NORMAL error: {str(m.get('payload'))[:120]}")
                    break
            else:
                out.append("NORMAL: no text_response within timeout")

            # WEB path (typed): send crawler_query directly
            await ws.send(json.dumps({"type": "crawler_query", "payload": {"query": "latest AI hardware companies 2026"}, "seq": 3}))
            seen = []
            got = []
            for _ in range(120):
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 4))
                except asyncio.TimeoutError:
                    break
                t = m.get("type")
                seen.append(t)
                if t == "crawler_started":
                    p = m.get("payload", {})
                    got.append(f"WEB crawler_started query={p.get('query')!r} urls={p.get('url_count')}")
                elif t == "crawler_page_fetched":
                    p = m.get("payload", {})
                    got.append(f"WEB page_fetched {p.get('page_number')}/{p.get('total')} {p.get('url')}")
                elif t == "open_tab":
                    p = m.get("payload", {})
                    data = p.get("data") or {}
                    sections = data.get("sections", [])
                    got.append(f"WEB open_tab type={p.get('tab_type')} title={p.get('title')!r} sections={len(sections)} summary={(data.get('summary') or '')[:80]!r}")
                elif t == "crawler_error":
                    got.append(f"WEB crawler_error: {str(m.get('payload'))[:120]}")
                elif t == "text_response":
                    p = m.get("payload", {})
                    if p.get("sender") == "assistant":
                        got.append(f"WEB text_response: {(p.get('text') or '')[:90]!r}")
                        break
            out.append("WEB seen=" + ",".join(sorted(set(seen))))
            out.extend(got)
    except Exception as e:
        out.append("EXC: " + repr(e))
    with open("C:/dev/IRISVOICE/logs/wstest.log", "w") as f:
        f.write("\n".join(out) + "\n")

asyncio.run(asyncio.wait_for(run(), timeout=200))
