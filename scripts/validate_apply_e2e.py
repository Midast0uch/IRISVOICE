"""
End-to-end agent response test through the CORRECTED APPLY routing path.

1. Set distinct per-role bindings (reasoning->cerebras, tool_execution->cerebras)
   via set_role_binding (simulating Brain/Tool dropdowns).
2. Fire the model_selection confirm_card (simulating APPLY) with MODEL NAMES
   in the values (the old bug class).
3. Send a real text_message prompt.
4. Assert the agent produces a chat_message response (routing is intact, not
   broken by a dangling model-name binding).
"""
import asyncio
import json
import websockets

WS_URL = "ws://127.0.0.1:8090/ws/test_client_e2e?session_id=session_iris"


async def main():
    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({
            "type": "set_role_binding",
            "payload": {"role": "reasoning", "instance_id": "cerebras"},
        }))
        await asyncio.sleep(0.3)
        await ws.send(json.dumps({
            "type": "set_role_binding",
            "payload": {"role": "tool_execution", "instance_id": "cerebras"},
        }))
        await asyncio.sleep(0.3)

        # APPLY -> model_selection confirm_card with MODEL NAMES (old bug class)
        await ws.send(json.dumps({
            "type": "confirm_card",
            "section_id": "model_selection",
            "values": {
                "model_provider": "cerebras",
                "reasoning_model": "gemma-4-31b",
                "tool_model": "gemma-4-31b",
                "api_key": "",
            },
        }))
        await asyncio.sleep(0.5)

        # Real prompt
        await ws.send(json.dumps({
            "type": "text_message",
            "payload": {"text": "Reply with exactly: ROUTING_OK"},
        }))

        got_response = False
        got_error = False
        for _ in range(60):  # up to ~30s
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            data = json.loads(msg)
            t = data.get("type") or data.get("event") or data.get("kind")
            if t in ("chat_message", "message"):
                got_response = True
                print("RESPONSE:", json.dumps(data)[:400])
                break
            if t in ("error", "inference_failed", "task:fail"):
                got_error = True
                print("ERROR:", json.dumps(data)[:400])
                break

        print("GOT_RESPONSE" if got_response else "NO_RESPONSE")
        print("GOT_ERROR" if got_error else "NO_ERROR")
        assert got_response and not got_error, "Agent did not produce a clean response through corrected routing"


asyncio.run(main())
