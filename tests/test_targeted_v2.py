"""Targeted test v2: flush confirm_card responses before text_message"""

import asyncio, json, sys, time

try:
    import websockets
except ImportError:
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets", "-q"])
    import websockets

BACKEND = "ws://127.0.0.1:8000/ws/targeted_test_v2"


async def flush(ws, timeout=1.0):
    """Consume all pending messages within timeout."""
    msgs = []
    try:
        while True:
            r = await asyncio.wait_for(ws.recv(), timeout=timeout)
            data = json.loads(r)
            msgs.append(data)
    except asyncio.TimeoutError:
        pass
    return msgs


async def test():
    print("\n" + "=" * 60)
    print("  TARGETED TEST V2: Full Pipeline")
    print("=" * 60)

    async with websockets.connect(BACKEND, open_timeout=5) as ws:
        # 1) Set provider to Cohere API
        print("\n[1] Setting provider to Cohere API...")
        await ws.send(
            json.dumps(
                {
                    "type": "confirm_card",
                    "payload": {
                        "section_id": "model_selection",
                        "values": {
                            "model_provider": "api",
                            "reasoning_model": "command-r-plus",
                            "tool_execution_model": "command-r-plus",
                            "api_key": "test_key_123",
                            "api_base_url": "https://api.cohere.com/compatibility/v1",
                        },
                    },
                }
            )
        )
        msgs = await flush(ws)
        types = [m.get("type", "?") for m in msgs]
        print(f"  Responses: {types}")

        # 2) Send inference_mode (should NOT clobber)
        print("\n[2] inference_mode confirm_card (no clobber)...")
        await ws.send(
            json.dumps(
                {
                    "type": "confirm_card",
                    "payload": {
                        "section_id": "inference_mode",
                        "values": {
                            "agent_thinking_style": "balanced",
                            "tool_mode": "auto",
                        },
                    },
                }
            )
        )
        msgs = await flush(ws)
        types = [m.get("type", "?") for m in msgs]
        print(f"  Responses: {types}")

        # 3) Set context_window override
        print("\n[3] Memory context_window = 32K...")
        await ws.send(
            json.dumps(
                {
                    "type": "confirm_card",
                    "payload": {
                        "section_id": "memory",
                        "values": {"context_window": 32},
                    },
                }
            )
        )
        msgs = await flush(ws)
        types = [m.get("type", "?") for m in msgs]
        print(f"  Responses: {types}")

        # 4) Request state to get context
        print("\n[4] Requesting state...")
        await ws.send(json.dumps({"type": "request_state", "payload": {}}))
        msgs = await flush(ws, timeout=2)
        types = [m.get("type", "?") for m in msgs]
        print(f"  Responses: {types}")
        # Check if initial_state has field_values with model_selection
        for m in msgs:
            if m.get("type") == "initial_state":
                fv = m.get("payload", {}).get("state", {}).get("field_values", {})
                ms = fv.get("model_selection", {})
                print(f"  Model selection in state: {ms}")

        # 5) Send text message
        print("\n[5] Sending text message: 'Hello, list your tools'...")
        await ws.send(
            json.dumps(
                {"type": "text_message", "payload": {"text": "Hello, list your tools."}}
            )
        )

        # Collect response
        chunks = []
        print("  Waiting for response (up to 45s)...")
        start = time.time()
        try:
            while time.time() - start < 45:
                r = await asyncio.wait_for(ws.recv(), timeout=45)
                data = json.loads(r)
                t = data.get("type", "")
                p = data.get("payload", {})
                if t in ("chat_chunk", "stream_chunk"):
                    c = p.get("text", "") or p.get("chunk", "")
                    if c:
                        chunks.append(c)
                        if len(chunks) == 1:
                            print(f"  → First chunk: {c[:120]}...")
                elif t == "chat_message":
                    # chat_message uses "content" key, not "text"
                    text = p.get("content", "") or p.get("text", "")
                    if text:
                        chunks.append(text)
                    print(f"  → chat_message received (content={len(text)} chars)")
                    break
                elif t == "chat_typing":
                    continue
                elif t == "error":
                    print(f"  → ERROR: {p.get('message', p)}")
                    break
                elif t in ("card_confirmed", "state_update", "available_models"):
                    continue
                else:
                    print(f"  → Other: {t}")
        except asyncio.TimeoutError:
            print("  Timeout")

        full = "".join(chunks)
        if full:
            print(f"\n  ✅ Response received ({len(full)} chars):")
            print(f"  {full[:600]}")
        else:
            print("\n  ❌ No response received")

    print("\n" + "=" * 60)
    print("  DONE")
    print("=" * 60 + "\n")


asyncio.run(test())
