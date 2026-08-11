"""Pooled Playwright browser lifecycle for the server-side vision browser (T-browser-pool).

Mirrors the idle/lease shape already proven for the vision server in
``backend/tools/lfm_vl_provider.py`` — read that file first, this is the same
pattern applied to Chromium instead of llama-server:

  - ``_IDLE_TIMEOUT`` (env-configurable) + an idle watchdog that stops the
    resource when unused.
  - ``acquire_browser_lease(max_ms)`` -> ``BrowserLease`` with ``.release()``,
    COUNTED (not boolean) and with a HARD EXPIRY so a crashed holder cannot
    leak the resource forever.
  - ``has_active_browser_lease()`` — the watchdog defers while any lease is
    held.
  - ``should_idle_stop_browser()`` — pure predicate.
  - ``_stop_owned_browser()`` — ONLY stops what IRIS itself started
    (ownership tracking via ``_owned``); never kills a browser someone else
    owns.
  - ``set_browser_idle_callback`` for status broadcast.

Problem this fixes: ``backend/vision/browser_session.py`` used to launch a
BRAND NEW Playwright driver + Chromium process on every session's ``open()``
and tear both down on ``close()``. Live evidence 2026-08-10 18:16: one
websearch escalation of 4 URLs to fetch.vision cost 4 cold browser launches —
the dominant latency cost of the escalation path (see
``backend/crawler/crawl_runner.py`` ~:40 for the measured cold-launch cost on
the sibling crawl path).

This module holds ONE Playwright driver + ONE Chromium ``Browser`` instance,
started LAZILY on first ``acquire_browser()``. Callers (``BrowserSession``)
get their own ``browser.new_context()`` — NOT a new browser — so cookies and
storage stay isolated per session (REQ-5 AC2 run-scoped cookie semantics)
while the expensive Chromium process itself is reused.

Heavy import (``playwright``) stays lazy, inside ``_start_browser`` only.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Idle timeout — env-configurable, mirrors IRIS_VISION_IDLE_TIMEOUT's shape.
# Default is longer than the vision server's (180s vs 120s) because a
# websearch escalation can drive several sequential URL sessions through the
# same job; a short timeout would cold-start again between them.
# ---------------------------------------------------------------------------
_IDLE_TIMEOUT: float = float(os.environ.get("IRIS_BROWSER_IDLE_TIMEOUT", "180"))

# Shared Chromium process state. None until the first acquire_browser().
_pw = None  # Playwright driver instance (opaque; typed loosely — lazy import)
_browser = None  # Chromium Browser instance (opaque)
_owned: bool = False  # True once THIS module started _browser (ownership tracking)

# Guards the lazy-start critical section so two concurrent acquire_browser()
# calls race-free share one launch instead of racing two launches.
_start_lock = asyncio.Lock()

_last_browser_use: float = 0.0
_idle_task: Optional[asyncio.Task] = None
_idle_task_lock = threading.Lock()  # guards _idle_task against concurrent touches
_browser_idle_callback = None  # set by the caller to broadcast idle-stop status


def set_browser_idle_callback(cb) -> None:
    """Register a callback invoked when the idle watchdog stops the browser."""
    global _browser_idle_callback
    _browser_idle_callback = cb


def _touch_browser_use() -> None:
    """Record a browser use and (re)schedule the idle auto-stop watchdog.

    Only schedules a watchdog when this module owns the browser (``_owned``),
    so a hypothetical externally-supplied browser is never idled out. Uses an
    asyncio task (not ``threading.Timer``) because the stop path is async
    (``await browser.close()``); the touch always happens from inside an
    already-running event loop (``acquire_browser`` is a coroutine).
    """
    global _last_browser_use, _idle_task
    _last_browser_use = time.monotonic()
    with _idle_task_lock:
        if _idle_task is not None:
            _idle_task.cancel()
            _idle_task = None
        if _owned:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                _idle_task = loop.create_task(_idle_watch())


async def _idle_watch() -> None:
    """Sleep out the idle window, then stop the browser if still idle."""
    try:
        await asyncio.sleep(_IDLE_TIMEOUT)
    except asyncio.CancelledError:
        return
    with _idle_task_lock:
        global _idle_task
        _idle_task = None
    if not should_idle_stop_browser():
        return  # active lease or already stopped -> defer; next touch reschedules
    await _stop_owned_browser()
    cb = _browser_idle_callback
    if cb is not None:
        try:
            cb()
        except Exception:  # noqa: BLE001 — status broadcast must never break teardown
            pass


def should_idle_stop_browser() -> bool:
    """Pure predicate: is the owned browser idle past the timeout?"""
    if not _owned:
        return False
    if has_active_browser_lease():
        return False  # a live session must never be idle-stopped out from under it
    return (time.monotonic() - _last_browser_use) >= _IDLE_TIMEOUT


# --- Browser lease (mirrors VisionLease) -------------------------------------
# A counted lease with a hard expiry. While any lease is active the idle
# watchdog defers the stop, so a BrowserSession (multi-action loop, possibly
# up to SessionBounds.max_wall_ms) cannot have its browser pulled out from
# under it mid-task. Leases are pure bookkeeping here — no browser calls — and
# expire lazily so a crashed holder (never released) cannot leak the browser
# open forever.

_BROWSER_LEASES: dict[str, float] = {}  # lease_id -> monotonic deadline
_LEASE_LOCK = threading.Lock()


class BrowserLease:
    """Context-managed browser lease with hard expiry.

    Usable as ``with acquire_browser_lease(max_ms=...) as lease:`` so the
    lease is ALWAYS released on exception. ``active`` is checked lazily
    against the deadline, so an abandoned lease self-expires.
    """

    __slots__ = ("_lease_id", "_deadline", "_active")

    def __init__(self, lease_id: str, deadline: float):
        self._lease_id = lease_id
        self._deadline = deadline
        self._active = True

    @property
    def lease_id(self) -> str:
        return self._lease_id

    @property
    def deadline(self) -> float:
        return self._deadline

    @property
    def expired(self) -> bool:
        return time.monotonic() >= self._deadline

    @property
    def active(self) -> bool:
        if not self._active:
            return False
        if self.expired:
            self.release()
            return False
        return True

    def renew(self, max_ms: float = 60_000.0) -> None:
        """Push the hard expiry out from NOW — call on session activity.

        The expiry exists so a crashed holder cannot pin the browser forever,
        but a LIVE session that simply runs longer than the initial window must
        not lose its lease: once it lapses, ``has_active_browser_lease()`` goes
        False and the idle watchdog is free to close the browser mid-session.
        That is what produced "Target page, context or browser has been closed"
        live on 2026-08-11 09:18, immediately after "[browser_pool] shared
        browser stopped", while three escalations were still running.

        Renewing on activity keeps the leak guard intact — an abandoned session
        stops renewing and still expires on schedule.
        """
        if not self._active:
            return
        self._deadline = time.monotonic() + max(1.0, max_ms) / 1000.0
        with _LEASE_LOCK:
            if self._lease_id in _BROWSER_LEASES:
                _BROWSER_LEASES[self._lease_id] = self._deadline

    def release(self) -> None:
        if not self._active:
            return
        self._active = False
        with _LEASE_LOCK:
            _BROWSER_LEASES.pop(self._lease_id, None)

    def __enter__(self) -> "BrowserLease":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()  # releases on exception and on normal exit


def acquire_browser_lease(max_ms: float = 120_000.0) -> BrowserLease:
    """Acquire a browser lease that hard-expires after ``max_ms``.

    Unlike the vision lease, this never returns None: a lease is pure
    bookkeeping against the idle watchdog and the browser starts on demand
    inside ``acquire_browser`` before a lease is ever handed out.
    """
    _prune_expired_browser_leases()
    deadline = time.monotonic() + max(1.0, max_ms) / 1000.0
    lease_id = uuid.uuid4().hex
    with _LEASE_LOCK:
        _BROWSER_LEASES[lease_id] = deadline
    return BrowserLease(lease_id, deadline)


def has_active_browser_lease() -> bool:
    """True while at least one unexpired lease is held."""
    _prune_expired_browser_leases()
    with _LEASE_LOCK:
        return bool(_BROWSER_LEASES)


def _prune_expired_browser_leases() -> None:
    now = time.monotonic()
    with _LEASE_LOCK:
        expired = [lid for lid, dl in _BROWSER_LEASES.items() if now >= dl]
        for lid in expired:
            _BROWSER_LEASES.pop(lid, None)


# --- Lazy start / stop --------------------------------------------------------


async def _start_browser() -> None:
    """Launch Playwright + Chromium once. Caller holds ``_start_lock``.

    Heavy import is lazy, here only. ImportError propagates uncaught so
    ``acquire_browser`` callers can distinguish "capability missing" (no
    playwright installed) from a hard launch crash — mirroring the
    distinction ``browser_session.open()`` already made before this pool
    existed. On a launch crash the half-started driver is stopped so the pool
    is left clean for the next attempt to retry.
    """
    global _pw, _browser, _owned
    from playwright.async_api import async_playwright  # noqa: PLC0415 — lazy, heavy

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(headless=True)
    except Exception:
        try:
            await pw.stop()
        except Exception:  # noqa: BLE001 — best-effort cleanup of the half-start
            pass
        raise
    _pw = pw
    _browser = browser
    _owned = True
    logger.info("[browser_pool] shared browser started")


async def acquire_browser(max_lease_ms: float = 120_000.0):
    """Ensure the shared browser is running (starting it lazily on first use)
    and return ``(browser, lease)``.

    The caller MUST release the returned lease on every exit path, including
    exceptions (``BrowserSession.close()`` does this). While the lease is
    held the idle watchdog will not stop the browser.

    Raises ``ImportError`` if Playwright is not installed, or any other
    exception on a hard launch failure — never silently returns a broken
    browser.
    """
    async with _start_lock:
        if _browser is None:
            await _start_browser()
    lease = acquire_browser_lease(max_lease_ms)
    _touch_browser_use()
    return _browser, lease


async def _stop_owned_browser() -> None:
    """Close the Chromium browser + Playwright driver IRIS itself started.

    Ownership-gated: a browser this module did not start (``_owned`` False)
    is left alone — mirrors ``lfm_vl_provider._stop_owned_vision_server``'s
    tracked-PID guard. Never raises.
    """
    global _pw, _browser, _owned
    if not _owned or _browser is None:
        return
    browser, pw = _browser, _pw
    _browser = None
    _pw = None
    _owned = False
    if browser is not None:
        try:
            await browser.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[browser_pool] browser close failed: %s", exc)
    if pw is not None:
        try:
            await pw.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[browser_pool] playwright stop failed: %s", exc)
    logger.info("[browser_pool] shared browser stopped")


async def shutdown_browser_pool() -> None:
    """Explicit teardown — 'killed by the brain when no longer needed'.

    Cancels the idle watchdog, drops all outstanding lease bookkeeping, and
    closes the browser if this module owns it. Idempotent; never raises.
    """
    global _idle_task
    task = None
    with _idle_task_lock:
        if _idle_task is not None:
            task = _idle_task
            task.cancel()
            _idle_task = None
    if task is not None:
        try:
            await task  # let the cancellation actually land before returning
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    with _LEASE_LOCK:
        _BROWSER_LEASES.clear()
    await _stop_owned_browser()


__all__ = [
    "BrowserLease",
    "acquire_browser",
    "acquire_browser_lease",
    "has_active_browser_lease",
    "should_idle_stop_browser",
    "shutdown_browser_pool",
    "set_browser_idle_callback",
]
