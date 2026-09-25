"""Drive one text turn on its OWN WebSocket client id and print the reply.

The client id is the URL path segment (main.py: websocket, client_id: str), so a
driver that connects as "iris" shares the browser's client and the reply is
delivered to the browser instead. This connects as its own client.

    $env:IRIS_DRIVE_TEXT = "..."; python scripts/ws_drive_turn3.py 240
"""
import asyncio
import json
import os
import sys

CLIENT_ID = os.environ.get("IRIS_DRIVE_CLIENT") or "ws-driver"
URL = "ws://127.0.0.1:8090/ws/%s" % CLIENT_ID
REPLY_TYPES = ("text_response", "chat_response", "assistant_message", "response",
               "reply", "final_response", "chat_chunk", "chat_message")


async def main() -> int:
    text = os.environ.get("IRIS_DRIVE_TEXT") or "hello"
    try:
        budget = float(sys.argv[1]) if len(sys.argv) > 1 else 180.0
    except ValueError:
        budget = 180.0
    import websockets

    async with websockets.connect(URL, max_size=16 * 1024 * 1024) as ws:
        await ws.send(json.dumps({
            "type": "text_message",
            "payload": {"text": text, "client_id": CLIENT_ID},
            "client_id": CLIENT_ID,
            "seq": 1,
        }))
        loop = asyncio.get_event_loop()
        end = loop.time() + budget
        kinds = {}
        docs = []
        while loop.time() < end:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            t = msg.get("type", "?")
            kinds[t] = kinds.get(t, 0) + 1
            if t == "document:render":
                docs.append(msg.get("payload", {}))
            if t in REPLY_TYPES and t != "chat_chunk":
                print("== %s ==" % t)
                print(json.dumps(msg.get("payload", {}), ensure_ascii=False)[:2000])
                print("DOC RENDERS: %d" % len(docs))
                for d in docs[-2:]:
                    print("  doc title=%r format=%r chars=%d" % (
                        d.get("title"), d.get("format"), len(d.get("content") or "")))
                print("FRAME COUNTS:", json.dumps(kinds))
                return 0
            if t == "chat_chunk":
                # Streaming token frames: print the final assembled text at the end.
                docs.append({"chunk": msg.get("payload", {}).get("chunk", "")})
        joined = "".join(d.get("chunk", "") for d in docs if isinstance(d, dict) and "chunk" in d)
        if joined:
            print("== assembled chat_chunk text (%d chars) ==" % len(joined))
            print(joined[:2000])
        print("FRAME COUNTS:", json.dumps(kinds))
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
