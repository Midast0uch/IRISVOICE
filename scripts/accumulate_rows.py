"""Drive the IRIS backend via WS to accumulate decision-engine ledger rows.

Sends messages slowly (30s delay) to avoid rate limits. Each message that
triggers tool use generates rows for multiple consumers (tool_choice,
review_verdict, monitor bools, mode, web_intent, surface consumers).

Usage:
    python scripts/accumulate_rows.py [--count N] [--delay S]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import sys
import time

import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("accumulate_rows")

# 127.0.0.1, NOT localhost (2026-09-27). On this machine `localhost` resolves to
# ::1 first (IPv6) and the backend binds 0.0.0.0 (IPv4), so every run died with
# "WinError 1225 The remote computer refused the network connection" and produced
# no traffic at all - which reads like a broken row pipeline rather than a name
# resolution mismatch.
WS_URL = "ws://127.0.0.1:8090/ws/row-accumulator?session_id=row-accumulator"

# Messages that trigger different consumers:
# - tool_choice: any message that needs a tool
# - web_intent: messages that need web search
# - review_verdict: any completed step
# - sufficient/done/on_track: any step completion
# - mode: any message
# - has_gaps: any completed step
# - use_thinking: any message
# - escalate_incomplete: any step with incomplete results
# - needs_action: any message
MESSAGES = [
    # ── LOCAL-TOOL prompts FIRST (2026-09-27) ──
    # The completion monitors (sufficient, done, on_track) and the per-step
    # director (has_gaps) only fire when a step COMPLETES. The web prompts below
    # fail on this box (search blocked), so those consumers never saw a
    # completed step and had zero rows. These prompts use tools that succeed
    # locally - file reads, directory listing, system info, memory - so steps
    # actually finish and the completion checks run.
    "List the files in the current directory and tell me how many there are.",
    # NOT "read the README and summarise": README.md is 83 KB (~20k tokens), so
    # that single prompt cost 187 s of prefill where a light one costs 11 s.
    # Measured 2026-09-27. Same evidence value, no giant prompt. The rule for
    # this list: prefer tools that read LITTLE - directory listings, system
    # info, a small file - never a large document.
    "List the files in the backend/agent folder and tell me how many Python "
    "files there are.",
    "Get the system info and tell me how much memory this machine has.",
    "List the files in the scripts folder and pick the one with the longest name.",
    "Remember that my project is called IRIS, then recall what my project is called.",
    "Get the system info, then list the files in the current directory, and "
    "compare the two results in one summary.",
    # ── MULTI-STEP prompts ──
    "Research the three most popular electric cars of 2026, compare their "
    "prices and ranges, then write a short comparison table.",
    "Find the latest news about quantum computing, then look up one of the "
    "companies mentioned and summarise both findings.",
    "Look up the population of Tokyo and of Osaka, compare them, and explain "
    "which is larger and by how much.",
    "Search for the best pasta recipes, pick the one with the fewest "
    "ingredients, and list exactly what I need to buy.",
    "Find the current price of Bitcoin and of Ethereum, compare the two, and "
    "explain what drives the difference.",
    "Research the top three Python async libraries, then find one working "
    "example of the best one and summarise it.",
    "Look up the distance from Earth to Mars and to Venus, compare them, and "
    "tell me which is closer on average.",
    "Find two recent articles about renewable energy, compare their main "
    "claims, and tell me where they disagree.",
    "Search for the best hiking trails in Colorado, pick three, and compare "
    "their difficulty and length.",
    "Research the current state of AI regulation in the EU and in the US, then "
    "compare the two approaches in a short summary.",
    # ── one-shot lookups ──
    "What's the weather in Seattle?",
    "Search for the latest news about AI",
    "Find information about climate change",
    "Look up the stock price of Apple",
    "Search for best restaurants in Tokyo",
    "What's the capital of France?",
    "Find the latest sports scores",
    "Search for information about space exploration",
    "What's the population of New York City?",
    "Find recipes for pasta",
    "Search for the best laptops of 2026",
    "What's the time in London?",
    "Find information about electric cars",
    "Search for the latest movie reviews",
    "What's the distance from Earth to Mars?",
    "Find the best hiking trails in Colorado",
    "Search for information about quantum computing",
    "What's the price of Bitcoin?",
    "Find the latest news about technology",
    "Search for information about renewable energy",
]


def _ws_url(client: str) -> str:
    """Build the WS URL for a distinct client.

    The client id is a parameter (2026-09-27) so several accumulators can run at
    once: two processes sharing one client id are the SAME client to the server,
    so the second connection replaces the first and half the traffic is lost.
    """
    return f"ws://127.0.0.1:8090/ws/{client}?session_id={client}"


# The local model server's address. The app launches it on 8082; IRIS_LOCAL_PORT
# overrides if that ever moves.
LOCAL_MODEL_HOST = "127.0.0.1"
LOCAL_MODEL_PORT = int(os.environ.get("IRIS_LOCAL_PORT", "8082"))

# How long to wait for the local model before refusing to send any traffic.
READY_TIMEOUT_S = 180.0


async def _wait_for_local_model_ready(timeout: float = READY_TIMEOUT_S) -> bool:
    """Block until the local model server's port accepts work, or give up.

    WHY THIS EXISTS (measured 2026-09-27). This driver used to fire message 1
    immediately after asking the app to load the model, with no gate at all.
    The load and the first request landed in the same SECOND, and that run
    produced 12 of 13 turns answered with "[IRIS error] The provider request
    failed 3 times" - which TTS then SPOKE ALOUD - and zero rows.

    WHY IT PROBES A TCP CONNECT AND NOT /health (measured the same day, after
    the first version of this gate got it wrong). With --parallel 1 the single
    slot is nearly always busy while the app is working, and this llama-server
    build's /health and /props handlers BLOCK while a slot is processing. So a
    perfectly healthy server looks dead:

      - /props answered fine while the server was idle, then timed out for 8 s
        mid-generation;
      - the process CPU clock looked frozen (10.40625 -> 10.40625 across 6 s),
        which proves nothing: GPU decode barely moves CPU time;
      - the server's OWN stderr showed it serving throughout:
        "slot release: id 0 | task 0 | stop processing: n_tokens = 2112".

    A TCP connect answers the only question this gate needs - is the port
    accepting work yet - and it cannot contend for the model lock.
    """

    def _probe() -> None:
        with socket.create_connection(
            (LOCAL_MODEL_HOST, LOCAL_MODEL_PORT), timeout=3
        ):
            return

    deadline = time.monotonic() + timeout
    last = "no attempt yet"
    while time.monotonic() < deadline:
        try:
            await asyncio.to_thread(_probe)
            logger.info(
                "Local model server is accepting connections on %s:%d",
                LOCAL_MODEL_HOST, LOCAL_MODEL_PORT,
            )
            return True
        except Exception as exc:
            last = type(exc).__name__
        logger.info(
            "Waiting for the local model server (%s) on %s:%d",
            last, LOCAL_MODEL_HOST, LOCAL_MODEL_PORT,
        )
        await asyncio.sleep(5.0)
    logger.warning(
        "Local model server still not accepting connections after %.0fs (last: %s)",
        timeout, last,
    )
    return False


async def send_messages(
    count: int, delay: float, web: bool = False, client: str = "row-accumulator"
) -> int:
    """Send messages to the backend via WS.

    Returns 0 when the messages went out, or 4 when the local model server
    never became ready and nothing was sent (see
    :func:`_wait_for_local_model_ready`).
    """
    ws_url = _ws_url(client)
    messages_to_send = MESSAGES[:count] if count > 0 else MESSAGES

    logger.info("Connecting to %s", ws_url)
    async with websockets.connect(ws_url) as ws:
        logger.info("Connected. Sending %d messages with %.0fs delay", len(messages_to_send), delay)

        # GATE FIRST: no traffic while the model is still loading. See the
        # helper's docstring for the measured run this prevents.
        if not await _wait_for_local_model_ready():
            logger.error(
                "Refusing to send: the local model server at %s:%d never "
                "accepted connections. Traffic sent now can only produce error "
                "turns, which TTS then reads aloud. Start the model and run "
                "again.",
                LOCAL_MODEL_HOST, LOCAL_MODEL_PORT,
            )
            return 4

        if web:
            # Internet access is a CAPABILITY GATE, not a routing switch
            # (iris_gateway.py:838): with it OFF the kernel has zero web tools
            # and answers "Web search is currently disabled" — no tool step, so
            # no decision rows at all. Measured 2026-09-26: without this the
            # driver produced zero rows, which looked like a broken row
            # pipeline rather than a closed gate.
            await ws.send(json.dumps({
                "type": "set_web_mode",
                "payload": {"enabled": True},
            }))
            logger.info("Web mode: ON (web tools granted app-wide)")
        else:
            logger.warning(
                "Web mode NOT enabled (--web): web-asking messages will be "
                "answered without a tool call and produce no rows"
            )

        for i, msg in enumerate(messages_to_send):
            logger.info("[%d/%d] Sending: %s", i + 1, len(messages_to_send), msg)

            # Send text_message
            await ws.send(json.dumps({
                "type": "text_message",
                "payload": {"text": msg},
            }))

            # Wait for response (task:done or task:fail)
            try:
                while True:
                    response = await asyncio.wait_for(ws.recv(), timeout=120)
                    data = json.loads(response)
                    msg_type = data.get("type", "")

                    if msg_type in ("task:done", "task:fail", "chat_message"):
                        logger.info("[%d/%d] Received: %s", i + 1, len(messages_to_send), msg_type)
                        break
                    elif msg_type == "ping":
                        # ANSWER THE HEARTBEAT (2026-09-27). The server pings
                        # every client and drops it after 30 s without a pong:
                        #   [WARNING] ws_manager: Client z1 did not respond to
                        #   ping within 30s, disconnecting
                        # This script never replied, so the client was cut off
                        # mid-turn, waited out its own 120 s recv timeout, and
                        # moved on. Measured cost: SIX messages took 4-6 minutes
                        # while the model answered each one in ~20 s - the app
                        # was idle for most of the wall clock. The gateway
                        # handles a client "pong" at iris_gateway.py:905.
                        await ws.send(json.dumps({"type": "pong", "payload": {}}))
                    elif msg_type == "task:progress":
                        pass  # Ignore progress events
                    else:
                        logger.debug("[%d/%d] Received: %s", i + 1, len(messages_to_send), msg_type)

            except asyncio.TimeoutError:
                logger.warning("[%d/%d] Timeout waiting for response", i + 1, len(messages_to_send))
            except Exception as exc:
                logger.warning("[%d/%d] Error: %s", i + 1, len(messages_to_send), exc)

            # Delay between messages to avoid rate limits
            if i < len(messages_to_send) - 1:
                logger.info("Waiting %.0fs before next message...", delay)
                await asyncio.sleep(delay)

        logger.info("Done. Sent %d messages.", len(messages_to_send))
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Accumulate decision-engine ledger rows")
    parser.add_argument("--count", type=int, default=10, help="Number of messages to send")
    parser.add_argument("--delay", type=float, default=30.0, help="Delay between messages in seconds")
    parser.add_argument(
        "--web", action="store_true",
        help="enable internet access first (required for tool-using rows)",
    )
    parser.add_argument(
        "--client", default="row-accumulator",
        help="distinct WS client id, so several accumulators can run at once",
    )
    args = parser.parse_args()

    try:
        return asyncio.run(send_messages(args.count, args.delay, web=args.web,
                                         client=args.client))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 1
    except Exception as exc:
        logger.error("Failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
