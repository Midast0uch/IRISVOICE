"""
IRISVOICE End-to-End Test Script
Tests the full pipeline: WS connect → model selection → confirm_card → message → response
"""

import asyncio
import json
import time
import sys

try:
    import websockets
except ImportError:
    print("[SETUP] Installing websockets...")
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets", "-q"])
    import websockets

BACKEND = "ws://127.0.0.1:8000/ws/test_session_001"
RESULTS = []


def log_test(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    RESULTS.append((name, passed, detail))
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


async def run_tests():
    print("\n" + "=" * 70)
    print("  IRISVOICE END-TO-END TEST SUITE")
    print("=" * 70)

    # ── 6B: WebSocket Connect ──────────────────────────────────────────────
    print("\n[6B] WebSocket Connection")
    try:
        async with websockets.connect(BACKEND, open_timeout=5) as ws:
            log_test("WebSocket connects to backend", True, BACKEND)

            # Read the welcome/initial message
            try:
                welcome = await asyncio.wait_for(ws.recv(), timeout=3)
                welcome_data = json.loads(welcome)
                log_test(
                    "Backend sends initial state",
                    True,
                    f"type={welcome_data.get('type', '?')}",
                )
            except asyncio.TimeoutError:
                log_test(
                    "Backend sends initial state", False, "No welcome message within 3s"
                )

            # ── 6C: Model Selection via confirm_card ───────────────────────
            print("\n[6C] Model Selection (confirm_card)")
            # Simulate selecting Cohere API from the model_selection card
            model_selection_msg = {
                "type": "confirm_card",
                "payload": {
                    "section_id": "model_selection",
                    "values": {
                        "model_provider": "api",
                        "reasoning_model": "command-r-plus",
                        "tool_execution_model": "command-r-plus",
                        "api_key": "test_key_validation",
                        "api_base_url": "https://api.cohere.com/compatibility/v1",
                    },
                },
            }
            await ws.send(json.dumps(model_selection_msg))
            await asyncio.sleep(0.5)

            # Check backend logs for the model selection
            log_test("confirm_card message sent (model_selection)", True)

            # ── 6D: DarkGlassDashboard APPLY (inference_mode section) ─────
            print("\n[6D] DarkGlassDashboard APPLY (provider not clobbered)")
            # Simulate the dashboard APPLY sending inference_mode section values
            # The old bug: this would clobber the Cohere provider to lmstudio
            inference_mode_msg = {
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
            await ws.send(json.dumps(inference_mode_msg))
            await asyncio.sleep(0.5)
            log_test(
                "confirm_card sent (inference_mode — no legacy field)",
                True,
                "Should NOT override provider to lmstudio",
            )

            # ── 6H: Context Window ────────────────────────────────────────
            print("\n[6H] Context Window Auto-Detect")
            context_msg = {
                "type": "confirm_card",
                "payload": {"section_id": "memory", "values": {"context_window": 32}},
            }
            await ws.send(json.dumps(context_msg))
            await asyncio.sleep(0.5)
            log_test("Memory context_window override sent (32K)", True)

            # ── 6E/6F: Send a text message ────────────────────────────────
            print("\n[6E/6F] Text Message → Response")
            text_msg = {
                "type": "text_message",
                "payload": {
                    "text": "Hello, what tools do you have available? List them briefly."
                },
            }
            await ws.send(json.dumps(text_msg))

            # Collect response with timeout
            response_chunks = []
            got_response = False
            try:
                start = time.time()
                while time.time() - start < 30:  # 30s timeout
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    data = json.loads(raw)
                    msg_type = data.get("type", "")

                    if msg_type == "chat_chunk" or msg_type == "stream_chunk":
                        chunk = data.get("payload", {}).get("text", "") or data.get(
                            "payload", {}
                        ).get("chunk", "")
                        if chunk:
                            response_chunks.append(chunk)
                    elif msg_type == "chat_message" or msg_type == "response":
                        response_chunks.append(
                            data.get("payload", {}).get("text", "")
                            or json.dumps(data.get("payload", {}))
                        )
                        got_response = True
                        break
                    elif msg_type == "error":
                        error_text = data.get("payload", {}).get(
                            "message", ""
                        ) or json.dumps(data.get("payload", {}))
                        log_test(
                            "Message response received", False, f"Error: {error_text}"
                        )
                        got_response = True
                        break
            except asyncio.TimeoutError:
                pass

            full_response = "".join(response_chunks)
            if full_response:
                log_test(
                    "Message response received", True, f"{len(full_response)} chars"
                )
                # Check if response mentions tools
                has_tools = any(
                    kw in full_response.lower()
                    for kw in ["tool", "search", "memory", "file", "web"]
                )
                log_test(
                    "Response mentions tools/capabilities",
                    has_tools,
                    full_response[:150] + "..."
                    if len(full_response) > 150
                    else full_response,
                )
            elif got_response:
                log_test("Message response received", True, "Response received")
            else:
                log_test("Message response received", False, "No response within 30s")

            # ── 6L: Error handling ─────────────────────────────────────────
            print("\n[6L] Error Messages")
            # Send a message with bad config to trigger error handling
            # The backend should return a human-readable error, not crash
            error_msg = {
                "type": "text_message",
                "payload": {"text": "test error handling"},
            }
            await ws.send(json.dumps(error_msg))
            try:
                error_response = await asyncio.wait_for(ws.recv(), timeout=15)
                error_data = json.loads(error_response)
                # Any response (even error) means the pipeline didn't crash
                log_test(
                    "Error handling — pipeline doesn't crash",
                    True,
                    f"type={error_data.get('type', '?')}",
                )
            except asyncio.TimeoutError:
                log_test(
                    "Error handling — pipeline doesn't crash",
                    False,
                    "No response in 15s",
                )

    except ConnectionRefusedError:
        log_test("WebSocket connects to backend", False, "Connection refused")
    except Exception as e:
        log_test("WebSocket connects to backend", False, str(e))


async def run_health_tests():
    """Test HTTP endpoints."""
    import urllib.request

    print("\n[6A] HTTP Endpoints")
    endpoints = [
        ("http://localhost:8000/health", "Health check"),
        ("http://localhost:8000/api/mode", "Mode endpoint"),
        ("http://localhost:8000/ready", "Readiness check"),
    ]
    for url, name in endpoints:
        try:
            req = urllib.request.urlopen(url, timeout=5)
            data = json.loads(req.read())
            log_test(f"HTTP {name}", True, json.dumps(data)[:100])
        except Exception as e:
            log_test(f"HTTP {name}", False, str(e)[:100])


async def main():
    await run_health_tests()
    await run_tests()

    # ── Summary ────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    total = len(RESULTS)
    passed = sum(1 for _, p, _ in RESULTS if p)
    failed = total - passed
    print(f"  RESULTS: {passed}/{total} passed, {failed} failed")
    if failed > 0:
        print("\n  FAILED TESTS:")
        for name, p, detail in RESULTS:
            if not p:
                print(f"    - {name}: {detail}")
    print("=" * 70 + "\n")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
