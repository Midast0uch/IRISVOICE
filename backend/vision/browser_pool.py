"""Pooled Playwright browser lifecycle for the server-side vision browser (T-browser-pool).

Mirrors the idle/lease shape already proven for the vision server in
``backend/tools/vision_provider.py`` — read that file first, this is the same
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

from backend.vision.browser_host import get_browser_host

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Idle timeout — env-configurable, mirrors IRIS_VISION_IDLE_TIMEOUT's shape.
# Session-326 default is 60s idle grace: back-to-back runs stay warm, idle
# RAM frees on its own. Raise it if a short gap cold-starts twice in a row.
# ---------------------------------------------------------------------------
# Session 366: 60 -> 180 to match the contract the crawler ALREADY documents
# (capabilities.py and iris_gateway.py name 180 s in three places). MEASURED: at
# 60 s the BOOT pre-warm started Chromium, the idle watchdog stopped it ~72 s
# later, and the crawl then cold-started it anyway - so the pre-warm was pure
# waste AND the cold acquire (1.7-9.5 s) was paid twice. 180 s keeps it warm
# across the planning phase that precedes the first crawl of a turn.
_IDLE_TIMEOUT: float = float(os.environ.get("IRIS_BROWSER_IDLE_TIMEOUT", "180"))

# Session-326 (owner: 60s idle grace). The shell closes after 60s with no
# live lease — back-to-back runs stay warm, idle RAM frees on its own.
# Set IRIS_BROWSER_HOLD_OPEN=1 to keep one Chromium for backend lifetime.
_HOLD_OPEN: bool = os.environ.get("IRIS_BROWSER_HOLD_OPEN", "0") == "1"
# The web toggle holds the browser warm (owner 2026-10-02, audit addendum H):
# while web access is ON, Chromium starts at once and stays up, so the
# agent's first browser_open opens a tab instead of paying a cold launch
# (measured 90-180 s on this machine's C: disk; the agent call timed out).
_web_hold: bool = False


def _held_open() -> bool:
    return _HOLD_OPEN or _web_hold

# REQ-18 AC4 (T20): bound a cold Chromium launch so a wedged start fails open
# instead of pinning the run (or the pool start lock). Env-overridable; the
# default is generous (a cold launch measured ~33s) but finite.
_ACQUIRE_TIMEOUT_MS: int = int(os.environ.get("IRIS_BROWSER_ACQUIRE_TIMEOUT_MS", "90000"))

# D5 memory bounds for the ONE Chromium (pool + agent sessions). Renderer count
# and JS heap are capped, no GPU process, no extensions; crawl contexts also drop
# media/font requests (see ``BLOCKED_CRAWL_RESOURCES``).
_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--renderer-process-limit=4",
    "--js-flags=--max-old-space-size=256",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--disable-extensions",
]
BLOCKED_CRAWL_RESOURCES = frozenset({"media", "font"})


async def block_heavy_resources(target) -> None:
    """Drop media and fonts before they are fetched, on a crawl context or page
    (D5 memory bound). Best-effort - a target without ``route`` just loads them."""

    async def _gate(route) -> None:
        if route.request.resource_type in BLOCKED_CRAWL_RESOURCES:
            await route.abort()
        else:
            await route.continue_()

    try:
        await target.route("**/*", _gate)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[browser_pool] resource blocking not installed: %s", exc)

# Shared Chromium process state. None until the first acquire_browser().
_pw = None  # Playwright driver instance (opaque; typed loosely — lazy import)
_browser = None  # Chromium Browser instance (opaque)
_owned: bool = False  # True once THIS module started _browser (ownership tracking)

# Guards the lazy-start critical section so two concurrent acquire_browser()
# calls race-free share one launch instead of racing two launches.
_start_lock = asyncio.Lock()
# The ONE Chromium launch in flight. A caller's wait is bounded, the launch is
# not: a bound that cancels the launch made every cold attempt start again
# from zero (live 2026-10-02: two 90 s timeouts, then 4.5 s). A later caller
# joins the same launch.
_launch_task: Optional[asyncio.Task] = None
# One SPARE context + blank page, built in the background while web is ON, so
# an agent's browser_open adopts a page whose renderer already started. Run A4
# (2026-10-02, warm Chromium, loop never blocked): new_context 3.0 s +
# new_page 29.9 s inside the first open. Used once (fresh, never shared), then
# replaced off the answer path. Lives and dies on the host loop.
_spare = None  # (context, page) or None
_spare_task: Optional[asyncio.Task] = None
# How long an open waits for an in-flight spare before building its own page.
_SPARE_WAIT_S = 60.0

_last_browser_use: float = 0.0
_idle_task: Optional[asyncio.Task] = None
_idle_task_lock = threading.Lock()  # guards _idle_task against concurrent touches
_browser_idle_callback = None  # set by the caller to broadcast idle-stop status

# REQ-18 (T20): cold/warm acquire accounting. `_warm` is True while a live run
# has DECLARED it needs the browser (see `declare_browser_run`), so the idle
# watchdog holds warmth BETWEEN two URLs of the same run instead of firing the
# 60s idle-stop in the gap. `_last_acquire_was_cold` records whether the most
# recent acquire paid a launch, for REQ-18 AC1's per-run split.
_warm_run_holders: int = 0  # count of runs holding warmth (nested/parallel safe)
_last_acquire_was_cold: bool = False


def declare_browser_run() -> None:
    """Declare that a RUN needs the browser, holding the pool warm (REQ-18 AC2).

    While at least one run holds warmth the idle watchdog does NOT stop the
    browser between two URLs of that run, so a cold launch is paid at most once
    per run where a warm pool was achievable. Release with
    ``release_browser_run`` on every exit path. Counted, so nested/parallel runs
    are safe. Never raises.
    """
    global _warm_run_holders
    try:
        _warm_run_holders += 1
        _touch_browser_use()
    except Exception:  # noqa: BLE001 — warmth is best-effort
        pass


def release_browser_run() -> None:
    """Release one run's warmth hold (REQ-18 AC2). Never raises."""
    global _warm_run_holders
    try:
        _warm_run_holders = max(0, _warm_run_holders - 1)
        _touch_browser_use()
    except Exception:  # noqa: BLE001
        pass


def has_warm_run_holder() -> bool:
    """True while any run is holding the pool warm (REQ-18 AC2)."""
    return _warm_run_holders > 0


def last_acquire_was_cold() -> bool:
    """Whether the most recent acquire paid a cold Chromium launch (REQ-18 AC1)."""
    return _last_acquire_was_cold


def set_browser_idle_callback(cb) -> None:
    """Register a callback invoked when the idle watchdog stops the browser."""
    global _browser_idle_callback
    _browser_idle_callback = cb


def _touch_browser_use() -> None:
    """Record a browser use and (re)schedule the idle auto-stop watchdog.

    Only schedules a watchdog when this module owns the browser (``_owned``),
    so a hypothetical externally-supplied browser is never idled out. Uses an
    asyncio task (not ``threading.Timer``) because the stop path is async
    (``await browser.close()``); that task runs on the browser host loop.
    """
    global _last_browser_use
    _last_browser_use = time.monotonic()
    if _held_open():
        return  # held open (env or web toggle) — no watchdog to schedule
    if not _owned and _idle_task is None:
        return  # nothing to schedule and nothing to cancel
    # The watchdog task lives on the host loop (it stops the browser there). A
    # touch can come from any loop or thread (declare/release_browser_run are
    # sync), so the (re)schedule is handed to the host loop, never done here.
    host = get_browser_host()
    if host.on_loop():
        _reschedule_idle_watch()
    else:
        host.loop().call_soon_threadsafe(_reschedule_idle_watch)


def _reschedule_idle_watch() -> None:
    """Replace the idle watchdog task. Runs ON the host loop."""
    global _idle_task
    with _idle_task_lock:
        if _idle_task is not None:
            _idle_task.cancel()
            _idle_task = None
        if _owned:
            _idle_task = asyncio.get_running_loop().create_task(_idle_watch())


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
    if _held_open():
        return False  # held open (env or web toggle) — the watchdog never fires
    if not _owned:
        return False
    if has_active_browser_lease():
        return False  # a live session must never be idle-stopped out from under it
    if has_warm_run_holder():
        # REQ-18 AC2 (T20): a run declared it needs the browser — hold warmth
        # BETWEEN two URLs of the same run so the idle-stop does not fire in the
        # gap and force a second cold launch.
        return False
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
    """Launch Playwright + Chromium once (as the shared ``_launch_task``).

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
        # Session-331: launch with a REALISTIC UA and automation signals
        # suppressed. The default Playwright UA advertises
        # "HeadlessChrome/<ver>", which search engines detect and answer with a
        # JS challenge (measured 2026-09-15: Bing returned a 68 KB challenge
        # page with NO search box and empty body text, which search_discovery
        # then misread as `wall=login` and parked — T2 never completed). With a
        # normal UA + --disable-blink-features=AutomationControlled the SAME
        # headless Chromium got a real Bing results page WITH the search box.
        # This is NOT CAPTCHA-solving (REQ-19 AC5 stays honoured): it is simply
        # not advertising that we are a bot in the first place. A genuine
        # CAPTCHA/login wall is still detected and parked unchanged.
        #
        # The args launch is tolerant of doubles (tests / alternate drivers)
        # that accept only ``headless`` — retry bare rather than crash the pool.
        try:
            browser = await pw.chromium.launch(headless=True, args=_LAUNCH_ARGS)
        except TypeError:
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

    The launch and every later touch of the browser run on the browser host loop
    (``browser_host``), whichever loop calls this. The returned Browser is a
    host-loop object: the caller must run the coroutines that use it on the host
    loop too (``get_browser_host().run(...)``), or only hold the lease (prewarm).
    """
    return await get_browser_host().run(_acquire_browser_on_host(max_lease_ms))


async def _acquire_browser_on_host(max_lease_ms: float):
    """``acquire_browser`` body. Runs ON the host loop.

    The caller MUST release the returned lease on every exit path, including
    exceptions (``BrowserSession.close()`` does this). While the lease is
    held the idle watchdog will not stop the browser.

    Liveness: a Chromium process that CRASHED (OOM, GPU reset, driver kill)
    leaves ``_browser`` a non-None Playwright object with a dead transport —
    every later ``browser.new_context()`` raised
    ``'NoneType' object has no attribute 'send'`` (live: conv-81, two
    screenshot_page failures at 21:44 with no recovery until backend
    restart). ``is_connected()`` detects the corpse; the stale handles are
    torn down and a fresh browser started so the pool SELF-HEALS instead of
    staying poisoned forever.

    Raises ``ImportError`` if Playwright is not installed, or any other
    exception on a hard launch failure — never silently returns a broken
    browser.

    REQ-18 (T20): the acquire is CLASSIFIED cold (paid a Chromium launch) vs
    warm (reused a live browser) and the classification is recorded so the
    per-run split is visible without re-measuring (AC1). A cold launch is
    ANNOUNCED on the idle/lifecycle callback channel (AC3). The whole acquire
    is bounded by ``_ACQUIRE_TIMEOUT_MS`` and FAILS OPEN — a wedged launch
    raises so the caller (BrowserSession.open) degrades the session to
    unavailable, and the pool start lock is released by the ``async with`` on
    the way out (AC4).
    """
    global _last_acquire_was_cold, _launch_task
    _acquire_t0 = time.monotonic()
    launch = None
    async with _start_lock:
        _was_cold = _browser is None
        if _browser is not None and not _browser.is_connected():
            logger.warning(
                "[browser_pool] shared browser is not connected (crashed?) "
                "— tearing down and restarting"
            )
            await _stop_owned_browser()
            _was_cold = True
        if _browser is None:
            _was_cold = True
            if _launch_task is None or _launch_task.done():
                _launch_task = asyncio.get_running_loop().create_task(_start_browser())
            launch = _launch_task
    if launch is not None:
        # REQ-18 AC4 (T20): this CALLER's wait is bounded and fails open; the
        # launch itself is shielded and keeps going for the next caller.
        try:
            await asyncio.wait_for(
                asyncio.shield(launch), timeout=max(1.0, _ACQUIRE_TIMEOUT_MS / 1000.0),
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[browser_pool] Chromium launch still running after %.0f s; this "
                "call fails open, the launch continues for the next caller",
                time.monotonic() - _acquire_t0,
            )
            raise
    _last_acquire_was_cold = _was_cold
    _acquire_ms = int((time.monotonic() - _acquire_t0) * 1000)
    # REQ-18 AC1/AC3 (T20): record the cold/warm split per acquire and announce
    # a cold launch on the lifecycle channel. Off the critical path.
    _record_acquire(_acquire_ms, _was_cold)
    lease = acquire_browser_lease(max_lease_ms)
    _touch_browser_use()
    return _browser, lease


def _record_acquire(duration_ms: int, cold: bool) -> None:
    """Emit the acquire accounting + announce a cold launch (REQ-18 AC1/AC3).

    Never raises: a status broadcast must never fail an acquire.
    """
    try:
        from backend.vision.stage_timing import record_stage

        record_stage("", "browser_acquire", duration_ms, cold=cold, warm=not cold)
    except Exception:  # noqa: BLE001
        pass
    if cold:
        cb = _browser_idle_callback
        if cb is not None:
            try:
                cb("cold_launch")
            except TypeError:
                # The existing idle callback takes no args — honour that shape.
                try:
                    cb()
                except Exception:  # noqa: BLE001
                    pass
            except Exception:  # noqa: BLE001 — announce must never fail the launch
                pass


async def _make_spare() -> None:
    """Build the spare context + blank page. Runs ON the host loop; never raises."""
    global _spare
    if _browser is None or _spare is not None or not _web_hold:
        return
    t0 = time.monotonic()
    try:
        from backend.vision.browser_session import _new_context  # lazy: cycle

        ctx = await _new_context(_browser)
        page = await ctx.new_page()
        if _spare is None and _browser is not None:
            _spare = (ctx, page)
            logger.info("[browser_pool] spare page ready in %.1f s", time.monotonic() - t0)
        else:
            await ctx.close()
    except Exception as exc:  # noqa: BLE001 — a spare is a bonus; open() builds its own
        logger.info("[browser_pool] spare page not built: %s", exc)


def _schedule_spare() -> None:
    """(Re)build the spare in the background. Call ON the host loop."""
    global _spare_task
    if _web_hold and _browser is not None and _spare is None and (
            _spare_task is None or _spare_task.done()):
        _spare_task = asyncio.get_running_loop().create_task(_make_spare())


async def take_spare_page():
    """The spare (context, page) for ONE session, or None. Runs ON the host
    loop; a replacement is scheduled at once."""
    global _spare
    task = _spare_task
    if _spare is None and task is not None and not task.done():
        # A spare is being built: wait for it rather than build a second page
        # beside it. Cold run 2026-10-03: the spare took 42 s while the open
        # built its own page in parallel (29.6 s) - two page builds on a cold
        # Chromium slow each other. Shielded: the wait may give up (the caller
        # then builds its own page), the build is never cancelled.
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=_SPARE_WAIT_S)
        except Exception:  # noqa: BLE001 - timeout or a failed build: own page
            pass
    sp, _spare = _spare, None
    if sp is not None and (_browser is None or not _browser.is_connected()):
        sp = None  # a spare of a dead browser is no page at all
    _schedule_spare()
    return sp


async def _drop_spare() -> None:
    global _spare
    sp, _spare = _spare, None
    if sp is not None:
        try:
            await sp[0].close()
        except Exception:  # noqa: BLE001
            pass


async def _stop_owned_browser() -> None:
    """Close the Chromium browser + Playwright driver IRIS itself started.

    Ownership-gated: a browser this module did not start (``_owned`` False)
    is left alone — mirrors ``vision_provider._stop_owned_vision_server``'s
    tracked-PID guard. Never raises.
    """
    global _pw, _browser, _owned
    if not _owned or _browser is None:
        return
    await _drop_spare()
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


def set_web_hold(enabled: bool) -> None:
    """The web toggle: ON starts Chromium now (background, never waited on)
    and holds it warm; OFF returns it to the idle watchdog. Never raises."""
    global _web_hold
    _web_hold = bool(enabled)
    try:
        host = get_browser_host()
        if enabled:
            asyncio.run_coroutine_threadsafe(_prewarm_on_host(), host.loop())
            # keyring's first import + backend discovery (9.5 s measured) is
            # paid here, not inside the agent's first browser_open.
            from backend.vision.browser_session import warm_keyring

            threading.Thread(target=warm_keyring, name="iris-keyring-warm", daemon=True).start()
        else:
            _touch_browser_use()  # schedule the idle stop again
    except Exception as exc:  # noqa: BLE001 — a toggle must never fail on warmth
        logger.warning("[browser_pool] web hold %s failed: %s", enabled, exc)


async def _prewarm_on_host() -> None:
    t0 = time.monotonic()
    try:
        _browser_obj, lease = await _acquire_browser_on_host(10_000.0)
        lease.release()
        logger.info("[browser_pool] web toggle prewarm ready in %.1f s", time.monotonic() - t0)
        _schedule_spare()
    except Exception as exc:  # noqa: BLE001 — the launch (if any) keeps going
        logger.info("[browser_pool] web toggle prewarm: %s", exc or type(exc).__name__)


async def shutdown_browser_pool() -> None:
    """Explicit teardown — 'killed by the brain when no longer needed'.

    Cancels the idle watchdog, drops all outstanding lease bookkeeping, and
    closes the browser if this module owns it. Idempotent; never raises.
    """
    await get_browser_host().run(_shutdown_on_host())


async def _shutdown_on_host() -> None:
    """``shutdown_browser_pool`` body. Runs ON the host loop."""
    global _idle_task, _launch_task
    launch, _launch_task = _launch_task, None
    if launch is not None and not launch.done():
        launch.cancel()
        try:
            await launch
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
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


async def reset_browser_pool() -> None:
    """Force-tear-down the owned browser so the NEXT ``acquire_browser`` starts
    a fresh Chromium.

    Session-331 (live T2): after the in-app browser hit a Bing login wall the
    shared Chromium's transport died, but a later ``new_context()`` still failed
    with ``'NoneType' object has no attribute 'send'`` — i.e. the corpse was not
    always caught by the ``is_connected()`` pre-check in ``acquire_browser`` (a
    crash can land between that check and the first call, or ``is_connected()``
    can still report True on a half-dead transport). A caller that OBSERVES the
    corpse signature can call this to guarantee the poisoned handles are gone
    before retrying. Idempotent; never raises.
    """
    await get_browser_host().run(_reset_on_host())


async def _reset_on_host() -> None:
    """``reset_browser_pool`` body. Runs ON the host loop."""
    global _idle_task
    task = None
    with _idle_task_lock:
        if _idle_task is not None:
            task = _idle_task
            task.cancel()
            _idle_task = None
    if task is not None:
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    await _stop_owned_browser()


__all__ = [
    "BrowserLease",
    "acquire_browser",
    "acquire_browser_lease",
    "declare_browser_run",
    "has_active_browser_lease",
    "has_warm_run_holder",
    "last_acquire_was_cold",
    "release_browser_run",
    "reset_browser_pool",
    "should_idle_stop_browser",
    "shutdown_browser_pool",
    "set_browser_idle_callback",
]
