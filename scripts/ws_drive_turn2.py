"""Drive one text turn through the real WS and print the reply frames.

The prompt comes from the IRIS_DRIVE_TEXT env var (shell quoting cannot mangle
it); the optional argv[1] is the time budget in seconds.

    $env:IRIS_DRIVE_TEXT = "create three files ..."; python scripts/ws_drive_turn2.py 240
"""
import asyncio
import json
import os
import sys

URL = "ws://127.0.0.1:8090/ws/iris"
REPLY_TYPES = ("text_response", "chat_response", "assistant_message", "response",
               "reply", "final_response", "chat_chunk")


async def main() -> int:
    text = os.environ.get("IRIS_DRIVE_TEXT") or "hello"
    try:
        budget = float(sys.argv[1]) if len(sys.argv) > 1 else 150.0
    except ValueError:
        budget = 150.0
    import websockets

    async with websockets.connect(URL, max_size=16 * 1024 * 1024) as ws:
        await ws.send(json.dumps({
            "type": "text_message", "payload": {"text": text}, "seq": 1,
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
            if t in REPLY_TYPES:
                print("== %s ==" % t)
                print(json.dumps(msg.get("payload", {}), ensure_ascii=False)[:1800])
                print("DOC RENDERS: %d" % len(docs))
                for d in docs[-2:]:
                    print("  doc title=%r format=%r chars=%d" % (
                        d.get("title"), d.get("format"), len(d.get("content") or "")))
                print("FRAME COUNTS:", json.dumps(kinds))
                return 0
        print("no reply within the budget; frame counts:", json.dumps(kinds))
        print("DOC RENDERS: %d" % len(docs))
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
