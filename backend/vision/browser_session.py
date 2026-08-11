"""Server-side interactive browser session for vision-driven websearch (T8).

REQ-7 (vision-driven interactive browser session) + REQ-9 (vision input scoped
to the browser session) + REQ-11 AC1 (frame publishing for the live iframe
mirror) + REQ-16 AC3/AC6 (session instrumentation, run identifier in every log
line).

Design (specs/vision-browser-websearch/design.md, D1):
  - The real browser lives SERVER-SIDE. The Playwright driver + Chromium
    PROCESS are POOLED and shared across sessions (``backend/vision/
    browser_pool.py``, started lazily once, closed by its own idle watchdog)
    — this eliminates the per-URL cold browser launch that used to dominate
    escalation latency. Each session still gets its OWN ``browser.new_context()``
    (never shared) so cookies/storage stay isolated (REQ-5 AC2). The frontend
    iframe is only a mirror served from the capture store — it is sandboxed
    without ``allow-same-origin`` and can never be the vision source.
  - This module ONLY executes DOM actions, publishes frames, detects walls, and
    hands back settled DOM. It NEVER calls the vision model and NEVER captures
    the desktop screen (REQ-9 AC2). Action *decisions* are made by the vision
    loop in ``fetch.vision`` (another module) and given to the session via
    :meth:`BrowserSession.act`.
  - Every settled/navigated frame is published best-effort to the capture store
    (REQ-11 AC1) so the browser panel can mirror the session. A publish failure
    never raises (REQ-11 AC5 / REQ-1 AC5).
  - WALL DETECTION (REQ-7) is pure DOM heuristics: structural markers for
    CAPTCHA, form/visible-text markers for LOGIN and PAYWALL. No network calls,
    no VLM. The VLM decides *actions*; detection is cheap DOM checks.

Failure semantics:
  - Playwright import is LAZY (inside ``browser_pool``) and heavy. ANY
    failure to get the pooled browser — unavailable import (ImportError) OR
    a hard launch failure (chromium missing, crash) — degrades ``open()`` to
    ``available() == False`` and returns; it never raises for a pool-start
    failure (REQ-6 AC1 edge: capability unavailable never fails the run).
  - A per-session context/navigation failure (AFTER the pool successfully
    handed back a browser) closes what this session holds (page/context/lease
    — NEVER the shared browser) and re-raises so the caller can record the
    URL unusable with ``transport_error`` (design.md Error Handling).
  - ``close()`` is idempotent and never raises; call sites wrap their work in
    try/finally so the lease is released on every path ("lease must release on
    exception"). ``close()`` never closes the pooled browser — that is
    ``browser_pool``'s job, gated on its own idle watchdog + lease count.
  - Per-action failures are recorded as ``last_error`` observations
    (REQ-7 AC6) — the session survives, the vision model sees the observation.
"""

from __future__ import annotations

import logging
import os
import re
import time
from enum import Enum
from typing import Literal, Optional
from dataclasses import dataclass

from backend.crawler.capture_store import get_capture_store

logger = logging.getLogger(__name__)

# Default Playwright timeouts (ms). Bounded — a stuck page must surface as an
# action failure, not hang the session.
#
# NAVIGATION is deliberately generous. This session's PRIMARY job is pages that
# plain crawling could not read — above all bot-challenge interstitials, which
# only yield after their JS challenge resolves. A 15s cap killed every
# escalation before the challenge could clear: observed live 2026-08-10 18:16,
# four consecutive "Page.goto: Timeout 15000ms exceeded" on exactly the
# challenged URLs the escalation existed to recover. Sitting on a slow page IS
# the feature here; the session's real bound is SessionBounds.max_wall_ms.
_NAVIGATION_TIMEOUT_MS = int(os.environ.get("IRIS_VISION_NAV_TIMEOUT_MS", "45000"))
_ACTION_TIMEOUT_MS = int(os.environ.get("IRIS_VISION_ACTION_TIMEOUT_MS", "5000"))
# Bounding-box capture for the frontend particle-trail cursor mirror (REQ-16
# AC7): short and best-effort ON PURPOSE — this must never become the reason
# a click/type action is slow. A failure/timeout here just omits the
# coordinates; it never delays or fails the actual action (see
# `_capture_action_point`).
_ACTION_POINT_TIMEOUT_MS = int(os.environ.get("IRIS_VISION_ACTION_POINT_TIMEOUT_MS", "1500"))


class SessionBudgetExceeded(RuntimeError):
    """Raised by ``act()`` when the session's action or wall-clock bound is hit.

    The session is still alive after this is raised; the caller is expected to
    close it in a finally. Carries the state at raise time for REQ-16 AC3
    (vision session terminal cause instrumentation).
    """

    def __init__(self, message: str, actions_taken: int = 0, elapsed_ms: int = 0) -> None:
        super().__init__(message)
        self.actions_taken = actions_taken
        self.elapsed_ms = elapsed_ms


@dataclass
class SessionBounds:
    """Configurable bounds for one vision session (REQ-7 AC4).

    ``max_extractions`` is the REQ-17 AC8 per-URL extraction bound owned by the
    frame-extraction module; it lives here so a single bounds object travels
    with the session.
    """

    max_actions: int = 12
    max_wall_ms: int = 60_000
    max_extractions: int = 8


@dataclass
class VisionAction:
    """One action the vision model asked the session to perform.

    ``target`` is a CSS selector (or NL description the vision loop resolves
    before emitting — this module executes, it does not resolve). ``reason`` is
    the model's stated justification, carried for REQ-16.
    """

    kind: Literal["navigate", "reload", "back", "forward", "scroll", "click", "type", "wait"]
    target: Optional[str] = None
    value: Optional[str] = None
    reason: str = ""


class WallKind(str, Enum):
    """Kinds of wall a vision session may hit (REQ-7 detection heuristics).

    Defined locally (not imported from ``backend.crawler.capabilities``) so
    this module has no dependency on a module that may not exist yet.
    """

    CAPTCHA = "captcha"
    LOGIN = "login"
    PAYWALL = "paywall"
    UNKNOWN = "unknown"


# ── Wall-detection heuristics (pure DOM, no network, no VLM) ───────────────

_CAPTCHA_STRUCTURAL = [
    # iframe[src*="challenge"]
    re.compile(r"<iframe[^>]*\bsrc=([\"'])[^\"']*challenge", re.IGNORECASE),
    # div[id*="captcha"]
    re.compile(r"<div[^>]*\bid=([\"'])[^\"']*captcha", re.IGNORECASE),
    # input[name*="captcha"]
    re.compile(r"<input[^>]*\bname=([\"'])[^\"']*captcha", re.IGNORECASE),
    # #cf-turnstile (id form, as the spec writes it)
    re.compile(r"id=([\"'])cf-turnstile\1", re.IGNORECASE),
    # .cf-turnstile (the class form Cloudflare actually emits)
    re.compile(r"class=([\"'])[^\"']*cf-turnstile[^\"']*\1", re.IGNORECASE),
    # [class*="g-recaptcha"]
    re.compile(r"class=([\"'])[^\"']*g-recaptcha", re.IGNORECASE),
]

_CAPTCHA_TEXT = ("verify you are human", "just a moment")
_LOGIN_TEXT = ("sign in", "log in")          # checked in first 2000 chars of visible text
_PAYWALL_TEXT = ("subscribe to read", "premium", "sign up to continue", "paywall")

_PASSWORD_INPUT = re.compile(r"<input[^>]*\btype=([\"'])password\1", re.IGNORECASE)
_TAG_STRIP = re.compile(r"<[^>]+>", re.IGNORECASE)


def _visible_text(html: str) -> str:
    """Strip scripts/styles/tags to a flattened visible-text approximation."""
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = _TAG_STRIP.sub(" ", text)
    return re.sub(r"\s+", " ", text)


def _detect_wall_from_html(html: str) -> Optional[WallKind]:
    """Return the first wall kind matched by DOM heuristics, else None.

    Order is deliberate: CAPTCHA (structural markers first, then known
    interstitial prose), then LOGIN (password field or sign-in copy), then
    PAYWALL copy. First kind matched wins.
    """
    lowered = html.lower()
    for pattern in _CAPTCHA_STRUCTURAL:
        if pattern.search(html):
            return WallKind.CAPTCHA
    for marker in _CAPTCHA_TEXT:
        if marker in lowered:
            return WallKind.CAPTCHA

    if _PASSWORD_INPUT.search(html):
        return WallKind.LOGIN
    visible = _visible_text(html).lower()
    head = visible[:2000]
    for marker in _LOGIN_TEXT:
        if marker in head:
            return WallKind.LOGIN

    for marker in _PAYWALL_TEXT:
        if marker in visible:
            return WallKind.PAYWALL
    return None


def _parse_int(value: Optional[str], default: int) -> int:
    """Parse an int from an action value string; fall back on junk."""
    if value is None:
        return default
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return default


class BrowserSession:
    """One persistent, bounded, server-side browser session for one URL.

    Lifecycle: ``open()`` -> zero or more ``act()`` (driving the vision loop's
    decisions) -> ``settle()``/``detect_wall()`` as needed -> ``close()`` in a
    finally. The session persists across actions (REQ-7 AC1); the iframe mirror
    is fed by frame publishing (REQ-11 AC1).
    """

    def __init__(
        self,
        job_id: str,
        url: str,
        goal: str,
        bounds: Optional[SessionBounds] = None,
    ) -> None:
        self._job_id = job_id
        self.url = url
        self.goal = goal
        self._bounds = bounds or SessionBounds()
        self._actions_taken = 0
        self._page_number = 0
        self._last_published: Optional[str] = None  # T16: rate-bound dedupe
        self._started_at = time.monotonic()
        self._unavailable = False
        self._closed = False
        self._context = None
        self._lease = None
        self._page = None
        # REQ-7 AC6: last action failure surfaced as an observation for the
        # vision model (read by the vision loop; None when the last act passed).
        self.last_error: Optional[str] = None
        # Particle-trail cursor mirror (REQ-16 AC7): best-effort coordinates
        # for the action just performed, read by fetch.vision after act() to
        # fold into the CRAWLER_VISION_ACTION payload. Shape:
        #   click/type -> {"x": 0..1, "y": 0..1, "viewport_w": int, "viewport_h": int}
        #   scroll     -> {"scroll_dx": int, "scroll_dy": int}
        #   everything else -> None (no cursor-relevant point)
        # Never trusted beyond "best effort" — the model has no mouse; these
        # are reconstructed FROM the DOM target's bounding box, never fed back
        # into the crawl. See module docstring / CLAUDE.md safety note.
        self.last_action_point: Optional[dict] = None

    # ── availability / observability ───────────────────────────────────────

    def available(self) -> bool:
        """True when a live page is attached and Playwright was importable."""
        return not self._unavailable and self._page is not None

    @property
    def actions_taken(self) -> int:
        return self._actions_taken

    @property
    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._started_at) * 1000)

    # ── lifecycle ──────────────────────────────────────────────────────────

    async def open(self) -> None:
        """Acquire the POOLED shared Chromium browser, open a fresh isolated
        context + page, navigate to ``url``.

        The Playwright/Chromium process itself lives in ``browser_pool`` and
        is started at most once per process (lazily, on first use across ALL
        sessions) — this eliminates the per-URL cold browser launch that used
        to dominate escalation latency (live evidence 2026-08-10 18:16: one
        websearch escalating 4 URLs paid 4 cold launches). What THIS session
        always gets fresh is a ``browser.new_context()`` — REQUIRED, not
        optional, for cookie/storage isolation (REQ-5 AC2 run-scoped cookie
        semantics; no cross-run identity) — sessions never share one context.

        Any failure to get the pooled browser — Playwright not installed
        (ImportError) OR a hard launch failure (chromium missing, crash) —
        degrades the session to unavailable exactly the same way (REQ-6 AC1
        edge): ``open()`` never raises for a browser-start failure. That is
        deliberately different from the per-session context/navigation
        failures below, which DO close-and-re-raise, because a pool-start
        failure is not this session's fault (every other session shares the
        same fate) and the caller (fetch.vision) already treats
        ``available() is False`` as ``transport_error`` — raising here would
        just make that caller catch what it can already read off ``available()``.
        """
        if self.available():
            return  # idempotent — already open
        from backend.vision import browser_pool

        try:
            browser, lease = await browser_pool.acquire_browser(
                max_lease_ms=self._bounds.max_wall_ms + 30_000,
            )
        except Exception as exc:  # noqa: BLE001 — pool-start failure (import or launch)
            self._unavailable = True
            logger.warning(
                "[browser_session] pooled browser unavailable job=%s url=%s: %s",
                self._job_id, self.url, exc,
            )
            return
        self._lease = lease
        try:
            # Fresh context per session — isolation, never shared (see docstring).
            self._context = await browser.new_context()
            self._page = await self._context.new_page()
            try:
                await self._page.goto(
                    self.url, wait_until="domcontentloaded",
                    timeout=_NAVIGATION_TIMEOUT_MS,
                )
            except Exception as _nav_exc:  # noqa: BLE001
                # A goto TIMEOUT is not an empty page. Playwright leaves the page
                # usable, and a challenge interstitial deliberately keeps network
                # activity alive so `domcontentloaded` may never settle — which is
                # precisely the case this session was escalated to handle. Aborting
                # here discarded the whole point: live 2026-08-10 18:16, four
                # escalations returned transport_error and the panel never showed a
                # single URL change. Continue with whatever rendered; the wall
                # detector and page_is_usable judge the content, and
                # SessionBounds.max_wall_ms remains the real bound.
                logger.info(
                    "[browser_session] nav did not settle job=%s url=%s (%s) — "
                    "continuing with the rendered page",
                    self._job_id, self.url, str(_nav_exc)[:120],
                )
            logger.info(
                "[browser_session] opened job=%s url=%s", self._job_id, self.url
            )
            # REQ-11 AC1: publish the first settled frame (page 1).
            await self._publish_frame()
        except Exception as exc:  # noqa: BLE001 — release and surface loudly
            logger.warning(
                "[browser_session] open failed job=%s url=%s: %s",
                self._job_id, self.url, exc,
            )
            await self.close()
            raise

    async def close(self) -> None:
        """Release the page, context, and lease. Idempotent, never raises.
        Call this in a finally at every public entry so the lease is released
        even when an exception unwinds.

        This does NOT close the shared browser — the browser is owned by
        ``browser_pool`` and stays alive (subject to its own idle watchdog)
        for the NEXT session to reuse. Only what THIS session opened
        (page + context) and its lease are released here.
        """
        if self._closed:
            return
        self._closed = True
        page, context, lease = self._page, self._context, self._lease
        # Detach first so available() is False immediately and a failing close
        # cannot make a stale page look live.
        self._page = self._context = self._lease = None
        if page is not None:
            try:
                await page.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[browser_session] page close failed job=%s: %s", self._job_id, exc)
        if context is not None:
            try:
                await context.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[browser_session] context close failed job=%s: %s", self._job_id, exc)
        if lease is not None:
            try:
                lease.release()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[browser_session] lease release failed job=%s: %s", self._job_id, exc)

    # ── action execution (REQ-7 AC2) ────────────────────────────────────────

    async def act(self, action: VisionAction) -> None:
        """Execute one action, enforcing the action-count and wall-clock bounds.

        Raises :class:`SessionBudgetExceeded` BEFORE executing when the next
        action would exceed ``bounds.max_actions`` or elapsed wall-clock
        exceeds ``bounds.max_wall_ms`` (REQ-7 AC4/AC5). Per-action execution
        failures are recorded on ``last_error`` and do NOT abort the session
        (REQ-7 AC6: reported to the vision model as observation).
        """
        page = self._page
        if page is None:
            raise RuntimeError(
                f"[browser_session] act on closed/unavailable session job={self._job_id}"
            )
        if self._actions_taken >= self._bounds.max_actions:
            raise SessionBudgetExceeded(
                f"[browser_session] action budget exhausted job={self._job_id} "
                f"actions={self._actions_taken} max={self._bounds.max_actions}",
                actions_taken=self._actions_taken,
                elapsed_ms=self.elapsed_ms,
            )
        if self.elapsed_ms > self._bounds.max_wall_ms:
            raise SessionBudgetExceeded(
                f"[browser_session] wall-clock budget exhausted job={self._job_id} "
                f"elapsed_ms={self.elapsed_ms} max_ms={self._bounds.max_wall_ms}",
                actions_taken=self._actions_taken,
                elapsed_ms=self.elapsed_ms,
            )
        self._actions_taken += 1
        # Reset before every action — a stale point from a PRIOR action must
        # never be reported against this one (REQ-16 AC7: no false coords).
        self.last_action_point = None
        try:
            await self._execute(page, action)
        except Exception as exc:  # noqa: BLE001 — REQ-7 AC6: observation, not abort
            self.last_error = f"{action.kind} failed: {exc}"
            logger.warning(
                "[browser_session] action failed job=%s kind=%s target=%s: %s",
                self._job_id, action.kind, action.target, exc,
            )
        else:
            self.last_error = None
            if action.kind == "navigate":
                # REQ-11 AC1: a navigated-away page is a distinct settled frame.
                await self._publish_frame()

    async def _execute(self, page: object, action: VisionAction) -> None:
        kind = action.kind
        if kind == "navigate":
            await page.goto(
                action.target, wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT_MS
            )
        elif kind == "reload":
            await page.reload()
        elif kind == "back":
            await page.go_back()
        elif kind == "forward":
            await page.go_forward()
        elif kind == "scroll":
            delta = _parse_int(action.value, default=800)
            await page.evaluate(f"window.scrollBy(0, {delta})")
            # Particle-trail cursor mirror (REQ-16 AC7): a scroll has no single
            # point on the page — a point would drift meaninglessly as the
            # content moves under it — so we emit direction/delta instead.
            self.last_action_point = {"scroll_dx": 0, "scroll_dy": delta}
        elif kind == "click":
            if not action.target:
                raise ValueError("click requires a target selector")
            locator = page.locator(action.target)
            # Best-effort BEFORE the click: capture where the cursor mirror
            # should land. Never allowed to slow or fail the click itself.
            await self._capture_action_point(page, locator)
            await locator.click(timeout=_ACTION_TIMEOUT_MS)
        elif kind == "type":
            if not action.target:
                raise ValueError("type requires a target selector")
            locator = page.locator(action.target)
            await self._capture_action_point(page, locator)
            await locator.fill(action.value or "")
        elif kind == "wait":
            ms = _parse_int(action.value, default=500)
            await page.wait_for_timeout(ms)
        else:
            raise ValueError(f"unknown action kind: {kind}")

    async def _capture_action_point(self, page: object, locator: object) -> None:
        """Best-effort centre point of ``locator``, normalised to viewport
        fractions, for the frontend particle-trail cursor mirror (REQ-16 AC7).

        SAFETY: this is a MIRROR concern, not a model concern (see module
        docstring) — the vision model still has no mouse; nothing here is fed
        back into the click/type action, and a failure never blocks it. The
        panel scales the captured frame to whatever size it renders at, so raw
        pixel coordinates would misplace the cursor at any size other than the
        one they were captured at — normalised fractions plus the viewport
        size are what let the panel place the cursor correctly regardless.
        """
        try:
            box = await locator.bounding_box(timeout=_ACTION_POINT_TIMEOUT_MS)
            viewport = page.viewport_size
            if not box or not viewport:
                return
            width = viewport.get("width") or 0
            height = viewport.get("height") or 0
            if width <= 0 or height <= 0:
                return
            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2
            self.last_action_point = {
                "x": cx / width,
                "y": cy / height,
                "viewport_w": width,
                "viewport_h": height,
            }
        except Exception as exc:  # noqa: BLE001 — REQ-16 AC7: off the critical
            # path. A missing/slow bounding box just omits the cursor point;
            # the click/type action this is attached to is unaffected.
            logger.debug(
                "[browser_session] action point capture failed job=%s: %s",
                self._job_id, exc,
            )

    # ── frames / walls / settle (REQ-9 AC1, REQ-7 wall detection) ──────────

    async def current_frame(self) -> str:
        """Return the page's full HTML (``page.content()``). Empty on a
        closed/crashed session — never raises (the vision loop treats an empty
        frame as an unusable page)."""
        if self._page is None:
            return ""
        try:
            return await self._page.content()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[browser_session] current_frame failed job=%s: %s", self._job_id, exc)
            return ""

    async def screenshot(self) -> Optional[bytes]:
        """PNG screenshot of the BROWSER page (REQ-9 AC2: browser-scoped frame
        capture, never the desktop). The vision loop feeds this to the VLM for
        action suggestion / triage. None on a closed session — never raises."""
        if self._page is None:
            return None
        try:
            return await self._page.screenshot(type="png")
        except Exception as exc:  # noqa: BLE001 — a lost frame degrades the loop, not the page
            logger.warning("[browser_session] screenshot failed job=%s: %s", self._job_id, exc)
            return None

    async def settle(self, max_actions: Optional[int] = None) -> str:
        """Return the settled DOM after the vision loop's actions, publishing
        it as the next page number (REQ-11 AC1).

        ``max_actions`` is accepted for interface parity with design.md — this
        module never generates actions (the vision loop drives them via
        ``act()``); the parameter bounds that loop, not this capture. Waits
        best-effort for network idle so lazy-loaded content is included; a page
        that never quietens is captured as-is (REQ-11 AC5: never block).
        """
        if self._page is None:
            return ""
        try:
            await self._page.wait_for_load_state("networkidle", timeout=3_000)
        except Exception:  # noqa: BLE001 — page keeps polling; capture anyway
            pass
        return await self._publish_frame()

    async def detect_wall(self) -> Optional[WallKind]:
        """Heuristic wall detection on the CURRENT DOM (REQ-7). Returns the
        first kind matched — CAPTCHA, LOGIN, PAYWALL — or None. Pure DOM, no
        network, no VLM."""
        html = await self.current_frame()
        if not html:
            return None
        return _detect_wall_from_html(html)

    # ── frame publishing (REQ-11 AC1 / AC5) ────────────────────────────────

    async def _publish_frame(self) -> str:
        """Best-effort save of the current frame to the capture store with an
        incrementing page number. Never raises (REQ-11 AC5): a store failure
        degrades the panel to its existing 'capture unavailable' state.

        Rate-bounded (REQ-11 AC5 / T16): only structurally DIFFERENT frames
        are published — an identical DOM (e.g. a settle after a no-op action)
        is skipped, so a 12-action session writes at most ~12 distinct frames.
        """
        html = await self.current_frame()
        if not html:
            return html
        # T16: skip exact-duplicate frames (same DOM, same job) — the capture
        # store keeps one page per distinct state, not one per action.
        if self._last_published == html:
            logger.debug(
                "[browser_session] frame dedupe job=%s page=%s (T16 rate-bound)",
                self._job_id, self._page_number,
            )
            return html
        self._page_number += 1
        try:
            get_capture_store().save(self._job_id, self._page_number, self.url, html)
            self._last_published = html
        except Exception as exc:  # noqa: BLE001 — publication is off the hot path
            logger.warning(
                "[browser_session] frame publish failed job=%s page=%s: %s",
                self._job_id, self._page_number, exc,
            )
        return html


__all__ = [
    "BrowserSession",
    "SessionBounds",
    "SessionBudgetExceeded",
    "VisionAction",
    "WallKind",
]
