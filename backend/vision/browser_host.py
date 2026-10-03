"""One event-loop thread that owns every Playwright object in the backend process.

A Playwright object (driver, Browser, Context, Page) only works on the loop that
created it. The DER loop runs every tool call on a fresh loop, so a browser
started by one call was a corpse or a hang for the next (measured 2026-09-30).
The fix is ONE dedicated loop thread: ``browser_pool`` launches its single
Chromium there, and every coroutine that touches a Playwright object - a crawl
page fetch, a vision session, an agent browser session - is handed over whole
with ``BrowserHost.run`` and awaited from the caller's own loop.

``run`` from the host loop itself awaits inline, so a host coroutine may call
another entry point without deadlocking. The thread is a daemon: a loop close
never joins it, and it needs no shutdown.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import sys
import threading
import time
import traceback
from typing import Any, Coroutine, Optional

logger = logging.getLogger(__name__)

# Loop-lag watchdog (2026-10-02): the first page of a backend process took 45 s
# to reach domcontentloaded while the same navigation outside the backend took
# 0.3-2.8 s. A blocked host loop stalls the Playwright driver too, so EVERY
# browser call waits. The watchdog pings the loop and, when it does not answer
# in time, logs what the loop thread is running - the blocker, by name.
_LAG_PING_S = 0.5
_LAG_ALARM_S = 2.0


class BrowserHost:
    def __init__(self) -> None:
        self._start_lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def loop(self) -> asyncio.AbstractEventLoop:
        """The host loop (the thread starts on first use)."""
        with self._start_lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                t = threading.Thread(
                    target=loop.run_forever, name="iris-browser-loop", daemon=True,
                )
                t.start()
                self._loop = loop
                threading.Thread(
                    target=_watch_lag, args=(loop, t), name="iris-browser-lag", daemon=True,
                ).start()
            return self._loop

    def on_loop(self) -> bool:
        """True when the calling code runs on the host loop."""
        loop = self._loop
        if loop is None:
            return False
        try:
            return asyncio.get_running_loop() is loop
        except RuntimeError:
            return False

    async def run(self, coro: Coroutine[Any, Any, Any], timeout: Optional[float] = None) -> Any:
        """Run ``coro`` on the host loop from any loop and return its result.

        The caller's context variables travel with it (an await would have kept
        them). A timeout or a cancelled caller cancels the hosted coroutine.
        """
        if self.on_loop():
            return await (coro if timeout is None else asyncio.wait_for(coro, timeout))
        ctx = contextvars.copy_context()

        async def _carried() -> Any:
            for var, value in ctx.items():
                var.set(value)
            return await coro

        fut = asyncio.run_coroutine_threadsafe(_carried(), self.loop())
        try:
            waiting = asyncio.wrap_future(fut)
            return await (waiting if timeout is None else asyncio.wait_for(waiting, timeout))
        except BaseException:  # timeout, or the caller being cancelled
            fut.cancel()
            raise


_HOST = BrowserHost()


def get_browser_host() -> BrowserHost:
    return _HOST


def _watch_lag(loop: asyncio.AbstractEventLoop, thread: threading.Thread) -> None:
    """Ping the host loop; on a stall log the loop thread's stack once per stall
    and the stall's length when it ends. Never raises; ends with the loop."""
    while thread.is_alive() and not loop.is_closed():
        answered = threading.Event()
        sent = time.monotonic()
        try:
            loop.call_soon_threadsafe(answered.set)
        except RuntimeError:  # loop closed
            return
        if not answered.wait(_LAG_ALARM_S):
            frame = sys._current_frames().get(thread.ident)
            stack = "".join(traceback.format_stack(frame)[-12:]) if frame else "(no frame)"
            logger.warning("[browser_host] loop blocked > %.0f s; the loop thread is in: %s",
                           _LAG_ALARM_S, stack.replace("\n", " | "))
            answered.wait()
            logger.warning("[browser_host] loop stall ended after %.1f s", time.monotonic() - sent)
        time.sleep(_LAG_PING_S)
