"""
Live validation of the APPLY-button per-role binding fix.

Drives the backend over WebSocket exactly as the frontend APPLY button does:
  1. Register a second provider (cohere) so we have two distinct instances.
  2. Set distinct per-role bindings via set_role_binding (simulating the
     Brain/Tool dropdowns): reasoning->cerebras, tool_execution->cohere.
  3. Fire the model_selection confirm_card (simulating APPLY) with
     model_provider=cerebras, reasoning_model=<MODEL NAME>, tool_model=<MODEL NAME>.
  4. Assert /api/inference/state still shows reasoning->cerebras,
     tool_execution->cohere (NOT collapsed to a model name, NOT clobbered).

Then a second scenario: both roles already same provider -> confirm_card keeps
both bound to the provider INSTANCE ID (not the model name).
"""
import asyncio
import json
import urllib.request

WS_URL = "ws://127.0.0.1:8090/ws/test_client_apply?session_id=session_iris"
STATE_URL = "http://127.0.0.1:8090/api/inference/state"


async def main():
    import websockets

    async with websockets.connect(WS_URL) as ws:
        async def send(msg):
            await ws.send(json.dumps(msg))
            # give the handler a moment
            await asyncio.sleep(0.3)

        # 1. Register cohere as a second provider instance
        await send({
            "type": "set_model_selection",
            "payload": {
                "reasoning_model": "command-a-03-2025",
                "tool_execution_model": "command-a-03-2025",
                "model_provider": "cohere",
                "api_base_url": "https://api.cohere.ai/compatibility/v1",
            },
        })

        # 2. Distinct per-role bindings (Brain/Tool dropdowns)
        await send({"type": "set_role_binding", "payload": {"role": "reasoning", "instance_id": "cerebras"}})
        await send({"type": "set_role_binding", "payload": {"role": "tool_execution", "instance_id": "cohere"}})

        # 3. APPLY -> model_selection confirm_card (model names in values!)
        await send({
            "type": "confirm_card",
            "section_id": "model_selection",
            "values": {
                "model_provider": "cerebras",
                "reasoning_model": "gemma-4-31b",
                "tool_model": "gemma-4-31b",
                "api_key": "",
            },
        })

    # 4. Read state
    with urllib.request.urlopen(STATE_URL, timeout=5) as r:
        state = json.load(r)
    bindings = {b["role"]: b["instance_id"] for b in state["role_bindings"]}
    print("AFTER APPLY (distinct pre-set):", bindings)

    ok = bindings.get("reasoning") == "cerebras" and bindings.get("tool_execution") == "cohere"
    print("PRESERVE_DISTINCT_PASS" if ok else "PRESERVE_DISTINCT_FAIL")
    assert ok, f"Expected reasoning->cerebras, tool->cohere; got {bindings}"

    # --- Scenario 2: both same provider, confirm_card must bind to INSTANCE ID ---
    async with websockets.connect(WS_URL) as ws:
        async def send2(msg):
            await ws.send(json.dumps(msg))
            await asyncio.sleep(0.3)

        # reset both to cerebras
        await send2({"type": "set_role_binding", "payload": {"role": "reasoning", "instance_id": "cerebras"}})
        await send2({"type": "set_role_binding", "payload": {"role": "tool_execution", "instance_id": "cerebras"}})
        await send2({
            "type": "confirm_card",
            "section_id": "model_selection",
            "values": {
                "model_provider": "cerebras",
                "reasoning_model": "gemma-4-31b",
                "tool_model": "gemma-4-31b",
                "api_key": "",
            },
        })

    with urllib.request.urlopen(STATE_URL, timeout=5) as r:
        state2 = json.load(r)
    bindings2 = {b["role"]: b["instance_id"] for b in state2["role_bindings"]}
    print("AFTER APPLY (same provider):", bindings2)
    ok2 = bindings2.get("reasoning") == "cerebras" and bindings2.get("tool_execution") == "cerebras"
    print("SAME_PROVIDER_PASS" if ok2 else "SAME_PROVIDER_FAIL")
    assert ok2, f"Expected both->cerebras (instance id); got {bindings2}"

    print("ALL_LIVE_TESTS_PASS")


asyncio.run(main())
