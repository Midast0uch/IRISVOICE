"""Apply the owner's Brain/Tool split.

Brain (reasoning)  -> the Ollama CLOUD model gemma4:31b-cloud, for quality.
Tool  (tool_execution) -> the LOCAL LFM 2.6B, for speed.

Why this shape: the local model is fast but small; the 31B is a better reasoner.
A LOCAL 31B is impossible on this box (RTX 3070 = 8 GB VRAM, 16 GB RAM; a Q4
31B needs ~18-20 GB), so the brain must be the cloud model. Ollama's cloud
models run on ollama.com and are proxied through the local Ollama server
(127.0.0.1:11434), verified answering: /api/generate with gemma4:31b-cloud
returned "OK".

Per-role binding is a first-class feature, not a hack:
  agent_kernel.py:19887  set_role_binding(role, instance_id, model_override)
  iris_gateway.py:690    websocket message type "set_role_binding"
  iris_gateway.py:10851  payload {role, instance_id, model_override?}
  iris_gateway.py:1779   "a Brain/Tool split across providers survives an
                          unrelated APPLY"
"""
from __future__ import annotations

import asyncio
import json

CLIENT = "brain"
URL = f"ws://127.0.0.1:8090/ws/{CLIENT}?session_id={CLIENT}"

# (role, provider instance id, model for that role)
BINDINGS = (
    ("reasoning", "ollama", "gemma4:31b-cloud"),
    ("tool_execution", "local:LFM2.5-2.6B-QAD-Q4_0", "LFM2.5-2.6B-QAD-Q4_0"),
)


async def main() -> int:
    import websockets

    async with websockets.connect(URL, max_size=16 * 1024 * 1024) as ws:
        for seq, (role, inst, model) in enumerate(BINDINGS, start=1):
            await ws.send(json.dumps({
                "type": "set_role_binding",
                "payload": {
                    "role": role,
                    "instance_id": inst,
                    "model_override": model,
                },
                "client_id": CLIENT, "seq": seq,
            }))
            print(f"sent {role} -> {inst} [{model}]", flush=True)

            # Read until this binding is acknowledged or refused, so the two
            # binds cannot race and a rejection is never silent.
            deadline = asyncio.get_event_loop().time() + 20
            done = False
            while not done and asyncio.get_event_loop().time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=6)
                except asyncio.TimeoutError:
                    continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                t = msg.get("type", "")
                if t == "role_binding_error":
                    print("REJECTED:", json.dumps(msg.get("payload", {}))[:200], flush=True)
                    return 1
                if t in ("role_binding_updated", "system_status", "model_selection"):
                    print(f"ack {role}: {t}", flush=True)
                    done = True
        print("BOTH BINDINGS SENT", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
