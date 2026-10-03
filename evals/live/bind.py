"""Bind a role over WS: python bind.py <role> <instance_id> [model_override]"""
import asyncio, json, sys, time, websockets
role, inst = sys.argv[1], sys.argv[2]
override = sys.argv[3] if len(sys.argv) > 3 else None
async def main():
    async with websockets.connect("ws://127.0.0.1:8090/ws/eval-binder?session_id=eval-binder", max_size=2**24, ping_interval=None) as ws:
        await ws.send(json.dumps({"type": "set_role_binding", "payload": {"role": role, "instance_id": inst, "model_override": override}}))
        t = time.time()
        while time.time() - t < 15:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
            except asyncio.TimeoutError:
                continue
            if m.get("type") == "ping":
                await ws.send(json.dumps({"type": "pong", "payload": {}})); continue
            if m.get("type") in ("role_binding_updated", "role_binding_error"):
                p = m["payload"]; print(m["type"], p.get("role"), p.get("instance_id"), p.get("model_override"), p.get("status"), p.get("error")); return
asyncio.run(main())
