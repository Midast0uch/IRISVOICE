import asyncio, json, websockets


async def test():
    uri = "ws://localhost:8000/ws/test_final?session_id=s_final"
    async with websockets.connect(uri) as ws:
        try:
            while True:
                await asyncio.wait_for(ws.recv(), timeout=0.2)
        except asyncio.TimeoutError:
            pass

        await ws.send(json.dumps({"type": "select_category", "category": "agent"}))
        try:
            await asyncio.wait_for(ws.recv(), timeout=1)
        except:
            pass

        await ws.send(
            json.dumps(
                {
                    "type": "confirm_card",
                    "payload": {
                        "section_id": "inference_mode",
                        "values": {"inference_mode": "api"},
                    },
                }
            )
        )
        for _ in range(5):
            try:
                r = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                if r.get("type") == "card_confirmed":
                    break
            except:
                pass

        await ws.send(
            json.dumps(
                {
                    "type": "confirm_card",
                    "payload": {
                        "section_id": "model_selection",
                        "values": {
                            "model_provider": "api",
                            "api_key": "rtUtK4MUo7ZxhTKc5kfaatpnHDEvSl89mF5fhXgn",
                            "api_base_url": "https://api.cohere.com/compatibility/v1",
                            "reasoning_model": "command-a-03-2025",
                            "tool_model": "command-a-03-2025",
                        },
                    },
                }
            )
        )
        for _ in range(5):
            try:
                r = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                if r.get("type") == "card_confirmed":
                    break
            except:
                pass

        await asyncio.sleep(0.5)

        # TEST 1: Caducean Governor
        print("### TEST 1: Caducean Governor ###")
        await ws.send(
            json.dumps(
                {
                    "type": "text_message",
                    "payload": {"text": "What phase is the Caducean governor in?"},
                }
            )
        )
        full = ""
        for _ in range(50):
            try:
                r = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                mt = r.get("type", "?")
                pl = r.get("payload", {})
                if mt == "chat_chunk":
                    full += pl.get("chunk", "")
                    print(pl.get("chunk", ""), end="", flush=True)
                elif mt == "chat_message":
                    print()
                    break
                elif mt in ("inference_event", "chat_typing", "system_status"):
                    pass
            except asyncio.TimeoutError:
                break
        cad_pass = (
            "exploit" in full.lower() or "xi" in full.lower() or "phase" in full.lower()
        )
        print("Caducean: " + ("PASS" if cad_pass else "FAIL") + " (" + full[:120] + ")")

        await asyncio.sleep(0.5)

        # TEST 2: Tool Calling
        print()
        print("### TEST 2: Tool Calling ###")
        await ws.send(
            json.dumps(
                {
                    "type": "text_message",
                    "payload": {
                        "text": "Use the web search tool to find a fun fact about cats."
                    },
                }
            )
        )
        full = ""
        tools = 0
        for _ in range(100):
            try:
                r = json.loads(await asyncio.wait_for(ws.recv(), timeout=40))
                mt = r.get("type", "?")
                pl = r.get("payload", {})
                if mt == "chat_chunk":
                    full += pl.get("chunk", "")
                    print(pl.get("chunk", ""), end="", flush=True)
                elif mt == "chat_message":
                    t = pl.get("text", "")
                    if t and t not in full:
                        full += t
                    print()
                    break
                elif mt == "tool_result":
                    tools += 1
                    print()
                    print(">>> TOOL #" + str(tools))
                elif mt in ("inference_event", "chat_typing", "system_status"):
                    pass
            except asyncio.TimeoutError:
                print()
                print("TIMEOUT")
                break
        print()
        print("Tool calls: " + str(tools))
        print("Response: " + full[:300])
        print()
        print("### SUMMARY ###")
        print("Caducean: " + ("PASS" if cad_pass else "FAIL"))
        print("Tools: " + str(tools) + " " + ("(PASS)" if tools > 0 else "(FAIL)"))


asyncio.run(test())
