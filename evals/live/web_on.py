"""Turn the web toggle ON over WS (python web_on.py [off])."""
import asyncio, json, sys, websockets

ON = not (len(sys.argv) > 1 and sys.argv[1] == "off")


async def main():
    async with websockets.connect("ws://127.0.0.1:8090/ws/web-toggle?session_id=session_iris",
                                  max_size=2**24, ping_interval=None) as ws:
        await ws.send(json.dumps({"type": "set_web_mode", "payload": {"enabled": ON}}))
        await asyncio.sleep(2)
    print("web_mode", ON)


asyncio.run(main())
