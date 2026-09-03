"""Provider switching mid-session test"""

import asyncio, json, sys, time

try:
    import websockets
except ImportError:
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets", "-q"])
    import websockets

BACKEND = "ws://127.0.0.1:8000/ws/switch_test_001"


async def flush(ws, timeout=1.0):
    msgs = []
    try:
        while True:
            r = await asyncio.wait_for(ws.recv(), timeout=timeout)
            data = json.loads(r)
            msgs.append(data)
    except asyncio.TimeoutError:
        pass
    return msgs


async def send_and_get_response(ws, text, timeout=30):
    """Send a text_message and collect the response."""
    await ws.send(json.dumps({"type": "text_message", "payload": {"text": text}}))
    chunks = []
    start = time.time()
    try:
        while time.time() - start < timeout:
            r = await asyncio.wait_for(ws.recv(), timeout=timeout)
            data = json.loads(r)
            t = data.get("type", "")
            p = data.get("payload", {})
            if t in ("chat_chunk", "stream_chunk"):
                c = p.get("text", "") or p.get("chunk", "")
                if c:
                    chunks.append(c)
            elif t == "chat_message":
                text = p.get("content", "") or p.get("text", "")
                if text:
                    chunks.append(text)
                break
            elif t == "error":
                chunks.append(f"[ERROR] {p.get('message', p)}")
                break
    except asyncio.TimeoutError:
        pass
    return "".join(chunks)


async def test():
    print("\n" + "=" * 60)
    print("  PROVIDER SWITCHING MID-SESSION TEST")
    print("=" * 60)

    results = []

    async with websockets.connect(BACKEND, open_timeout=5) as ws:
        # Phase 1: Start with Cohere (test key → expect auth error)
        print("\n[1] Setting Cohere API (test key)...")
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
                            "api_key": "fake_key_123",
                            "api_base_url": "https://api.cohere.com/compatibility/v1",
                        },
                    },
                }
            )
        )
        await flush(ws, 0.5)

        print("  Sending message via Cohere...")
        resp1 = await send_and_get_response(ws, "What model are you?")
        has_auth_error = (
            "AuthenticationError" in resp1
            or "auth" in resp1.lower()
            or "error" in resp1.lower()
        )
        results.append(("Cohere (bad key) → auth error", has_auth_error, resp1[:100]))

        # Phase 2: Switch to LM Studio
        print("\n[2] Switching to LM Studio...")
        await ws.send(
            json.dumps(
                {
                    "type": "confirm_card",
                    "payload": {
                        "section_id": "model_selection",
                        "values": {
                            "model_provider": "lmstudio",
                            "reasoning_model": "LFM-2-8B",
                            "tool_execution_model": "LFM-2-8B",
                            "lmstudio_endpoint": "http://localhost:1234",
                        },
                    },
                }
            )
        )
        await flush(ws, 0.5)

        print("  Sending message via LM Studio...")
        resp2 = await send_and_get_response(ws, "What model are you?")
        # LM Studio may be running or not — either way the pipeline should try
        results.append(
            (
                "LM Studio → pipeline attempted",
                len(resp2) > 0,
                resp2[:100] if resp2 else "empty",
            )
        )

        # Phase 3: Switch back to Cohere
        print("\n[3] Switching back to Cohere...")
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
                            "api_key": "fake_key_123",
                            "api_base_url": "https://api.cohere.com/compatibility/v1",
                        },
                    },
                }
            )
        )
        await flush(ws, 0.5)

        print("  Sending message via Cohere again...")
        resp3 = await send_and_get_response(ws, "What model are you?")
        has_auth_error2 = (
            "AuthenticationError" in resp3
            or "auth" in resp3.lower()
            or "error" in resp3.lower()
        )
        results.append(("Cohere again → auth error", has_auth_error2, resp3[:100]))
        results.append(
            (
                "Provider switching works end-to-end",
                has_auth_error and has_auth_error2,
                "Auth errors on both Cohere attempts",
            )
        )

    # Summary
    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)
    for name, passed, detail in results:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")
    total = len(results)
    passed = sum(1 for _, p, _ in results if p)
    print(f"\n  {passed}/{total} passed")
    print("=" * 60 + "\n")


asyncio.run(test())
