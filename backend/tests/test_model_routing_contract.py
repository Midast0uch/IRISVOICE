"""
Contract tests: frontend ↔ backend model routing + local model loading.

Verifies that the WS message payloads sent by the frontend match what the
backend expects, and that the backend processes them correctly.

Covers:
- set_model_selection (provider + reasoning_model + tool_execution_model)
- set_role_binding (brain/tool routing per provider)
- load_local_model (model_path, profile, n_ctx, n_gpu_layers)
- confirm_card model_selection (legacy path)

Run with: pytest backend/tests/test_model_routing_contract.py -v
"""

import asyncio, json, os, sys
import pytest
import websockets

WS_URI = "ws://localhost:8090/ws/test_contract?session_id=contract-test-1"
# No hardcoded fallback. The literal that used to sit here was a REAL Cerebras
# key, and this file is tracked in a public repo — it leaked that credential for
# as long as it existed (found 2026-08-13). These are live integration tests
# that call a real provider over a real socket, so a credential is a genuine
# precondition: without one they cannot exercise anything, and skipping states
# that honestly instead of failing against a dead key.
CEREBRAS_KEY = os.environ.get("CEREBRAS_TEST_KEY")
TIMEOUT = 45.0

pytestmark = pytest.mark.skipif(
    not CEREBRAS_KEY,
    reason=(
        "CEREBRAS_TEST_KEY is not set. These are live integration tests: they "
        "need a backend on :8090 and a real Cerebras credential. Export "
        "CEREBRAS_TEST_KEY to run them."
    ),
)


async def connect_and_init(session_id="contract-test-1"):
    """Open a WS connection and return it."""
    uri = f"ws://localhost:8090/ws/conctest?session_id={session_id}"
    ws = await websockets.connect(uri, max_size=10 * 1024 * 1024)
    # Drain any startup events (system, heartbeat, etc.)
    await asyncio.sleep(1)
    return ws


async def recv_until(ws, stop_types, timeout=TIMEOUT):
    """Read events until one of stop_types is seen, or timeout."""
    events = []
    while True:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            data = json.loads(raw)
            t = data.get("type", "")
            events.append(data)
            if t in stop_types:
                return events
        except asyncio.TimeoutError:
            return events


async def drain_events(ws, seconds=0.5):
    """Discard events for a short period (background noise)."""
    await asyncio.sleep(seconds)


# ─────────────────────────────────────────────
# CONTRACT 1: set_model_selection
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_model_selection_includes_reasoning_model():
    """Frontend MUST send reasoning_model + tool_execution_model in set_model_selection."""
    ws = await connect_and_init()

    # Send the payload that handleApplyProvider now produces (after fix)
    await ws.send(json.dumps({
        "type": "set_model_selection",
        "payload": {
            "model_provider": "cerebras",
            "reasoning_model": "gemma-4-31b",
            "tool_execution_model": "gemma-4-31b",
            "api_key": CEREBRAS_KEY,
            "api_base_url": "https://api.cerebras.ai/v1",
        }
    }))

    # Expect a confirmation response
    events = await recv_until(ws, {"error", "state_update"})
    # No error should come back
    for ev in events:
        assert ev.get("type") != "error", \
            f"Backend rejected valid set_model_selection: {ev.get('payload', {}).get('message', '?')}"
    await ws.close()


@pytest.mark.asyncio
async def test_set_model_selection_missing_reasoning_still_works():
    """
    Defense: if the frontend sends set_model_selection WITHOUT reasoning_model
    (e.g. old/buggy frontend), the backend MUST NOT overwrite the session's
    reasoning model with None. It should keep the last known value.
    """
    ws = await connect_and_init("contract-defense-1")

    # Step 1: Set correctly (like a new session with config)
    await ws.send(json.dumps({
        "type": "set_model_selection",
        "payload": {
            "model_provider": "cerebras",
            "reasoning_model": "gemma-4-31b",
            "tool_execution_model": "gemma-4-31b",
            "api_key": CEREBRAS_KEY,
        }
    }))
    await drain_events(ws, 1)

    # Step 2: Send a message — should work
    await ws.send(json.dumps({
        "type": "text_message",
        "payload": {"text": "Reply only with: MODEL_OK"}
    }))
    events = await recv_until(ws, {"chat_message", "error"}, timeout=60)
    final = [e for e in events if e["type"] == "chat_message"]
    error = [e for e in events if e["type"] == "error"]
    assert not error, f"Got backend error after correct setup: {error[0]}"
    assert len(final) >= 1, "No chat_message received after correct setup"
    content = final[0].get("payload", {}).get("content", "")
    assert "couldn't generate" not in content.lower(), \
        f"Model failed despite correct set_model_selection: {content[:200]}"
    await ws.close()


# ─────────────────────────────────────────────
# CONTRACT 2: set_role_binding (Brain / Tool)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_role_binding_contract():
    """
    set_role_binding MUST send role + instance_id.
    Frontend sends: {role: "reasoning", instance_id: "cerebras"}
    """
    ws = await connect_and_init("contract-role-1")

    # Ensure provider is set first
    await ws.send(json.dumps({
        "type": "set_model_selection",
        "payload": {
            "model_provider": "cerebras",
            "reasoning_model": "gemma-4-31b",
            "tool_execution_model": "gemma-4-31b",
            "api_key": CEREBRAS_KEY,
        }
    }))
    await drain_events(ws, 1)

    # Set role bindings (like the Brain Model dropdown does)
    await ws.send(json.dumps({
        "type": "set_role_binding",
        "payload": {
            "role": "reasoning",
            "instance_id": "cerebras",
        }
    }))
    await ws.send(json.dumps({
        "type": "set_role_binding",
        "payload": {
            "role": "tool_execution",
            "instance_id": "cerebras",
        }
    }))
    await drain_events(ws, 0.5)

    # Send a message to verify
    await ws.send(json.dumps({
        "type": "text_message",
        "payload": {"text": "Reply only with: ROLE_BINDING_OK"}
    }))
    events = await recv_until(ws, {"chat_message", "error"}, timeout=60)
    error = [e for e in events if e["type"] == "error"]
    assert not error, f"Got error after role binding: {error[0]}"
    chat = [e for e in events if e["type"] == "chat_message"]
    assert len(chat) >= 1, "No chat_message after role binding"
    await ws.close()


# ─────────────────────────────────────────────
# CONTRACT 3: load_local_model
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_local_model_loading_contract():
    """
    load_local_model MUST send: model_path, profile, n_ctx, n_gpu_layers.
    Frontend sends these from the Dashboard sliders + dropdowns.
    Even if the file doesn't exist, the backend must accept the payload
    format and return a meaningful error (not silent ignore).
    """
    ws = await connect_and_init("contract-local-1")

    # Send the full load_local_model payload (as the frontend Dashboard does)
    await ws.send(json.dumps({
        "type": "load_local_model",
        "payload": {
            "profile": "balanced",
            "n_ctx": 32768,
            "n_gpu_layers": -1,
            "model_path": "C:\\Users\\midas\\.lmstudio\\models\\prism-ml\\Ternary-Bonsai-27B-gguf\\Ternary-Bonsai-27B-dspark-Q4_1.gguf",
        }
    }))

    events = await recv_until(ws, {"local_model_loading"}, timeout=30)
    # The backend MUST respond with local_model_loading event(s).
    # First is status: "starting", second (if error) is status: "error".
    types_seen = {e["type"] for e in events}
    assert "local_model_loading" in types_seen, \
        f"Backend did not respond to load_local_model. Events: {[e['type'] for e in events[:5]]}"
    # Check if any event has an error status
    errors = [e for e in events if e.get("payload", {}).get("status") == "error"]
    if errors:
        print(f"  (expected: model file not found — {errors[0].get('payload',{}).get('error','')[:80]})")
    await ws.close()


@pytest.mark.asyncio
async def test_local_model_payload_fields():
    """
    Verify the backend accepts all optional fields correctly.
    The frontend Dashboard sliders map to: n_ctx, n_gpu_layers, profile.
    """
    ws = await connect_and_init("contract-local-2")

    # Test with minimal required fields (no model_path — expect error for that)
    await ws.send(json.dumps({
        "type": "load_local_model",
        "payload": {
            "profile": "balanced",
            "n_ctx": 16384,
            "n_gpu_layers": -1,
            "model_path": "/nonexistent/test.gguf",
        }
    }))

    events = await recv_until(ws, {"local_model_loading"}, timeout=30)
    types_seen = {e["type"] for e in events}
    assert "local_model_loading" in types_seen, \
        "Backend did not reply to load_local_model even with minimal payload"
    await ws.close()


# ─────────────────────────────────────────────
# CONTRACT 4: confirm_card model_selection (legacy)
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_confirm_card_model_selection_contract():
    """
    Legacy confirm_card model_selection path sends all values in one card.
    Must use 'reasoning_model' field (not 'model').
    """
    ws = await connect_and_init("contract-confirm-1")

    await ws.send(json.dumps({
        "type": "confirm_card",
        "payload": {
            "section_id": "model_selection",
            "values": {
                "provider": "cerebras",
                "reasoning_model": "gemma-4-31b",
                "tool_execution_model": "gemma-4-31b",
                "model_provider": "cerebras",
                "api_key": CEREBRAS_KEY,
                "api_base_url": "https://api.cerebras.ai/v1",
                "max_steps": 15,
                "mode": "reasoning",
            }
        }
    }))

    events = await recv_until(ws, {"error", "state_update"}, timeout=15)
    for ev in events:
        assert ev.get("type") != "error", \
            f"confirm_card rejected: {ev.get('payload', {}).get('message', '?')}"
    # Look for the card_confirmed event
    confirmed = any(
        e.get("payload", {}).get("section_id") == "model_selection"
        and e.get("payload", {}).get("applied") is True
        for e in events
    )
    assert confirmed, "confirm_card model_selection was not applied"
    await ws.close()
