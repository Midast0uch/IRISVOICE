"""`browser_open` / `browser_observe` / `browser_act` — the agent drives a real page.

Specs/websearch-vision-browser REQ-4 / REQ-5, design D6. The agent gets ONE live
Playwright page per conversation, built on ``BrowserSession`` (no second browser
class): ``browser_open`` loads a URL, ``browser_observe`` lists what can be
clicked or typed into (Set-of-Marks), ``browser_act`` does it with real mouse and
keyboard input while the overlay shows the cursor arriving first.

WHY A PRIVATE LOOP AND A PRIVATE CHROMIUM. The DER loop runs every tool call on a
fresh event loop (``tool_decision._run_async``), and a Playwright object only
works on the loop that created it. The shared ``browser_pool`` Chromium is bound
to whichever loop started it: measured 2026-09-30, a session held open on one
loop makes the pool's next user on another loop HANG (and across two
``asyncio.run`` calls the pooled browser is a corpse). A session that must
outlive one tool call therefore lives on ONE dedicated loop thread with its own
Chromium, and every tool call marshals onto it. Crawls keep the shared pool and
never touch this browser.

Bounded: at most ``IRIS_BROWSER_MAX_SESSIONS`` sessions (default 2, LRU-closed),
each idle-closed after ``_IDLE_TTL_S``; the private Chromium exits with its last
session.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

Emit = Callable[[str, dict], None]

_MAX_SESSIONS = max(1, int(os.environ.get("IRIS_BROWSER_MAX_SESSIONS", "2")))
_IDLE_TTL_S = 300.0
_REAP_EVERY_S = 30.0
# Whole-call ceilings. open: cold Chromium launch + navigation; the others are
# one DOM round trip plus the settle.
_OPEN_TIMEOUT_S = 120.0
_OBSERVE_TIMEOUT_S = 30.0
_ACT_TIMEOUT_S = 60.0
_LAUNCH_TIMEOUT_S = 60.0
# A long interactive task takes many steps; the defaults for vision sessions
# (12 actions / 60 s) are sized for a reading pass, not for this.
_SESSION_MAX_ACTIONS = 150
_SESSION_MAX_WALL_MS = 900_000
# Ceiling on the base64 marked screenshot carried in a tool result.
_MAX_IMAGE_B64 = 600_000


class _NullLease:
    """Stands in for a pool lease: the private browser is closed by its own
    last session, not by an idle watchdog."""

    def renew(self, *_a: Any, **_k: Any) -> None:
        pass

    def release(self) -> None:
        pass


@dataclass
class _Entry:
    session: Any
    emit: Optional[Emit] = None
    last_used: float = field(default_factory=time.monotonic)


class _BrowserRuntime:
    """The dedicated loop thread, its sessions and its private Chromium.

    ``sessions`` and the browser handles are touched ONLY from the loop thread,
    so they need no lock; ``run`` is the single way in from any other loop.
    """

    def __init__(self) -> None:
        self._start_lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.sessions: "OrderedDict[str, _Entry]" = OrderedDict()
        self._pw: Any = None
        self._browser: Any = None
        self._launch_lock: Optional[asyncio.Lock] = None

    def loop(self) -> asyncio.AbstractEventLoop:
        with self._start_lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                threading.Thread(
                    target=loop.run_forever, name="iris-browser-loop", daemon=True,
                ).start()
                asyncio.run_coroutine_threadsafe(self._reap_forever(), loop)
                self._loop = loop
            return self._loop

    async def run(self, coro: Any, timeout: float) -> Any:
        """Run ``coro`` on the browser loop from any loop; cancel it on timeout."""
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop())
        try:
            return await asyncio.wait_for(asyncio.wrap_future(fut), timeout)
        except BaseException:  # timeout or the caller being cancelled
            fut.cancel()
            raise

    # ── private browser (loop thread only) ──────────────────────────────────

    async def acquire(self, max_lease_ms: float = 0) -> tuple:
        """Drop-in for ``browser_pool.acquire_browser`` (see BrowserSession)."""
        if self._launch_lock is None:
            self._launch_lock = asyncio.Lock()
        async with self._launch_lock:
            if self._browser is not None and not self._browser.is_connected():
                await self.stop_browser()
            if self._browser is None:
                from playwright.async_api import async_playwright  # lazy, heavy

                pw = await async_playwright().start()
                try:
                    self._browser = await asyncio.wait_for(
                        pw.chromium.launch(
                            headless=True,
                            args=["--disable-blink-features=AutomationControlled"],
                        ),
                        _LAUNCH_TIMEOUT_S,
                    )
                except BaseException:
                    try:
                        await pw.stop()
                    except Exception:  # noqa: BLE001
                        pass
                    raise
                self._pw = pw
                logger.info("[browser_tools] private browser started")
            return self._browser, _NullLease()

    async def stop_browser(self) -> None:
        browser, pw = self._browser, self._pw
        self._browser = self._pw = None
        for closer in (browser, pw):
            if closer is None:
                continue
            try:
                await (closer.close() if closer is browser else closer.stop())
            except Exception as exc:  # noqa: BLE001
                logger.debug("[browser_tools] private browser stop: %s", exc)

    # ── session lifecycle (loop thread only) ────────────────────────────────

    async def close_entry(self, conv: str, reason: str) -> None:
        """Close one conversation's session, tell the panel the run is over, and
        stop the private Chromium when it was the last one. Never raises."""
        entry = self.sessions.pop(conv, None)
        if entry is None:
            return
        session = entry.session
        _emit(entry.emit, "CRAWLER_COMPLETE", {
            "query": session.url, "summary": f"browser session closed ({reason})",
            "page_count": getattr(session, "_frames_published", 0),
            "job_id": getattr(session, "_job_id", ""),
        })
        try:
            await session.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[browser_tools] session close conv=%s: %s", conv, exc)
        logger.info("[browser_tools] session closed conv=%s reason=%s", conv, reason)
        if not self.sessions:
            await self.stop_browser()

    async def _reap_forever(self) -> None:
        while True:
            await asyncio.sleep(_REAP_EVERY_S)
            try:
                now = time.monotonic()
                for conv, entry in list(self.sessions.items()):
                    if now - entry.last_used > _IDLE_TTL_S:
                        await self.close_entry(conv, "idle")
            except Exception as exc:  # noqa: BLE001 — the reaper must not die
                logger.debug("[browser_tools] reaper: %s", exc)


_RT = _BrowserRuntime()


def _emit(emit: Optional[Emit], event: str, payload: dict) -> None:
    """Forward one crawl-vocabulary event; a dead frontend never fails a tool."""
    if emit is None:
        return
    try:
        emit(event, payload)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[browser_tools] emit %s failed: %s", event, exc)


def _normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url or any(c.isspace() for c in url):
        return ""
    if "://" not in url:
        url = "https://" + url
    return url if url.lower().startswith(("http://", "https://")) else ""


async def _egress_error(url: str) -> str:
    """Why the egress guard refuses ``url``, or "" — the same gate the crawler and
    screenshot_page use, so this tool is no way around it."""
    try:
        from backend.proxy.egress_guard import EgressRefused, acheck_url
    except ImportError:
        return ""
    try:
        await acheck_url(url)
    except EgressRefused as refused:
        logger.info("[browser_tools] egress refused %s: %s", url, refused)
        return "that address is not allowed"
    except Exception as exc:  # noqa: BLE001 — a guard error must not open the gate
        logger.warning("[browser_tools] egress guard errored for %s: %s", url, exc)
        return "could not verify that address"
    return ""


def _vision_live_sync() -> bool:
    """True when a vision model can look at the marked screenshot right now."""
    from backend.agent.inference.router import resolve_vision_client

    resolution, client = resolve_vision_client()
    if resolution is not None and getattr(resolution, "tier", "") in ("brain", "tool"):
        return True  # an already-live provider
    return bool(client is not None and client.health_check())


async def _vision_live() -> bool:
    try:
        return await asyncio.wait_for(asyncio.to_thread(_vision_live_sync), 3.0)
    except Exception:  # noqa: BLE001 — no vision is the safe answer
        return False


def _fail(error: str) -> Dict[str, Any]:
    return {"success": False, "error": error}


def _label(mark: Optional[dict]) -> str:
    if not mark:
        return ""
    return f'{mark.get("role", "element")} "{mark.get("name", "")}"'.strip()


# ── public tool entry points (any loop) ────────────────────────────────────


async def browser_open(conversation_id: str, url: str, emit: Optional[Emit] = None) -> Dict[str, Any]:
    """Open ``url`` in this conversation's live browser (starting it if needed)."""
    url = _normalize_url(url)
    if not url:
        return _fail("browser_open needs an http(s) url")
    refused = await _egress_error(url)
    if refused:
        return _fail(refused)
    try:
        return await _RT.run(_do_open(conversation_id, url, emit), _OPEN_TIMEOUT_S)
    except asyncio.TimeoutError:
        return _fail(f"browser unavailable: opening {url} timed out")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[browser_tools] open failed conv=%s: %s", conversation_id, exc)
        return _fail(f"browser unavailable: {str(exc)[:200]}")


async def browser_observe(conversation_id: str, emit: Optional[Emit] = None) -> Dict[str, Any]:
    """List the page's interactive elements, numbered (Set-of-Marks)."""
    want_image = await _vision_live()
    try:
        return await _RT.run(_do_observe(conversation_id, want_image, emit), _OBSERVE_TIMEOUT_S)
    except asyncio.TimeoutError:
        return _fail("browser_observe timed out")
    except Exception as exc:  # noqa: BLE001
        return _fail(f"browser_observe failed: {str(exc)[:200]}")


async def browser_act(
    conversation_id: str, action: str, element_id: Any = None, text: Optional[str] = None,
    emit: Optional[Emit] = None,
) -> Dict[str, Any]:
    """click | type | select | scroll | back | press on the live page."""
    try:
        return await _RT.run(_do_act(conversation_id, action, element_id, text, emit), _ACT_TIMEOUT_S)
    except asyncio.TimeoutError:
        return _fail(f"browser_act {action} timed out")
    except Exception as exc:  # noqa: BLE001
        return _fail(f"browser_act failed: {str(exc)[:200]}")


async def close_conversation_browser(conversation_id: str) -> None:
    """Close a conversation's browser session (conversation end). Never raises."""
    try:
        await _RT.run(_RT.close_entry(conversation_id, "conversation ended"), 30.0)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[browser_tools] close conv=%s: %s", conversation_id, exc)


def handoff_hint(urls: Any) -> str:
    """The crawl's hand-off to the session (AC4.6): a page the crawl could not
    read is named to the agent together with the tool that can open it."""
    picked = [u for u in (urls or []) if isinstance(u, str) and u.startswith("http")][:3]
    if not picked:
        return ""
    return (
        "If a page only works in a real browser, open it with browser_open(url=...) "
        "and drive it with browser_observe / browser_act: " + ", ".join(picked) + "."
    )


# ── loop-thread implementations ────────────────────────────────────────────


def _touch(conv: str, emit: Optional[Emit]) -> Optional[_Entry]:
    entry = _RT.sessions.get(conv)
    if entry is not None:
        entry.last_used = time.monotonic()
        if emit is not None:
            entry.emit = emit
        _RT.sessions.move_to_end(conv)  # LRU order: newest last
    return entry


async def _do_open(conv: str, url: str, emit: Optional[Emit]) -> Dict[str, Any]:
    from backend.vision.browser_session import BrowserSession, SessionBounds

    entry = _touch(conv, emit)
    if entry is not None and (not entry.session.available() or entry.session._budget_error()):
        await _RT.close_entry(conv, "replaced")  # dead or out of budget: start fresh
        entry = None

    _emit(emit, "CRAWLER_STARTED", {"query": url, "url_count": 1})
    if entry is not None:
        res = await entry.session.navigate_to(url, emit)
        if not res["ok"]:
            return _fail(res["error"])
        session = entry.session
    else:
        while len(_RT.sessions) >= _MAX_SESSIONS:  # bounded: the least recently used goes
            await _RT.close_entry(next(iter(_RT.sessions)), "evicted")
        session = BrowserSession(
            job_id=f"browser-{uuid.uuid4().hex[:12]}", url=url,
            goal="interactive browsing for the agent",
            bounds=SessionBounds(
                max_actions=_SESSION_MAX_ACTIONS, max_wall_ms=_SESSION_MAX_WALL_MS,
            ),
            acquire=_RT.acquire,
        )
        try:
            await session.open()
        except Exception as exc:  # noqa: BLE001 — open() released what it held
            await session.close()
            if not _RT.sessions:
                await _RT.stop_browser()
            return _fail(f"browser unavailable: {str(exc)[:200]}")
        if not session.available():
            await session.close()
            if not _RT.sessions:
                await _RT.stop_browser()
            return _fail("browser unavailable: the browser could not be started")
        _RT.sessions[conv] = _Entry(session=session, emit=emit)
        _emit(emit, "OPEN_TAB", {
            "tab_type": "web", "id": "live-reading", "title": url, "url": url,
            "job_id": session._job_id,
        })
        await session._announce_page(emit, force=True)

    state = await session._page_state()
    return {
        "success": True,
        "content": (
            f'Opened {state["url"]} - "{state["title"]}". '
            f"Call browser_observe to see what you can click or type into."
        ),
        "url": state["url"], "title": state["title"], "job_id": session._job_id,
        "trust": "untrusted",
    }


def _need_session(conv: str, emit: Optional[Emit]) -> "tuple[Optional[_Entry], str]":
    entry = _touch(conv, emit)
    if entry is None or not entry.session.available():
        return None, "no open browser for this conversation; call browser_open(url) first"
    return entry, ""


async def _do_observe(conv: str, want_image: bool, emit: Optional[Emit]) -> Dict[str, Any]:
    entry, problem = _need_session(conv, emit)
    if entry is None:
        return _fail(problem)
    res = await entry.session.observe(marked_screenshot=want_image)
    if not res["ok"]:
        return _fail(res["error"])
    marks = res["marks"]
    lines = [f'[{m["id"]}] {_label(m)}' + (" (disabled)" if m.get("disabled") else "")
             + ("" if m.get("in_view") else " (off screen)") for m in marks]
    content = (
        f'Page: "{res["title"]}" - {res["url"]}\n'
        f'Text: {res["digest"]}\n'
        f"Elements (pass the number as element_id to browser_act):\n"
        + ("\n".join(lines) if lines else "(none found)")
    )
    out: Dict[str, Any] = {
        "success": True, "content": content, "url": res["url"], "title": res["title"],
        "marks": marks, "marks_seq": res["marks_seq"], "trust": "untrusted",
    }
    image = res.get("marked_image")
    if image:
        b64 = base64.b64encode(image).decode("ascii")
        if len(b64) <= _MAX_IMAGE_B64:
            out["marked_screenshot"] = {"mime": "image/jpeg", "b64": b64}
    return out


async def _do_act(
    conv: str, action: str, element_id: Any, text: Optional[str], emit: Optional[Emit],
) -> Dict[str, Any]:
    entry, problem = _need_session(conv, emit)
    if entry is None:
        return _fail(problem)
    session = entry.session
    target = ""
    try:
        target = _label(next((m for m in session.last_marks if m.get("id") == int(element_id)), None))
    except (TypeError, ValueError):
        pass
    res = await session.interact(action, element_id, text, emit)
    if not res["ok"]:
        return _fail(res["error"])
    tail = (
        "The page changed; call browser_observe again to renumber the elements."
        if res["changed"] else "The page did not change."
    )
    return {
        "success": True,
        "content": (
            f'{res["action"]}{" " + target if target else ""} done. '
            f'Page: "{res["title"]}" - {res["url"]}. {tail}'
        ),
        "url": res["url"], "title": res["title"], "changed": res["changed"],
        "marks_seq": res["marks_seq"], "trust": "untrusted",
    }
