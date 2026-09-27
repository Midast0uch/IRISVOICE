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
    "Read the README file and summarise what the project is for.",
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


async def send_messages(
    count: int, delay: float, web: bool = False, client: str = "row-accumulator"
) -> None:
    """Send messages to the backend via WS."""
    ws_url = _ws_url(client)
    messages_to_send = MESSAGES[:count] if count > 0 else MESSAGES

    logger.info("Connecting to %s", ws_url)
    async with websockets.connect(ws_url) as ws:
        logger.info("Connected. Sending %d messages with %.0fs delay", len(messages_to_send), delay)

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
        asyncio.run(send_messages(args.count, args.delay, web=args.web,
                                  client=args.client))
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 1
    except Exception as exc:
        logger.error("Failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
