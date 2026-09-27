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

WS_URL = "ws://localhost:8090/ws/row-accumulator?session_id=row-accumulator"

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


async def send_messages(count: int, delay: float, web: bool = False) -> None:
    """Send messages to the backend via WS."""
    messages_to_send = MESSAGES[:count] if count > 0 else MESSAGES

    logger.info("Connecting to %s", WS_URL)
    async with websockets.connect(WS_URL) as ws:
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
    args = parser.parse_args()

    try:
        asyncio.run(send_messages(args.count, args.delay, web=args.web))
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 1
    except Exception as exc:
        logger.error("Failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
