"""
IRIS Memory Watchdog

Monitors the backend process RSS.  When memory exceeds configured caps it
takes graduated action:

  SOFT cap (default 800 MB):
    - Run gc.collect()
    - Trigger Mycelium maintenance (compress old episodes)
    - Log a WARNING so the profiler CSV shows the spike

  HARD cap (default 1400 MB):
    - Everything in SOFT
    - Attempt to unload the active local LLM (frees VRAM + CPU RAM)
    - Log an ERROR

Both caps are configurable via env vars:
    IRIS_MEM_SOFT_MB  (default: 800)
    IRIS_MEM_HARD_MB  (default: 1400)

The watchdog runs as a background asyncio task started in main.py lifespan.
It never raises — a watchdog crash must not take down the backend.
"""

import asyncio
import gc
import logging
import os
import time
from typing import Callable, Awaitable, Optional

logger = logging.getLogger("backend.memory.watchdog")

SOFT_CAP_MB: int = int(os.getenv("IRIS_MEM_SOFT_MB", "800"))
HARD_CAP_MB: int = int(os.getenv("IRIS_MEM_HARD_MB", "1400"))
POLL_INTERVAL_S: float = 30.0  # check every 30 seconds

# Minimum seconds between consecutive soft/hard actions (avoid spam)
_SOFT_COOLDOWN_S: float = 120.0
_HARD_COOLDOWN_S: float = 300.0


async def watchdog_loop(
    on_soft: Optional[Callable[[], Awaitable[None]]] = None,
    on_hard: Optional[Callable[[], Awaitable[None]]] = None,
) -> None:
    """Long-running coroutine — run via asyncio.create_task()."""
    try:
        import psutil
        proc = psutil.Process()
    except ImportError:
        logger.warning("[Watchdog] psutil not installed — memory watchdog disabled")
        return

    last_soft: float = 0.0
    last_hard: float = 0.0

    logger.info(
        f"[Watchdog] Started — soft={SOFT_CAP_MB}MB  hard={HARD_CAP_MB}MB  "
        f"poll={POLL_INTERVAL_S}s"
    )

    while True:
        try:
            await asyncio.sleep(POLL_INTERVAL_S)

            rss_mb = proc.memory_info().rss / 1_000_000
            now = time.monotonic()

            if rss_mb > HARD_CAP_MB and (now - last_hard) > _HARD_COOLDOWN_S:
                logger.error(
                    f"[Watchdog] HARD cap — RSS {rss_mb:.0f}MB > {HARD_CAP_MB}MB"
                )
                last_hard = now
                last_soft = now
                await _run_soft_actions(on_soft)
                if on_hard:
                    try:
                        await on_hard()
                    except Exception as e:
                        logger.error(f"[Watchdog] on_hard callback failed: {e}")

            elif rss_mb > SOFT_CAP_MB and (now - last_soft) > _SOFT_COOLDOWN_S:
                logger.warning(
                    f"[Watchdog] SOFT cap — RSS {rss_mb:.0f}MB > {SOFT_CAP_MB}MB"
                )
                last_soft = now
                await _run_soft_actions(on_soft)

        except asyncio.CancelledError:
            logger.info("[Watchdog] Cancelled — shutting down")
            return
        except Exception as e:
            # Never let an error kill the watchdog loop
            logger.exception(f"[Watchdog] Poll error (non-fatal): {e}")


async def _run_soft_actions(
    on_soft: Optional[Callable[[], Awaitable[None]]] = None
) -> None:
    """Default soft-cap mitigation: GC + optional callback."""
    try:
        collected = gc.collect()
        logger.info(f"[Watchdog] gc.collect() freed {collected} objects")
    except Exception as e:
        logger.warning(f"[Watchdog] gc.collect() failed: {e}")

    if on_soft:
        try:
            await on_soft()
        except Exception as e:
            logger.error(f"[Watchdog] on_soft callback failed: {e}")
