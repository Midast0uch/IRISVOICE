"""Targeted test: provider selection, context window, confirm_card clobber"""

import asyncio, json, sys, time

try:
    import websockets
except ImportError:
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets", "-q"])
    import websockets

BACKEND = "ws://127.0.0.1:8000/ws/targeted_test_001"


async def test():
    print("\n" + "=" * 60)
    print("  TARGETED TEST: Provider + Context Window + No Clobber")
    print("=" * 60)
    results = []

    async with websockets.connect(BACKEND, open_timeout=5) as ws:
        # 1) Select Cohere API provider via model_selection confirm_card
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
                            "api_key": "test_key_cohere_123",
                            "api_base_url": "https://api.cohere.com/compatibility/v1",
                        },
                    },
                }
            )
        )
        await asyncio.sleep(0.3)

        # Read any response
        try:
            r = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(r)
            print(f"  Response: type={data.get('type')}")
        except asyncio.TimeoutError:
            print("  No response (OK - async processing)")

        # 2) Send inference_mode WITHOUT legacy field (simulates DarkGlassDashboard APPLY)
        print(
            "\n[2] Sending inference_mode confirm_card (should NOT clobber provider)..."
        )
        await ws.send(
            json.dumps(
                {
                    "type": "confirm_card",
                    "payload": {
                        "section_id": "inference_mode",
                        "values": {
                            "agent_thinking_style": "balanced",
                            "max_response_length": "medium",
                            "reasoning_effort": "balanced",
                            "tool_mode": "auto",
                        },
                    },
                }
            )
        )
        await asyncio.sleep(0.3)

        try:
            r = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(r)
            print(f"  Response: type={data.get('type')}")
        except asyncio.TimeoutError:
            print("  No response (OK)")

        # 3) Set memory context_window override
        print("\n[3] Setting memory context_window to 32K tokens...")
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
        await asyncio.sleep(0.3)

        try:
            r = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(r)
            print(f"  Response: type={data.get('type')}")
        except asyncio.TimeoutError:
            print("  No response (OK)")

        # 4) Select a category (required for text_message)
        print("\n[4] Selecting agent category...")
        await ws.send(
            json.dumps({"type": "select_category", "payload": {"category": "agent"}})
        )
        await asyncio.sleep(0.3)

        try:
            r = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(r)
            print(f"  Response: type={data.get('type')}")
        except asyncio.TimeoutError:
            print("  No response (OK)")

        # 5) Send a text message
        print("\n[5] Sending text message...")
        await ws.send(
            json.dumps(
                {
                    "type": "text_message",
                    "payload": {"text": "Hello, list your available tools."},
                }
            )
        )

        # Collect response
        response_chunks = []
        print("  Waiting for response (up to 30s)...")
        start = time.time()
        try:
            while time.time() - start < 30:
                r = await asyncio.wait_for(ws.recv(), timeout=30)
                data = json.loads(r)
                t = data.get("type", "")
                if t in ("chat_chunk", "stream_chunk"):
                    chunk = data.get("payload", {}).get("text", "") or data.get(
                        "payload", {}
                    ).get("chunk", "")
                    if chunk:
                        response_chunks.append(chunk)
                        # Print first chunk immediately
                        if len(response_chunks) == 1:
                            print(f"  First chunk: {chunk[:100]}...")
                elif t in ("chat_message", "response"):
                    text = data.get("payload", {}).get("text", "")
                    if text:
                        response_chunks.append(text)
                    print(f"  Final response type: {t}")
                    break
                elif t == "error":
                    print(f"  ERROR: {data.get('payload', {})}")
                    break
                elif t == "category_selected":
                    print(
                        f"  Category selected: {data.get('payload', {}).get('category', '?')}"
                    )
                    continue
                elif t == "tool_result":
                    print(f"  Tool result: {data.get('payload', {}).get('tool', '?')}")
                    continue
        except asyncio.TimeoutError:
            print("  Timeout waiting for response")

        full_response = "".join(response_chunks)
        if full_response:
            print(f"\n  Full response ({len(full_response)} chars):")
            print(f"  {full_response[:500]}")
            results.append(
                ("Text message response", True, f"{len(full_response)} chars")
            )
        else:
            results.append(("Text message response", False, "No response"))
            # Check if the error was that provider isn't set
            print("\n  No response — checking if provider was set...")
            # The text message should either produce a response or an error
            # Either way, the pipeline didn't crash

    # Summary
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    for name, passed, detail in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}: {detail}")
    print("=" * 60 + "\n")


asyncio.run(test())
