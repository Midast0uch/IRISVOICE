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

import asyncio
import logging
import os
import random
import re
import time
from enum import Enum
from typing import Any, Awaitable, Callable, Literal, Optional
from dataclasses import dataclass

from backend.crawler.capture_store import CAPTURE_SLOT_STRIDE, get_capture_store
from backend.vision.stage_timing import StageTimer, record_stage

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

# ── Goal-directed machine-speed upgrades (vision-goal-directed-search T8) ──
# Micro-settle after instant teleports: window.scrollBy applies synchronously,
# but lazy-loaded DOM assets need a beat to hydrate (REQ-4 AC4.3). Bounded and
# env-overridable; the session stays machine-speed (no animation loops).
_MICRO_SETTLE_MS = int(os.environ.get("IRIS_VISION_MICRO_SETTLE_MS", "150"))
# Overlay dismissal locators, tried in order after Escape (REQ-5 AC5.2).
DISMISS_SELECTORS = (
    "button:has-text('Accept')",
    "button:has-text('I Agree')",
    "button:has-text('Close')",
    "[aria-label='Close']",
    "[data-testid*='close']",
)
_DISMISS_CLICK_TIMEOUT_MS = 1500
# Persistent-but-non-essential backdrop/cookie containers, hidden as a last
# resort when no dismissal control answers (REQ-5 AC5.2 step 3).
_OVERLAY_HIDE_JS = (
    "document.querySelectorAll('.modal-backdrop, [class*=\"overlay\"],"
    " [class*=\"cookie\"]').forEach(el => { el.style.display = 'none'; });"
)
# OS-keyring service + account scheme for session-cookie injection (REQ-12).
_KEYRING_SERVICE = "iris_voice_sessions"
# Playwright reports an intercepted click as an actionability TimeoutError
# whose message names the interception (there is no dedicated
# ElementClickInterceptedError type in the Python binding).
_CLICK_INTERCEPTED_MARK = "intercepts pointer events"
# Popup adoption settle budget (REQ-6 AC6.2): adopt fast, never stall the loop.
_POPUP_SETTLE_TIMEOUT_MS = 5_000

# ── Interactive control (browser_observe / browser_act) ─────────────────────
# Set-of-Marks cap: the model reads the list, so it stays short. In-viewport
# elements come first, so the cap drops the far-off-screen tail, not the page.
_MAX_MARKS = 60
# How long the overlay gets to glide to the target between the `approach` event
# and the real input (REQ-5 AC5.1). Matches the overlay's compressed transit.
_APPROACH_MS = int(os.environ.get("IRIS_BROWSER_APPROACH_MS", "180"))
# Per-key delay bounds while typing (REQ-4 AC4.3): human-paced, never instant.
_KEY_DELAY_MIN_S = 0.030
_KEY_DELAY_MAX_S = 0.090
# Typing is paced per key, so its wall time is len(text) * ~60 ms. Bounded.
_MAX_TYPE_CHARS = 400
_INTERACT_ACTIONS = ("click", "type", "select", "scroll", "back", "press")
# Collects every visible interactive element, tags it `data-iris-mark=<id>` so
# the act step can re-find the SAME node, and returns [{id, role, name, tag,
# x, y, w, h, in_view, disabled, +href/type/download/form when present}] plus a
# short visible-text digest. Order: the
# elements on screen in document order, then the rest in document order; ids
# are 1..N in that order. Hidden, zero-size and off-document nodes are skipped.
# (Open shadow roots and cross-origin iframes are not entered.)
_OBSERVE_JS = r"""
(cap) => {
  document.querySelectorAll('[data-iris-mark]').forEach(e => e.removeAttribute('data-iris-mark'));
  const SEL = 'a[href], button, input:not([type=hidden]), select, textarea, summary, ' +
    '[role=button], [role=link], [role=checkbox], [role=radio], [role=tab], [role=menuitem], ' +
    '[role=switch], [role=option], [onclick], [contenteditable=""], [contenteditable="true"]';
  const vw = window.innerWidth, vh = window.innerHeight;
  const docW = Math.max(document.documentElement.scrollWidth, vw);
  const sx = window.scrollX || 0, sy = window.scrollY || 0;
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const clip = (s) => (s.length > 80 ? s.slice(0, 77) + '...' : s);
  const nameOf = (el) => {
    const tag = el.tagName.toLowerCase();
    let n = el.getAttribute('aria-label');
    if (!n) {
      const lb = el.getAttribute('aria-labelledby');
      if (lb) n = lb.split(/\s+/).map(i => { const r = document.getElementById(i); return r ? r.textContent : ''; }).join(' ');
    }
    if (!n && el.labels && el.labels.length) n = Array.from(el.labels).map(l => l.textContent).join(' ');
    if (!n && tag === 'input') {
      const t = (el.type || '').toLowerCase();
      n = (t === 'submit' || t === 'button' || t === 'reset') ? (el.value || t) : (el.placeholder || el.title || el.name || '');
    }
    if (!n && tag === 'textarea') n = el.placeholder || el.title || el.name || '';
    if (!n && tag !== 'select') n = el.innerText || el.textContent || '';
    if (!n) { const im = el.querySelector('img[alt]'); if (im) n = im.getAttribute('alt'); }
    if (!n) n = el.getAttribute('title') || el.getAttribute('alt') || el.getAttribute('name') || '';
    return clip(clean(n));
  };
  const roleOf = (el) => {
    const r = el.getAttribute('role');
    if (r) return r;
    const tag = el.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'button' || tag === 'summary') return 'button';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      const t = (el.type || 'text').toLowerCase();
      if (t === 'checkbox' || t === 'radio') return t;
      if (t === 'submit' || t === 'button' || t === 'reset' || t === 'image') return 'button';
      if (t === 'search') return 'searchbox';
      if (t === 'range') return 'slider';
      return 'textbox';
    }
    if (el.isContentEditable) return 'textbox';
    return 'button';
  };
  // What the click-safety gate reads (W2): where a link goes, the input type, and
  // what the enclosing form collects ("type:autocomplete:name" per field).
  const formOf = (el) => {
    const f = el.form || el.closest('form');
    if (!f) return null;
    const fields = [];
    f.querySelectorAll('input:not([type=hidden]), select, textarea').forEach(c => {
      if (fields.length >= 12) return;
      fields.push([(c.type || c.tagName).toLowerCase(), (c.getAttribute('autocomplete') || '').toLowerCase(),
                   (c.name || c.id || '').toLowerCase().slice(0, 30)].join(':'));
    });
    return { fields, action: (f.getAttribute('action') || '').slice(0, 200) };
  };
  const inView = [], offView = [];
  document.querySelectorAll(SEL).forEach(el => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return;
    if (r.right + sx <= 0 || r.bottom + sy <= 0 || r.left + sx >= docW) return;
    const visible = r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
    (visible ? inView : offView).push([el, r, visible]);
  });
  const picked = inView.concat(offView).slice(0, cap);
  const marks = picked.map(([el, r, visible], i) => {
    const id = i + 1;
    el.setAttribute('data-iris-mark', String(id));
    const mark = {
      id, role: roleOf(el), name: nameOf(el), tag: el.tagName.toLowerCase(),
      x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
      in_view: visible, disabled: !!el.disabled,
    };
    const href = el.tagName === 'A' ? (el.href || '') : (el.getAttribute('formaction') || '');
    if (href) mark.href = href.slice(0, 300);
    const itype = (el.getAttribute('type') || '').toLowerCase();
    if (itype) mark.type = itype;
    if (el.hasAttribute('download')) mark.download = true;
    const form = formOf(el);
    if (form) mark.form = form;
    return mark;
  });
  const digest = clean(document.body ? document.body.innerText : '').slice(0, 600);
  return { marks, digest, vw, vh, title: document.title || '' };
}
"""
# True when nothing paints over the element's centre (an overlay would eat the click).
_HIT_TEST_JS = r"""
(el) => {
  const r = el.getBoundingClientRect();
  const t = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
  return !t || t === el || el.contains(t) || t.contains(el);
}
"""

# Session-331 (live T2): a realistic desktop UA. The Playwright default
# advertises "HeadlessChrome/<ver>", which Bing detects and answers with a JS
# challenge (no search box, empty body) that search_discovery misread as a login
# wall. A normal UA gets the real results page. Overridable for other sites.
_IRIS_BROWSER_UA = os.environ.get(
    "IRIS_BROWSER_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
)


def _context_options() -> dict:
    """Browser-context options for every vision session (session-331).

    Sets the realistic UA + a common viewport/locale so the headless Chromium is
    not trivially fingerprinted as a bot. This is presentation, not
    CAPTCHA-solving (REQ-19 AC5): a genuine challenge/login wall is still
    detected and parked by the wall detector. Never raises.
    """
    return {
        "user_agent": _IRIS_BROWSER_UA,
        "viewport": {"width": 1366, "height": 768},
        "locale": "en-US",
    }


async def _new_context(browser, **extra) -> object:
    """Create a context with the session-331 options, tolerating doubles.

    Real Playwright's ``browser.new_context(**options)`` accepts the UA /
    viewport / locale. Test doubles and alternate browser objects may not — so
    if the optioned call fails with a TypeError (unexpected kwarg), retry with
    no options. Never masks a real launch failure: any non-TypeError propagates.
    """
    opts = _context_options()
    opts.update(extra)
    try:
        return await browser.new_context(**opts)
    except TypeError:
        return await browser.new_context()


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

    kind: Literal[
        "navigate", "reload", "back", "forward", "scroll",
        "click", "type", "press", "wait",
    ]
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


def _host_of(url: str) -> str:
    """Lowercased netloc of a URL, "" when unparseable (never raises)."""
    try:
        from urllib.parse import urlparse
        return (urlparse(url or "").netloc or "").lower()
    except Exception:  # noqa: BLE001
        return ""


# REQ-2 AC1/AC4 (T8): the role+name vocabulary the model is asked to use
# matches `backend/vision/action_allowlist.py`. These helpers turn a
# description-only target ("button \"Sign in\"", "link 'Home'",
# "textbox 'Search'") into bounded, executor-resolvable CSS candidates. Kept
# as module-level pure functions so the resolution step is unit-testable
# without a browser.
_ROLE_TO_CSS = {
    "button": "button",
    "link": "a",
    "textbox": "input, textarea",
    "combobox": "select",
    "searchbox": "input[type='search'], input[name='q'], textarea[name='q']",
    "checkbox": "input[type='checkbox']",
    "radio": "input[type='radio']",
    "tab": "[role='tab']",
    "menuitem": "[role='menuitem']",
    "heading": "h1, h2, h3, h4, h5, h6",
}
_ROLE_NAME_RE = re.compile(
    r"^\s*(?P<role>[a-zA-Z]+)\s*[\"'`](?P<name>.+?)[\"'`]\s*$"
)


def _parse_role_name(target: str) -> "tuple[str, str] | None":
    """Parse a ``role "name"`` description into (role, name), else None.

    Accepts single, double, or backtick quoting around the accessible name.
    Returns None for anything that is not a role+name description (a bare CSS
    selector, or free prose), so the caller falls straight through to treating
    it as a selector.
    """
    try:
        m = _ROLE_NAME_RE.match(target or "")
        if not m:
            return None
        role = m.group("role").strip().lower()
        name = m.group("name").strip()
        if not name:
            return None
        return role, name
    except Exception:  # noqa: BLE001
        return None


def _role_name_selectors(role: str, name: str) -> "list[str]":
    """Bounded CSS candidates for a role+name target (REQ-2 AC4).

    Prefers Playwright's own role/name engine when available, then falls back
    to attribute/`:has-text` selectors derived from the allowlist vocabulary.
    The list is deliberately SHORT (a bounded resolution step, not a crawl).
    """
    _base = _ROLE_TO_CSS.get(role)
    candidates: "list[str]" = []
    if _base:
        # `:has-text` matches the element whose text contains the name — the
        # cheapest executor-side resolution for a button/link by label.
        for tag in [t.strip() for t in _base.split(",")]:
            candidates.append(f"{tag}:has-text(\"{name}\")")
            candidates.append(f"{tag}[aria-label=\"{name}\"]")
    # Generic accessible-name fallbacks, bounded to two.
    candidates.append(f"[aria-label=\"{name}\"]")
    candidates.append(f"[title=\"{name}\"]")
    return candidates


def _draw_marks(png: bytes, marks: "list[dict]") -> Optional[bytes]:
    """Draw each mark's number on a viewport screenshot; JPEG bytes (small enough
    to ride in a tool result). None when Pillow is missing or the image is bad —
    the text marks alone still answer, so this never raises."""
    try:
        import io
        from PIL import Image, ImageDraw  # lazy: only when a vision model is live

        img = Image.open(io.BytesIO(png)).convert("RGB")
        draw = ImageDraw.Draw(img)
        for m in marks:
            x, y, w, h = m["x"], m["y"], m["w"], m["h"]
            label = str(m["id"])
            draw.rectangle([x, y, x + w, y + h], outline=(255, 0, 80), width=2)
            tw = 7 * len(label) + 6
            draw.rectangle([x, y, x + tw, y + 14], fill=(255, 0, 80))
            draw.text((x + 3, y + 1), label, fill=(255, 255, 255))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=70)
        return out.getvalue()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[browser_session] draw marks failed: %s", exc)
        return None


def _keyring_read(host: str) -> Optional[str]:
    """Blocking keyring read (call through asyncio.to_thread). None when the
    keyring lib or backend is missing."""
    try:
        import keyring as _keyring
    except Exception:  # noqa: BLE001 — no keyring lib means anonymous
        return None
    return _keyring.get_password(_KEYRING_SERVICE, host)


def warm_keyring() -> None:
    """Pay keyring's import + backend discovery now, on the caller's thread
    (the web toggle runs it on a daemon thread). Never raises."""
    try:
        import keyring as _keyring

        _keyring.get_keyring()
    except Exception:  # noqa: BLE001
        pass


async def _inject_keyring_cookies(context: object, url: str, job_id: str) -> int:
    """Inject OS-keyring session cookies into a fresh context (REQ-12 AC12.1/12.2).

    Returns the injected cookie COUNT (never logs names, values, or the raw
    JSON — session tokens must not appear in logs). Zero when keyring is
    unavailable, holds nothing for the domain, or the payload is malformed.
    Never raises: anonymous browsing is the safe fallback.
    """
    import json as _json

    try:
        host = _host_of(url)
        if not host:
            return 0
        # OFF the browser host loop: the first `import keyring` + backend
        # discovery measured 9.5 s (4.0 + 5.6, 2026-10-02) and blocked EVERY
        # browser operation on that loop - the first open of a backend
        # process took 86 s with a warm Chromium.
        raw = await asyncio.to_thread(_keyring_read, host)
        if not raw:
            return 0
        cookies = _json.loads(raw)
        if not isinstance(cookies, list):
            return 0
        clean = [c for c in cookies
                 if isinstance(c, dict) and c.get("name") and c.get("value")]
        if not clean:
            return 0
        add = getattr(context, "add_cookies", None)
        if not callable(add):
            return 0
        await add(clean)
        logger.info(
            "[browser_session] injected %d keyring cookies job=%s domain=%s",
            len(clean), job_id, host,
        )
        return len(clean)
    except Exception as exc:  # noqa: BLE001 — anonymous fallback, values never logged
        logger.debug("[browser_session] keyring cookie injection skipped job=%s: %s",
                     job_id, type(exc).__name__)
        return 0


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
        page_offset: int = 0,
        acquire: Optional[Callable[..., Awaitable[Any]]] = None,
    ) -> None:
        self._job_id = job_id
        # Where open() gets its (browser, lease) from. None = the shared pool
        # (every crawl/vision session). The interactive browser_* tools pass
        # their own source: their session outlives one tool call, and the
        # pool's Chromium is bound to the event loop that started it — a
        # long-lived session on another loop hangs the pool's next user.
        self._acquire = acquire
        self.url = url
        self.goal = goal
        self._bounds = bounds or SessionBounds()
        self._actions_taken = 0
        # Capture addresses for this session's published frames. Without an
        # offset every session numbered from 1 into the SHARED job directory, so
        # an escalation on URL 4 overwrote URLs 1-3's captured pages and the panel
        # served the wrong page's bytes as evidence.
        #
        # With a reservation, the crawl page for the same URL owns offset+1, so
        # frames begin at offset+2. WITHOUT one (offset 0) there is no crawl page
        # to step over and the first frame must still be page 1 exactly as
        # before — this is the unreserved path the open()/settle() contract tests
        # pin, and starting it at 2 broke both.
        self._page_offset = max(0, int(page_offset))
        self._page_number = self._page_offset + 1 if self._page_offset else 0
        self._last_published: Optional[str] = None  # T16: rate-bound dedupe
        # REQ-8 AC2 (T4): counts that reveal waste, scoped to this session's
        # run id. `screenshots` (per-settled-state redundancy) and the
        # published/skipped split on _publish_frame are the two the audit
        # named. Never read for control flow — observability only.
        self._screenshots_taken = 0
        self._frames_published = 0
        self._frames_skipped = 0
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
        # Overlay-dismissal record (REQ-5 AC5.3): description of the last
        # auto-dismissed modal/banner, or None. The vision loop folds this
        # into the ActionTrajectory as `dismissed_overlay`.
        self.last_dismissal: Optional[str] = None
        # Adopted popup URLs awaiting pickup (REQ-6 AC6.2 step 5): the session
        # adopts the page + publishes its frame; the vision loop drains this
        # queue to emit CRAWLER_PAGE_FETCHED (emission stays the loop's job).
        self._adopted_popup_urls: list = []
        # Set-of-Marks state for the interactive tools (observe() writes,
        # interact() reads). `marks_seq` bumps on every observe so a caller can
        # tell that an old numbering is gone. One lock per page (REQ-4 AC4.5):
        # observe and interact never overlap on the same page.
        self.last_marks: list = []
        self.marks_seq = 0
        self._action_lock = asyncio.Lock()
        # Run-scoped monotonic sequence for CRAWLER_VISION_ACTION events the
        # overlay de-duplicates by (run_id, seq) — approach and done each take one.
        self._event_seq = 0

    # ── availability / observability ───────────────────────────────────────

    def available(self) -> bool:
        """True when a live page is attached and Playwright was importable.

        A page that was CLOSED or CRASHED is not available (live 2026-10-02,
        run A5: the page closed mid-task, browser_open then answered "ok" on
        the dead page in 12-36 ms and every observe failed, so the agent fell
        back to curl). Unavailable -> browser_open starts a fresh session.
        """
        if self._unavailable or self._page is None:
            return False
        try:
            if self._page.is_closed():
                return False
        except Exception:  # noqa: BLE001 — a stand-in page without is_closed
            pass
        return True

    def _watch_page(self, page) -> None:
        """Log why a page goes away (close / crash) and the browser's
        disconnect, so the next stall names its cause. Never raises."""
        on = getattr(page, "on", None)
        if not callable(on):
            return
        job = self._job_id

        def _closed(_p=None):
            logger.warning("[browser_session] page CLOSED job=%s url=%s", job, self.url)

        def _crashed(_p=None):
            logger.warning("[browser_session] page CRASHED (renderer died) job=%s url=%s", job, self.url)
            self._unavailable = True

        try:
            on("close", _closed)
            on("crash", _crashed)
            ctx = getattr(page, "context", None)
            browser = getattr(ctx, "browser", None) if ctx is not None else None
            b_on = getattr(browser, "on", None)
            if callable(b_on):
                b_on("disconnected", lambda _b=None: logger.warning(
                    "[browser_session] browser DISCONNECTED job=%s", job))
        except Exception as exc:  # noqa: BLE001
            logger.debug("[browser_session] page watch not installed job=%s: %s", job, exc)

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

        # REQ-8 AC1 (T4): time the browser ACQUIRE separately from the session
        # work. acquire_browser() may cold-launch Chromium (~33s measured) and
        # that is infrastructure, not browsing — the split is what makes the
        # cold/warm cost visible without re-measuring.
        _acquire_timer = StageTimer(self._job_id, "acquire")
        _acquire_fn = self._acquire or browser_pool.acquire_browser
        try:
            browser, lease = await _acquire_fn(
                max_lease_ms=self._bounds.max_wall_ms + 30_000,
            )
        except Exception as exc:  # noqa: BLE001 — pool-start failure (import or launch)
            self._unavailable = True
            logger.warning(
                "[browser_session] pooled browser unavailable job=%s url=%s: %s",
                self._job_id, self.url, exc,
            )
            return
        _acquire_ms = _acquire_timer.record()

        # The wall-clock budget starts HERE, not in __init__.
        #
        # acquire_browser() above may have to start the pooled Chromium, and on
        # a cold pool that is a one-off infrastructure cost with nothing to do
        # with how long this session spends BROWSING. Billing it to the budget
        # made the first search after any idle-stop fail by construction:
        # measured elapsed_ms=76495 against max_ms=30000, killed before it could
        # produce a single candidate url, so crawler_query reported "no
        # candidate urls" and the whole run failed with no page events — which
        # also left the crawl animations with nothing to draw.
        #
        # The 30s bound is UNCHANGED. What changed is that it now measures the
        # session's own work, which is what a per-session budget is for. The
        # pool's idle watchdog stops the browser a few minutes after use, so
        # this path is hit routinely, not just on the first run after a restart.
        acquire_ms = int((time.monotonic() - self._started_at) * 1000)
        if acquire_ms > 1_000:
            logger.info(
                "[browser_session] browser acquired in %dms (cold pool) job=%s — "
                "budget clock starts now",
                acquire_ms, self._job_id,
            )
        # REQ-18 AC1/AC3 (T20): record the acquire's COLD/WARM classification
        # scoped to THIS run id, so the per-run split is visible without
        # re-measuring. The launch is NOT charged to the action budget — the
        # budget clock is reset below (after acquire), which is the existing
        # "cold launch is infrastructure, not browsing" behavior REQ-18 AC3
        # requires.
        try:
            _cold = browser_pool.last_acquire_was_cold()
            record_stage(
                self._job_id, "browser_acquire_class",
                _acquire_ms, cold=_cold, warm=not _cold,
            )
        except Exception:  # noqa: BLE001 — accounting is off the critical path
            pass
        # REQ-18 AC1 (T20) will classify cold/warm; here (T4) we only record the
        # acquire duration so the split is measurable per run id.
        record_stage(self._job_id, "open", _acquire_ms)
        self._started_at = time.monotonic()
        self._lease = lease
        try:
            # Fresh context per session — isolation, never shared (see docstring).
            #
            # Session-331 (live T2): the pooled Chromium can be a CORPSE — its
            # transport died (e.g. after a login wall) but acquire_browser's
            # is_connected() pre-check missed it, so new_context() raises
            # "'NoneType' object has no attribute 'send'". Detect that signature,
            # force-reset the pool, re-acquire, and retry ONCE. Any other failure
            # falls through to the existing close-and-raise path unchanged.
            # A spare page from the pool (web ON): its renderer already started.
            _spare = None
            if self._acquire is None:
                try:
                    _spare = await browser_pool.take_spare_page()
                except Exception:  # noqa: BLE001 — build our own below
                    _spare = None
            try:
                if _spare is not None:
                    self._context = _spare[0]
                else:
                    self._context = await _new_context(browser)
            except Exception as _ctx_exc:  # noqa: BLE001
                if "no attribute 'send'" not in str(_ctx_exc):
                    raise
                logger.warning(
                    "[browser_session] pooled browser corpse detected job=%s "
                    "(%s) — resetting pool and retrying once",
                    self._job_id, _ctx_exc,
                )
                # A private source owns its own browser and re-launches a dead
                # one inside acquire; resetting the SHARED pool from here would
                # tear down a browser that belongs to another loop.
                if self._acquire is None:
                    try:
                        await browser_pool.reset_browser_pool()
                    except Exception:  # noqa: BLE001 — best-effort reset
                        pass
                try:
                    if self._lease is not None:
                        self._lease.release()
                except Exception:  # noqa: BLE001
                    pass
                browser, lease = await _acquire_fn(
                    max_lease_ms=self._bounds.max_wall_ms + 30_000,
                )
                self._lease = lease
                self._started_at = time.monotonic()
                # REQ-11 AC3: IF the retry ALSO fails THEN the session SHALL
                # mark itself unavailable and degrade — never raise into the
                # run. (A normal, non-corpse context failure still raises below,
                # unchanged.) This is the one place a corpse is expected to be
                # unrecoverable; degrading is the honest outcome.
                try:
                    self._context = await _new_context(browser)
                except Exception as _retry_exc:  # noqa: BLE001
                    self._unavailable = True
                    logger.warning(
                        "[browser_session] corpse retry failed job=%s url=%s (%s) "
                        "— degrading to unavailable (REQ-11 AC3)",
                        self._job_id, self.url, _retry_exc,
                    )
                    await self.close()
                    return
            # REQ-12: private session cookies from the OS keyring, injected
            # before any navigation so authenticated pages settle signed-in.
            # Best-effort: no keyring entry (or no keyring lib) means anonymous.
            _t_ctx = time.monotonic()
            await _inject_keyring_cookies(self._context, self.url, self._job_id)
            _t_cookies = time.monotonic()
            self._page = _spare[1] if _spare is not None else await self._context.new_page()
            self._watch_page(self._page)
            _t_page = time.monotonic()
            # REQ-6: adopt popups/tabs opened by clicks (target="_blank").
            # Guarded getattr: older fakes/pool shims without .on keep working.
            _on_page = getattr(self._context, "on", None)
            if callable(_on_page):
                try:
                    _on_page("page", self._handle_popup_page)
                except Exception as exc:  # noqa: BLE001 — adoption is a bonus
                    logger.debug(
                        "[browser_session] popup listener not registered job=%s: %s",
                        self._job_id, exc,
                    )
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
                    # 600: the Playwright call log says how far it got (committed?
                    # waiting on sub-resources?) - the first-nav stall is open.
                    self._job_id, self.url, " | ".join(str(_nav_exc)[:600].splitlines()),
                )
            _t_nav = time.monotonic()
            # Where an open's time goes (2026-10-02: 86 s with a warm browser).
            logger.info(
                "[browser_session] opened job=%s url=%s context_ms=%d cookies_ms=%d "
                "page_ms=%d nav_ms=%d spare=%s", self._job_id, self.url,
                int((_t_ctx - self._started_at) * 1000), int((_t_cookies - _t_ctx) * 1000),
                int((_t_page - _t_cookies) * 1000), int((_t_nav - _t_page) * 1000),
                _spare is not None,
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

    # ── popup auto-adoption (REQ-6 AC6.1/AC6.2) ─────────────────────────────

    def pop_adopted_pages(self) -> list:
        """Drain adopted popup URLs for CRAWLER_PAGE_FETCHED emission.

        The session adopts + publishes; emitting stays the vision loop's job.
        """
        adopted, self._adopted_popup_urls = self._adopted_popup_urls, []
        return adopted

    def _handle_popup_page(self, new_page: object) -> None:
        """Sync `context.on("page")` listener: schedule async adoption.

        Playwright calls listeners synchronously, so this only schedules —
        awaiting here would leave a dangling coroutine on real Chromium.
        Never raises (a listener must not break the page that fired it).
        """
        try:
            import asyncio as _asyncio
            _asyncio.get_running_loop().create_task(self._adopt_popup(new_page))
        except Exception as exc:  # noqa: BLE001 — no loop (tests) or closed loop
            logger.debug(
                "[browser_session] popup adopt not scheduled job=%s: %s",
                self._job_id, exc,
            )

    async def _adopt_popup(self, new_page: object) -> None:
        """Adopt a popup as the live page (REQ-6 AC6.2). Never raises."""
        try:
            if self._closed or new_page is None:
                return
            try:
                await new_page.wait_for_load_state(
                    "domcontentloaded", timeout=_POPUP_SETTLE_TIMEOUT_MS
                )
            except Exception:  # noqa: BLE001 — adopt whatever rendered
                pass
            try:
                _new_url = str(getattr(new_page, "url", "") or "")
            except Exception:  # noqa: BLE001
                _new_url = ""
            old_page = self._page
            try:
                _old_url = str(getattr(old_page, "url", "") or "") if old_page is not None else ""
            except Exception:  # noqa: BLE001
                _old_url = ""
            # Close the prior tab only for external bounces/auth redirects;
            # same-host popups stay open in the context (bounded by its close).
            if old_page is not None and old_page is not new_page and _new_url:
                if _host_of(_new_url) and _host_of(_new_url) != _host_of(_old_url or self.url):
                    try:
                        await old_page.close()
                    except Exception:  # noqa: BLE001 — best effort
                        pass
            self._page = new_page
            if _new_url:
                self.url = _new_url
                self._adopted_popup_urls.append(_new_url)
            await self._publish_frame()
            logger.info(
                "[browser_session] adopted popup job=%s url=%s",
                self._job_id, _new_url,
            )
        except Exception as exc:  # noqa: BLE001 — adoption never breaks the loop
            logger.debug(
                "[browser_session] popup adopt failed job=%s: %s",
                self._job_id, exc,
            )

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
        # REQ-8 AC1 (T4): time the action execution (the DOM round trip).
        _act_t0 = time.monotonic()
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
        finally:
            record_stage(
                self._job_id, "action",
                int((time.monotonic() - _act_t0) * 1000),
                kind=action.kind, index=self._actions_taken,
            )

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
            # Particle-trail cursor mirror (REQ-16 AC7): a scroll has no single
            # point on the page — a point would drift meaninglessly as the
            # content moves under it — so we emit direction/delta instead.
            #
            # The ABSOLUTE position rides along too. The panel mirrors this
            # session into the iframe the user is watching, and a delta cannot
            # be mirrored reliably: the iframe and this page do not start from
            # the same offset, and any dropped or reordered event desynchronises
            # them permanently. An absolute top is self-correcting — every event
            # re-anchors the iframe to where the model actually is.
            #
            # ONE evaluate, not two. The mirror read was originally a second
            # `page.evaluate` issued after the scroll, so every scroll cost two
            # CDP round trips to Chromium. A vision session is scroll-dominated
            # — scroll is its hottest action — and the second trip bought
            # nothing: `window.scrollBy` with the default (instant) behavior
            # applies synchronously, so reading pageYOffset/scrollHeight in the
            # SAME script already observes the post-scroll document. Folding
            # them halves the round trips on that path.
            #
            # The read sits in a JS try/catch (not just the Python one) so the
            # original guarantee survives the fusion: if the mirror read fails,
            # the scroll has still happened and the deltas are still emitted
            # exactly as before — a failed mirror can never cost a scroll.
            # NOT wrapped in try/except: this call now performs the scroll
            # itself, so a failure here is a FAILED SCROLL and must reach
            # act()'s handler as last_error (REQ-7 AC6) rather than be
            # swallowed as a missing mirror reading. The JS try/catch above is
            # what keeps a bad mirror read from throwing in the first place.
            _pos = await page.evaluate(
                "(() => { window.scrollBy(0, %d);"
                " try { return {y: window.pageYOffset"
                " || document.documentElement.scrollTop || 0,"
                " h: Math.max(document.documentElement.scrollHeight,"
                " document.body ? document.body.scrollHeight : 0)}; }"
                " catch (e) { return null; } })()" % delta
            )
            _abs_y: Optional[int] = None
            _doc_h: Optional[int] = None
            if isinstance(_pos, dict):
                try:
                    _abs_y = int(_pos.get("y") or 0)
                    _doc_h = int(_pos.get("h") or 0)
                except Exception:  # noqa: BLE001 — the mirror never costs a scroll
                    pass
            self.last_action_point = {"scroll_dx": 0, "scroll_dy": delta}
            if _abs_y is not None:
                self.last_action_point["scroll_y"] = _abs_y
            if _doc_h:
                self.last_action_point["scroll_height"] = _doc_h
            # REQ-4 AC4.3: micro-settle so lazy-loaded DOM hydrates. Bounded,
            # guarded (older fakes without wait_for_timeout keep working).
            _sleeper = getattr(page, "wait_for_timeout", None)
            if callable(_sleeper):
                try:
                    await _sleeper(_MICRO_SETTLE_MS)
                except Exception:  # noqa: BLE001 — settle never costs a scroll
                    pass
        elif kind == "click":
            if not action.target:
                raise ValueError("click requires a target selector")
            locator = await self._resolve_target(page, action.target)
            # REQ-4 AC4.3: instant teleport onto the element before acting.
            await self._teleport_to(locator)
            # Best-effort BEFORE the click: capture where the cursor mirror
            # should land. Never allowed to slow or fail the click itself.
            await self._capture_action_point(page, locator)
            try:
                await locator.click(timeout=_ACTION_TIMEOUT_MS)
            except Exception as exc:  # noqa: BLE001
                # REQ-5: an intercepted click means a modal/banner is in the
                # way — dismiss and retry ONCE, then let failure surface.
                if _CLICK_INTERCEPTED_MARK not in str(exc):
                    raise
                if await self._dismiss_overlays(page):
                    await locator.click(timeout=_ACTION_TIMEOUT_MS)
                else:
                    raise
        elif kind == "type":
            if not action.target:
                raise ValueError("type requires a target selector")
            locator = await self._resolve_target(page, action.target)
            await self._teleport_to(locator)
            await self._capture_action_point(page, locator)
            # REQ-4 AC4.5: instant fill (native input/change events in ~1ms),
            # never character-by-character typing.
            await locator.fill(action.value or "")
        elif kind == "press":
            # Session-331: press a key on a target (or the page when no target).
            # Search engines change their submit-button markup constantly
            # (measured 2026-09-15: Bing's #sb_form_go / button[type=submit]
            # returned ZERO elements, so the submit click timed out and the
            # query was typed but never submitted). Pressing Enter in the
            # focused search box is markup-independent and always submits.
            key = (action.value or "Enter")
            if action.target:
                locator = await self._resolve_target(page, action.target)
                await self._teleport_to(locator)
                await locator.press(key, timeout=_ACTION_TIMEOUT_MS)
            else:
                await page.keyboard.press(key)
        elif kind == "wait":
            ms = _parse_int(action.value, default=500)
            await page.wait_for_timeout(ms)
        else:
            raise ValueError(f"unknown action kind: {kind}")

    async def _resolve_target(self, page: object, target: str) -> object:
        """Resolve a model-named target to a Playwright locator (REQ-2 AC1/AC4).

        The model is asked for a RESOLVABLE handle (a CSS selector OR a
        role+name). A CSS selector is used directly; a role+name description
        (e.g. ``button "Sign in"`` or ``link "Home"``) is resolved through a
        BOUNDED role/name lookup so a description-only suggestion still has a
        chance before it is treated as unresolvable. Never raises for the
        description path — on failure it returns a locator that will simply not
        match, and the caller's ``act()`` records the miss as a ``last_error``
        observation (REQ-2 AC2), exactly as before.
        """
        # A CSS selector resolves directly (the common, cheap path).
        try:
            _loc = page.locator(target)
            _count = getattr(_loc, "count", None)
            if callable(_count):
                try:
                    if await _count() > 0:
                        return _loc
                except Exception:  # noqa: BLE001 — counting is best-effort
                    return _loc
            else:
                return _loc
        except Exception:  # noqa: BLE001 — fall through to description resolution
            pass
        # REQ-2 AC4: bounded role/name resolution for a description-only target.
        _parsed = _parse_role_name(target)
        if _parsed is not None:
            role, name = _parsed
            for _candidate in _role_name_selectors(role, name):
                try:
                    _loc = page.locator(_candidate)
                    _count = getattr(_loc, "count", None)
                    if callable(_count):
                        if await _count() > 0:
                            logger.info(
                                "[browser_session] resolved description %r -> %s "
                                "job=%s (REQ-2 AC4)",
                                target, _candidate, self._job_id,
                            )
                            return _loc
                    else:
                        return _loc
                except Exception:  # noqa: BLE001 — try the next candidate
                    continue
        # Unresolvable: hand back the raw locator so act() surfaces the miss.
        return page.locator(target)

    async def _teleport_to(self, locator: object) -> None:
        """Instantly bring a target element into view (REQ-4 AC4.3).

        `scroll_into_view_if_needed` aligns immediately with no animation
        loop. Best-effort and guarded: a locator without the method (older
        fakes) or a failure just skips — the click/type that follows raises
        naturally if the element is truly unreachable.
        """
        try:
            _scroll = getattr(locator, "scroll_into_view_if_needed", None)
            if callable(_scroll):
                await _scroll(timeout=_ACTION_TIMEOUT_MS)
        except Exception as exc:  # noqa: BLE001 — teleport never costs the action
            logger.debug(
                "[browser_session] teleport skipped job=%s: %s",
                self._job_id, exc,
            )

    async def _dismiss_overlays(self, page: object) -> bool:
        """Auto-dismiss an intercepting modal/banner, then report (REQ-5).

        Strict sequence per AC5.2: Escape, then each DISMISS_SELECTORS
        control, then hiding persistent backdrops. Returns True when
        something was dismissed (caller retries the action once) and records
        `last_dismissal` for the ActionTrajectory (AC5.3). Never raises.
        """
        self.last_dismissal = None
        try:
            _keyboard = getattr(page, "keyboard", None)
            _press = getattr(_keyboard, "press", None) if _keyboard is not None else None
            if callable(_press):
                try:
                    await _press("Escape")
                except Exception:  # noqa: BLE001 — Escape is step 1 of 3
                    pass
            for selector in DISMISS_SELECTORS:
                try:
                    _locator = page.locator(selector)
                    _first = getattr(_locator, "first", _locator)
                    await _first.click(timeout=_DISMISS_CLICK_TIMEOUT_MS)
                    self.last_dismissal = f"dismissed via {selector!r}"
                    logger.info(
                        "[browser_session] overlay dismissed job=%s via=%s",
                        self._job_id, selector,
                    )
                    return True
                except Exception:  # noqa: BLE001 — next selector
                    continue
            try:
                _evaluate = getattr(page, "evaluate", None)
                if callable(_evaluate):
                    await _evaluate(_OVERLAY_HIDE_JS)
                    self.last_dismissal = "hid persistent overlay/backdrop via JS"
                    logger.info(
                        "[browser_session] overlay hidden via JS job=%s",
                        self._job_id,
                    )
                    return True
            except Exception:  # noqa: BLE001 — nothing worked
                pass
        except Exception as exc:  # noqa: BLE001 — dismissal never breaks the loop
            logger.debug(
                "[browser_session] overlay dismissal failed job=%s: %s",
                self._job_id, exc,
            )
        return False

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

    # ── interactive control: observe / interact / navigate_to (REQ-4, REQ-5) ──
    #
    # These serve the agent-facing browser_* tools. Unlike act() (which runs a
    # vision loop's bounded, selector-resolved, JS-teleport actions and swallows
    # failures into `last_error`), interact() drives REAL mouse and keyboard
    # input at an element's current centre, announces each action to the overlay
    # BEFORE it happens, and RETURNS its outcome — a failed action is never
    # reported as ok.

    def _budget_error(self) -> Optional[str]:
        """Why the session may not take another action, or None."""
        if self._actions_taken >= self._bounds.max_actions:
            return (
                f"action budget exhausted ({self._actions_taken}/"
                f"{self._bounds.max_actions}); call browser_open to start a fresh session"
            )
        if self.elapsed_ms > self._bounds.max_wall_ms:
            return "session time budget exhausted; call browser_open to start a fresh session"
        return None

    def _renew_lease(self) -> None:
        if self._lease is not None:
            try:
                self._lease.renew(self._bounds.max_wall_ms + 30_000)
            except Exception:  # noqa: BLE001 — renewal must never fail an action
                pass

    def _emit_action(
        self, emit: Optional[Callable[[str, dict], None]], phase: str, kind: str,
        index: int, point: Optional[dict] = None, ok: Optional[bool] = None,
        error: str = "", element_id: Optional[int] = None,
    ) -> None:
        """One CRAWLER_VISION_ACTION in the existing shape + `phase`/`ok`/`error`.

        Never raises: a dead or missing frontend must not block the action
        (REQ-5 AC5.4). `seq` is monotonic per session, so the overlay's
        (run_id, seq) de-duplication keeps both halves of the pair.
        """
        if emit is None:
            return
        try:
            self._event_seq += 1
            payload = {
                "run_id": self._job_id, "seq": self._event_seq, "job_id": self._job_id,
                "url": self.url, "kind": kind, "reason": "",
                "action_index": index, "total": self._bounds.max_actions,
                "phase": phase, "escalated": False,
            }
            if point:
                payload.update(point)
            if element_id is not None:
                payload["element_id"] = element_id
            if ok is not None:
                payload["ok"] = ok
                if not ok:
                    payload["error"] = error
            emit("CRAWLER_VISION_ACTION", payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[browser_session] action emit failed job=%s: %s", self._job_id, exc)

    async def _viewport_point(self, page: object, box: Optional[dict] = None) -> dict:
        """Cursor-mirror fields for an action: x/y as 0..1 viewport fractions
        (the hook's contract), viewport size and the absolute scroll position."""
        vp = getattr(page, "viewport_size", None) or {}
        width = int(vp.get("width") or 1366)
        height = int(vp.get("height") or 768)
        point: dict = {"viewport_w": width, "viewport_h": height}
        if box:
            point["x"] = min(1.0, max(0.0, (box["x"] + box["width"] / 2) / width))
            point["y"] = min(1.0, max(0.0, (box["y"] + box["height"] / 2) / height))
        try:
            pos = await page.evaluate(
                "(() => ({y: window.pageYOffset || document.documentElement.scrollTop || 0,"
                " h: Math.max(document.documentElement.scrollHeight,"
                " document.body ? document.body.scrollHeight : 0)}))()"
            )
            if isinstance(pos, dict):
                point["scroll_y"] = int(pos.get("y") or 0)
                point["scroll_height"] = int(pos.get("h") or 0)
        except Exception:  # noqa: BLE001 — the mirror never costs an action
            pass
        return point

    async def _announce_page(
        self, emit: Optional[Callable[[str, dict], None]], force: bool = False,
    ) -> None:
        """Publish the live page to the capture store and tell the panel, so the
        iframe follows the agent within one action (REQ-5 AC5.3). Best-effort.

        ``force`` announces the already-published frame too (open() publishes
        page 1 itself, so a dedupe would otherwise leave the panel unannounced)."""
        page = self._page
        if page is None:
            return
        try:
            _live = str(getattr(page, "url", "") or "")
            if _live.startswith(("http://", "https://")):
                self.url = _live
            before = self._frames_published
            await self._publish_frame()
            if emit is None or self.current_capture_page is None:
                return  # nothing stored: nothing for the panel to show
            if self._frames_published == before and not force:
                return  # unchanged frame (deduped): the panel already has it
            title = ""
            try:
                title = await page.title()
            except Exception:  # noqa: BLE001
                pass
            emit("CRAWLER_PAGE_FETCHED", {
                "url": self.url, "page_number": self._frames_published,
                "total": self._frames_published, "host": _host_of(self.url),
                "title": title, "snippet": "", "job_id": self._job_id,
                "capture_page": self._page_number, "capture_available": True,
            })
        except Exception as exc:  # noqa: BLE001 — publication is off the hot path
            logger.debug("[browser_session] announce failed job=%s: %s", self._job_id, exc)

    async def _page_state(self) -> dict:
        page = self._page
        if page is None:
            return {"url": self.url, "title": ""}
        try:
            title = await page.title()
        except Exception:  # noqa: BLE001
            title = ""
        return {"url": str(getattr(page, "url", "") or self.url), "title": title}

    async def observe(self, marked_screenshot: bool = False) -> dict:
        """Set-of-Marks of the current page (REQ-4 AC4.2).

        Tags every visible interactive element with ``data-iris-mark`` and
        returns ``{ok, url, title, digest, marks, marks_seq, viewport,
        marked_image}``. ``marked_image`` (JPEG bytes with the numbers drawn on)
        is produced only when the caller says a vision model can use it. Never
        raises; ``{"ok": False, "error": ...}`` on failure.
        """
        async with self._action_lock:
            page = self._page
            if page is None:
                return {"ok": False, "error": "browser session is closed; call browser_open"}
            self._renew_lease()
            try:
                data = await page.evaluate(_OBSERVE_JS, _MAX_MARKS)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[browser_session] observe failed job=%s: %s", self._job_id, exc)
                return {"ok": False, "error": f"observe failed: {exc}"[:300]}
            marks = list((data or {}).get("marks") or [])
            self.last_marks = marks
            self.marks_seq += 1
            image: Optional[bytes] = None
            if marked_screenshot:
                try:
                    raw = await page.screenshot(type="png")
                    image = await asyncio.to_thread(
                        _draw_marks, raw, [m for m in marks if m.get("in_view")],
                    )
                except Exception as exc:  # noqa: BLE001 — the text marks still answer
                    logger.debug("[browser_session] marked screenshot failed job=%s: %s",
                                 self._job_id, exc)
            return {
                "ok": True,
                "url": str(getattr(page, "url", "") or self.url),
                "title": str((data or {}).get("title") or ""),
                "digest": str((data or {}).get("digest") or ""),
                "marks": marks,
                "marks_seq": self.marks_seq,
                "viewport": {"w": (data or {}).get("vw"), "h": (data or {}).get("vh")},
                "marked_image": image,
            }

    async def navigate_to(
        self, url: str, emit: Optional[Callable[[str, dict], None]] = None,
    ) -> dict:
        """Navigate the live page (REQ-4 AC4.1 ``browser_open`` on an open
        session) and publish the new page. Returns ``{ok, url, title}`` or
        ``{ok: False, error}``; never raises."""
        async with self._action_lock:
            page = self._page
            if page is None:
                return {"ok": False, "error": "browser session is closed; call browser_open"}
            over = self._budget_error()
            if over:
                return {"ok": False, "error": over}
            self._actions_taken += 1
            self._renew_lease()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT_MS)
            except Exception as exc:  # noqa: BLE001
                # Same rule as open(): a goto TIMEOUT leaves a usable page; a
                # hard network error (DNS, refused) does not.
                if "net::ERR" in str(exc):
                    self.last_error = f"navigate failed: {exc}"
                    return {"ok": False, "error": f"could not load {url}: {str(exc)[:160]}"}
                logger.info("[browser_session] nav did not settle job=%s url=%s (%s)",
                            self._job_id, url, " | ".join(str(exc)[:600].splitlines()))
            self.last_error = None
            self.last_marks = []  # the old numbering belongs to the old page
            await self._announce_page(emit)
            state = await self._page_state()
            return {"ok": True, **state}

    async def interact(
        self, action: str, element_id: Optional[int] = None, text: Optional[str] = None,
        emit: Optional[Callable[[str, dict], None]] = None,
    ) -> dict:
        """One real mouse / keyboard action on the live page (REQ-4 AC4.3-4.5,
        REQ-5 AC5.1-5.3).

        Order is the contract: resolve the element (scroll into view, CURRENT
        box) -> emit ``approach`` with x/y fractions -> wait the overlay travel
        time -> real input -> emit ``done`` with ``ok`` (+ ``error``) -> publish
        a capture when the page changed. An unknown/stale ``element_id`` returns
        ``ok=False`` BEFORE any ``approach`` is emitted. Never raises.
        """
        action = (action or "").strip().lower()
        if action not in _INTERACT_ACTIONS:
            return {"ok": False, "error": f"unknown action {action!r}; use one of "
                    + ", ".join(_INTERACT_ACTIONS)}
        needs_element = action in ("click", "type", "select")
        if needs_element and element_id is None:
            return {"ok": False, "error": f"{action} needs an element_id from browser_observe"}
        if action in ("type", "select") and not (text or ""):
            return {"ok": False, "error": f"{action} needs text"}
        if action == "type" and len(text) > _MAX_TYPE_CHARS:
            return {"ok": False, "error": f"text too long for one type action (max {_MAX_TYPE_CHARS} chars)"}
        if element_id is not None:
            try:
                element_id = int(element_id)
            except (TypeError, ValueError):
                return {"ok": False, "error": f"element_id must be a number, got {element_id!r}"}

        async with self._action_lock:
            page = self._page
            if page is None:
                return {"ok": False, "error": "browser session is closed; call browser_open"}
            over = self._budget_error()
            if over:
                return {"ok": False, "error": over}
            self._renew_lease()

            # 1) Resolve BEFORE announcing: an action that cannot run must not
            #    animate a cursor toward nothing.
            locator = None
            box: Optional[dict] = None
            if element_id is not None:
                locator, box, problem = await self._resolve_mark(page, element_id)
                if problem:
                    return {"ok": False, "error": problem, "marks_seq": self.marks_seq}

            self._actions_taken += 1
            index = self._actions_taken
            _act_t0 = time.monotonic()
            before_url = str(getattr(page, "url", "") or "")
            try:
                before_html = await page.content()
            except Exception:  # noqa: BLE001
                before_html = ""

            # 2) Announce, then give the overlay its glide time.
            point = await self._viewport_point(page, box)
            if action == "scroll" and box is None:
                point["x"], point["y"] = 0.5, 0.5  # the wheel turns at the viewport centre
            self._emit_action(emit, "approach", action, index, point, element_id=element_id)
            await asyncio.sleep(_APPROACH_MS / 1000.0)

            # 3) Real input. Any failure is reported, never swallowed.
            error = ""
            try:
                await self._perform(page, action, locator, box, text)
            except Exception as exc:  # noqa: BLE001
                error = f"{action} failed: {str(exc)[:200]}"
                logger.warning("[browser_session] interact failed job=%s action=%s el=%s: %s",
                               self._job_id, action, element_id, exc)
            self.last_error = error or None

            # 4) Let a triggered navigation/render land, then report.
            try:
                await page.wait_for_timeout(_MICRO_SETTLE_MS)
                await page.wait_for_load_state("domcontentloaded", timeout=2_000)
            except Exception:  # noqa: BLE001 — a page that never quiets is reported as-is
                pass
            page = self._page or page  # a click may have opened an adopted popup
            done_point = await self._viewport_point(page, None)
            done_point.pop("x", None)
            done_point.pop("y", None)
            self._emit_action(emit, "done", action, index, done_point,
                              ok=not error, error=error, element_id=element_id)
            record_stage(self._job_id, "action", int((time.monotonic() - _act_t0) * 1000),
                         kind=action, index=index)

            after_url = str(getattr(page, "url", "") or "")
            try:
                after_html = await page.content()
            except Exception:  # noqa: BLE001
                after_html = before_html
            changed = (after_url != before_url) or (after_html != before_html)
            if changed:
                self.last_marks = [] if after_url != before_url else self.last_marks
                await self._announce_page(emit)
            state = await self._page_state()
            result = {
                "ok": not error, "action": action, "element_id": element_id,
                "changed": changed, "marks_seq": self.marks_seq,
                "capture_page": self.current_capture_page, **state,
            }
            if error:
                result["error"] = error
            return result

    async def _resolve_mark(self, page: object, element_id: int):
        """``(locator, box, problem)`` for a mark id from the LAST observe.

        Scrolls the element into view and reads its CURRENT bounding box (the
        observe-time box is stale after any scroll or reflow). ``problem`` names
        what is wrong (REQ-4 AC4.4) and leaves the agent able to re-observe.
        """
        stale = f"element {element_id} not on page; call browser_observe"
        if not any(m.get("id") == element_id for m in self.last_marks):
            return None, None, stale
        try:
            locator = page.locator(f'[data-iris-mark="{element_id}"]')
            if await locator.count() == 0:
                return None, None, stale
            locator = locator.first
            await locator.scroll_into_view_if_needed(timeout=_ACTION_TIMEOUT_MS)
            box = await locator.bounding_box(timeout=_ACTION_POINT_TIMEOUT_MS)
            if not box or box["width"] <= 0 or box["height"] <= 0:
                return None, None, f"element {element_id} is not visible; call browser_observe"
            if not await locator.evaluate(_HIT_TEST_JS):
                return None, None, (
                    f"element {element_id} is covered by another element (a dialog or "
                    f"overlay); close it first, then call browser_observe"
                )
            return locator, box, ""
        except Exception as exc:  # noqa: BLE001 — a detached node is a stale id
            logger.debug("[browser_session] resolve mark %s failed job=%s: %s",
                         element_id, self._job_id, exc)
            return None, None, stale

    async def _perform(
        self, page: object, action: str, locator: object, box: Optional[dict], text: Optional[str],
    ) -> None:
        """The input itself: Playwright mouse / keyboard, nothing synthetic
        (except ``select``, whose native popup has no headless mouse target)."""
        if action in ("click", "type") and box is not None:
            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2
            await page.mouse.move(cx, cy, steps=8)
            await page.mouse.click(cx, cy)
        if action == "type":
            # Replace, not append: select what is there, then type over it.
            await locator.evaluate("el => { if (typeof el.select === 'function') el.select(); }")
            for i, ch in enumerate(text):
                if i:
                    await asyncio.sleep(random.uniform(_KEY_DELAY_MIN_S, _KEY_DELAY_MAX_S))
                await page.keyboard.type(ch)
        elif action == "press":
            if locator is not None:
                await locator.focus(timeout=_ACTION_TIMEOUT_MS)  # focus, not click: no double-activate
            await page.keyboard.press((text or "Enter").strip() or "Enter")
        elif action == "select":
            try:
                await locator.select_option(label=text, timeout=_ACTION_TIMEOUT_MS)
            except Exception:  # noqa: BLE001 — the option may be named by value
                await locator.select_option(value=text, timeout=_ACTION_TIMEOUT_MS)
        elif action == "scroll":
            raw = (text or "down").strip().lower()
            if raw in ("up", "top"):
                dy = -600
            elif raw == "bottom":
                dy = 100_000
            else:
                dy = _parse_int(raw, default=600)
            vp = getattr(page, "viewport_size", None) or {"width": 1366, "height": 768}
            await page.mouse.move(vp["width"] / 2, vp["height"] / 2, steps=4)
            await page.mouse.wheel(0, dy)
        elif action == "back":
            if await page.go_back(wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT_MS) is None:
                raise RuntimeError("no previous page in history")

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

    async def screenshot(self, target_selector: Optional[str] = None) -> Optional[bytes]:
        """PNG screenshot of the BROWSER page (REQ-9 AC2: browser-scoped frame
        capture, never the desktop). The vision loop feeds this to the VLM for
        action suggestion / triage. None on a closed session — never raises.

        REQ-4 AC4.1: when `target_selector` names a visual container, capture
        ONLY that element's bounding box (cheaper tokens, sharper OCR).
        Any element-capture failure falls back to the full viewport.
        """
        if self._page is None:
            return None
        # Renew the pool lease on activity: a session that outlives its initial
        # lease window would otherwise have the shared browser closed under it
        # by the idle watchdog (see BrowserLease.renew). screenshot() is the
        # loop's heartbeat — it runs before every action decision and every
        # extraction frame — so renewing here keeps any LIVE session pinned
        # while an abandoned one still expires.
        if self._lease is not None:
            try:
                self._lease.renew(self._bounds.max_wall_ms + 30_000)
            except Exception:  # noqa: BLE001 — renewal must never fail a frame
                pass
        if target_selector:
            try:
                _locator = self._page.locator(target_selector)
                _shot = getattr(_locator, "screenshot", None)
                if callable(_shot):
                    _t0 = time.monotonic()
                    _bytes = await _shot(timeout=_ACTION_POINT_TIMEOUT_MS)
                    self._screenshots_taken += 1
                    record_stage(
                        self._job_id, "screenshot",
                        int((time.monotonic() - _t0) * 1000),
                        count=self._screenshots_taken,
                    )
                    return _bytes
            except Exception as exc:  # noqa: BLE001 — fall back to viewport
                logger.debug(
                    "[browser_session] element screenshot fell back to viewport "
                    "job=%s target=%s: %s",
                    self._job_id, target_selector, exc,
                )
        try:
            _t0 = time.monotonic()
            _bytes = await self._page.screenshot(type="png")
            self._screenshots_taken += 1
            # REQ-8 AC1/AC2 (T4): per-capture duration + the running screenshot
            # count (a count that reveals waste: redundant screenshots per
            # settled state). Off the critical path — record_stage never raises.
            record_stage(
                self._job_id, "screenshot",
                int((time.monotonic() - _t0) * 1000),
                count=self._screenshots_taken,
            )
            return _bytes
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

    # ── T11 (REQ-10): interactive takeover ─────────────────────────────────

    def _get_takeover_manager(self):
        """Lazily create this session's TakeoverManager (REQ-13, T15).

        Imported lazily so `browser_session.py` never references the CDP
        transport at module scope (keeps the CT-7 token scan clean). The
        manager routes frames through the process-wide frame sink the gateway
        registers.
        """
        mgr = getattr(self, "_takeover_mgr", None)
        if mgr is None:
            from backend.vision import cdp_takeover as _cdp

            mgr = _cdp.TakeoverManager(
                run_id=self._job_id,
                frame_sink=_cdp.get_frame_sink(),
            )
            _cdp.register_active(mgr)
            self._takeover_mgr = mgr
        return mgr

    async def _stop_takeover_manager(self, reason: str) -> None:
        """Stop the screencast + release the CDP session + close the grant.

        REQ-13 AC3 / REQ-15 AC3: on resolve, timeout, cancel, or run end the
        screencast stops, the CDP session is released, and the session returns
        to the deterministic DOM path. Idempotent; never raises.
        """
        mgr = getattr(self, "_takeover_mgr", None)
        if mgr is None:
            return
        try:
            await mgr.stop_screencast()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[browser_session] screencast stop failed job=%s: %s", self._job_id, exc)
        try:
            mgr.close_grant(reason)
        except Exception:  # noqa: BLE001
            pass
        try:
            from backend.vision import cdp_takeover as _cdp

            _cdp.unregister_active(self._job_id)
        except Exception:  # noqa: BLE001
            pass

    async def request_takeover(
        self,
        wall: WallKind,
        *,
        site_name: Optional[str] = None,
        timeout_seconds: int = 180,
    ) -> bool:
        """REQ-10 AC1/AC3: hand this page to the user in the browser panel.

        Emits the takeover question (kind="browser_takeover") with contextual
        guidance, waits for "I've Completed It", verifies the wall really is
        gone on the CURRENT page (a user can mis-click or the wall can
        persist — trust nothing), publishes the cleared frame, and returns
        True so the caller RESUMES the action loop instead of parking.

        PAYWALLs are excluded BY DESIGN (Non-Goals: never solve what the user
        cannot solve). False on timeout, on any error, or if the wall
        survives — the caller keeps the wall and parks as before; never
        raises (a takeover failure must not add a second failure mode).

        ``wait_for_answer`` is synchronous (time.sleep), so it runs on a
        thread — calling it inline on the event loop would freeze every
        concurrent crawl and every other live client for the full timeout.
        (Wording note: this docstring deliberately does not name the socket
        transport, because REQ-14 AC2's guard scans this file for transport
        tokens and treats any mention as an inbound channel.)"""
        if wall == WallKind.PAYWALL:
            return False
        try:
            from backend.agent.tools.ask_user_tool import get_ask_user_tool
        except Exception as exc:  # noqa: BLE001 — tooling unavailable
            logger.info(
                "[browser_session] takeover unavailable (ask tool) job=%s: %s",
                self._job_id, exc,
            )
            return False
        url = getattr(self._page, "url", None) or self.url
        # REQ-13 (T15/T18): start the CDP screencast BEFORE asking, so the panel
        # has live frames the moment the user sees the banner. A CDP failure
        # degrades to the existing replay mirror (REQ-13 AC4) — the ask/resume
        # path below is unchanged and still works.
        manager = self._get_takeover_manager()
        manager.open_grant(
            question_id="", wall_kind=wall.value,
            max_ms=max(1, int(timeout_seconds)) * 1000,
        )
        try:
            started = await manager.start_screencast(self._page)
            if not started:
                logger.info(
                    "[browser_session] CDP screencast unavailable job=%s — "
                    "degrading to replay mirror (REQ-13 AC4)", self._job_id,
                )
        except Exception as exc:  # noqa: BLE001 — degrade, never fail the run
            logger.info(
                "[browser_session] screencast start failed job=%s: %s", self._job_id, exc
            )
        try:
            tool = get_ask_user_tool()
            question = tool.ask_browser_takeover(
                takeover_url=url,
                reason=wall.value,
                site_name=site_name,
                job_id=self._job_id,
                timeout_seconds=timeout_seconds,
            )
            # Bind the grant to the real question id now that it exists.
            manager.open_grant(
                question_id=getattr(question, "question_id", ""),
                wall_kind=wall.value,
                max_ms=max(1, int(timeout_seconds)) * 1000,
            )
        except Exception as exc:  # noqa: BLE001 — a broken takeover ask must
            # never kill the session; the caller still has the wall.
            logger.warning(
                "[browser_session] takeover ask failed job=%s: %s", self._job_id, exc
            )
            await self._stop_takeover_manager("ask_failed")
            return False
        try:
            answered = await asyncio.to_thread(tool.wait_for_answer, question)
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "[browser_session] takeover wait failed job=%s: %s", self._job_id, exc
            )
            await self._stop_takeover_manager("wait_failed")
            return False
        # REQ-13 AC3 / REQ-15 AC3: the takeover resolved — STOP the screencast,
        # release the CDP session, and return to the deterministic DOM path.
        await self._stop_takeover_manager("answered")
        if getattr(answered, "answer", None) != "completed":
            logger.info(
                "[browser_session] takeover not completed job=%s status=%s",
                self._job_id, getattr(answered, "status", "?"),
            )
            return False
        # AC3: confirm the obstacle is actually cleared before continuing.
        cleared_wall = await self.detect_wall()
        if cleared_wall is not None:
            logger.info(
                "[browser_session] takeover claimed completed but wall persists "
                "job=%s wall=%s — treating as unresolved",
                self._job_id, cleared_wall.value,
            )
            return False
        try:
            # AC3: capture the settled frame so the panel shows post-takeover.
            await self._publish_frame()
        except Exception as exc:  # noqa: BLE001 — capture failure doesn't veto
            logger.debug("[browser_session] post-takeover frame failed: %s", exc)
        logger.info(
            "[browser_session] takeover cleared the wall job=%s wall=%s (REQ-10 AC3)",
            self._job_id, wall.value,
        )
        return True

    # ── frame publishing (REQ-11 AC1 / AC5) ────────────────────────────────

    @property
    def current_capture_page(self) -> Optional[int]:
        """Capture address of the most recently PUBLISHED frame, or None.

        Read by fetch.vision to put the address on CRAWLER_VISION_ACTION so the
        panel can render the frame the model is looking at. None until the first
        successful publish — never report an address with no bytes behind it.
        """
        if self._last_published is None:
            return None
        return self._page_number

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
            self._frames_skipped += 1
            return html
        # Stay inside this session's reserved block. A session is bounded to ~12
        # distinct frames, so the stride is ample; the clamp is the guard that a
        # runaway loop can never write over the NEXT url's capture addresses —
        # which would silently serve one page's bytes under another's tab.
        _next = self._page_number + 1
        _ceiling = self._page_offset + CAPTURE_SLOT_STRIDE - 1
        if self._page_offset and _next > _ceiling:
            logger.warning(
                "[browser_session] frame block exhausted job=%s slot_offset=%s "
                "frames=%s — not publishing further frames (would overwrite the "
                "next URL's capture)",
                self._job_id, self._page_offset, _next - self._page_offset,
            )
            return html
        self._page_number = _next
        _pub_t0 = time.monotonic()
        try:
            # Off the browser host loop: a disk write + eviction scan measured up
            # to 3.0 s (run A3) and stalls every browser call while it runs.
            await asyncio.to_thread(
                get_capture_store().save, self._job_id, self._page_number, self.url, html,
            )
            self._last_published = html
            self._frames_published += 1
        except Exception as exc:  # noqa: BLE001 — publication is off the hot path
            logger.warning(
                "[browser_session] frame publish failed job=%s page=%s: %s",
                self._job_id, self._page_number, exc,
            )
        # REQ-8 AC1/AC2 (T4): publish duration + the published/skipped split
        # (a count that reveals waste — a session that keeps publishing the
        # same state, or that skips almost everything).
        record_stage(
            self._job_id, "publish",
            int((time.monotonic() - _pub_t0) * 1000),
            published=self._frames_published, skipped=self._frames_skipped,
        )
        return html


__all__ = [
    "BrowserSession",
    "DISMISS_SELECTORS",
    "SessionBounds",
    "SessionBudgetExceeded",
    "VisionAction",
    "WallKind",
]
