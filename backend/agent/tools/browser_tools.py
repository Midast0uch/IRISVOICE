"""`browser_open` / `browser_observe` / `browser_act` — the agent drives a real page.

Specs/websearch-vision-browser REQ-4 / REQ-5, design D6. The agent gets ONE live
Playwright page per conversation, built on ``BrowserSession`` (no second browser
class): ``browser_open`` loads a URL, ``browser_observe`` lists what can be
clicked or typed into (Set-of-Marks), ``browser_act`` does it with real mouse and
keyboard input while the overlay shows the cursor arriving first.

WHY ONE HOST LOOP. The DER loop runs every tool call on a fresh event loop
(``tool_decision._run_async``), and a Playwright object only works on the loop
that created it (measured 2026-09-30: a session held open on one loop made the
pool's next user on another loop HANG). A session that must outlive one tool call
therefore lives on the ONE browser host loop (``vision.browser_host``), and every
tool call marshals onto it. The same loop hosts the crawl pool's Chromium, so the
backend runs ONE Chromium; each conversation gets its own BrowserContext.

Bounded: at most ``IRIS_BROWSER_MAX_SESSIONS`` sessions (default 2, LRU-closed),
each idle-closed after ``_IDLE_TTL_S``; the pool stops the Chromium when idle.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from backend.agent.tools import click_safety
from backend.vision.browser_host import get_browser_host

logger = logging.getLogger(__name__)

Emit = Callable[[str, dict], None]

_MAX_SESSIONS = max(1, int(os.environ.get("IRIS_BROWSER_MAX_SESSIONS", "2")))
_IDLE_TTL_S = 300.0
_REAP_EVERY_S = 30.0
# Whole-call ceilings. open: cold Chromium launch + navigation; the others are
# one DOM round trip plus the settle.
_OPEN_TIMEOUT_S = 120.0
_OBSERVE_TIMEOUT_S = 30.0
# act = the input itself (60 s) + the click-safety gate's Brain judge and the
# user's answer window, so a question never eats the action's own time.
_ACT_TIMEOUT_S = 60.0 + click_safety.JUDGE_TIMEOUT_S + click_safety.ASK_TIMEOUT_S
# browser_explore: the whole read of the related pages, and one page's navigation.
_EXPLORE_TIMEOUT_S = 30.0
_EXPLORE_MAX_PAGES = 5
_EXPLORE_NAV_MS = 8_000
_EXPLORE_PASSAGE_CHARS = 400
_LINKS_JS = (
    "() => Array.from(document.querySelectorAll('a[href]')).slice(0, 300)"
    ".map(a => [a.href, (a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 120)])"
)
_MAIN_TEXT_JS = (
    "() => { const r = document.querySelector('article') || document.querySelector('main') "
    "|| document.body; return r ? r.innerText : ''; }"
)
# A long interactive task takes many steps; the defaults for vision sessions
# (12 actions / 60 s) are sized for a reading pass, not for this.
_SESSION_MAX_ACTIONS = 150
_SESSION_MAX_WALL_MS = 900_000
# Ceiling on the base64 marked screenshot carried in a tool result.
_MAX_IMAGE_B64 = 600_000


@dataclass
class _Entry:
    session: Any
    emit: Optional[Emit] = None
    last_used: float = field(default_factory=time.monotonic)
    # Elements the click-safety gate refused (or the user declined) in this task:
    # the agent must not retry the same one. Bounded.
    refused: "deque[str]" = field(default_factory=lambda: deque(maxlen=64))


class _BrowserRuntime:
    """The agent's browser sessions, hosted on the shared browser host loop.

    ``sessions`` is touched ONLY from the host loop, so it needs no lock; ``run``
    is the single way in from any other loop. The Chromium is the pool's - one per
    backend process - and each conversation gets its own BrowserContext from it.
    """

    def __init__(self) -> None:
        self._reaper_started = False
        self.sessions: "OrderedDict[str, _Entry]" = OrderedDict()

    def loop(self) -> asyncio.AbstractEventLoop:
        loop = get_browser_host().loop()
        if not self._reaper_started:
            self._reaper_started = True
            asyncio.run_coroutine_threadsafe(self._reap_forever(), loop)
        return loop

    async def run(self, coro: Any, timeout: float) -> Any:
        """Run ``coro`` on the host loop from any loop; cancel it on timeout."""
        self.loop()
        return await get_browser_host().run(coro, timeout)

    # ── session lifecycle (loop thread only) ────────────────────────────────

    async def close_entry(self, conv: str, reason: str) -> None:
        """Close one conversation's session and tell the panel the run is over.
        The shared Chromium stays up: the pool's idle watchdog stops it when no
        crawl or session needs it. Never raises."""
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
    if resolution is not None and getattr(resolution, "requires_load", False) and client is not None:
        # V5/V8: the chosen vision model loads into the empty slot now. This
        # runs on the probe's own daemon thread (no event loop), so the load
        # may block it; observes meanwhile go without a screenshot.
        return bool(client.start())
    return bool(client is not None and client.health_check())


# The probe can make HTTP calls to local model servers. It runs on its OWN
# daemon thread, never the loop's default executor: a probe abandoned by the
# 3 s bound there was still joined when the per-call loop closed, so a slow
# probe held the tool call anyway (it hung the Wave B tests at teardown).
# The answer is cached so each observe does not probe again.
_VISION_TTL_S = 60.0
_VISION_WAIT_S = 3.0
_vision_lock = threading.Lock()
_vision_state: Dict[str, Any] = {"at": 0.0, "value": False, "probing": False}


def _vision_probe_thread() -> None:
    try:
        value = _vision_live_sync()
    except Exception as exc:  # noqa: BLE001 — no vision is the safe answer
        logger.debug("[browser_tools] vision probe failed: %s", exc)
        value = False
    with _vision_lock:
        _vision_state.update(at=time.monotonic(), value=bool(value), probing=False)


async def _vision_live() -> bool:
    """Cached vision liveness. Waits at most _VISION_WAIT_S for a fresh probe,
    then answers False (degrades the marked screenshot, never cancels the probe)."""
    deadline = time.monotonic() + _VISION_WAIT_S
    started_here = False
    while True:
        with _vision_lock:
            fresh = time.monotonic() - _vision_state["at"] < _VISION_TTL_S
            if fresh:
                return bool(_vision_state["value"])
            if not _vision_state["probing"]:
                _vision_state["probing"] = True
                started_here = True
                threading.Thread(
                    target=_vision_probe_thread, daemon=True, name="iris-vision-probe",
                ).start()
            elif not started_here:
                # An EARLIER call started this probe and already waited for it
                # (e.g. a 2-min vision model autoload): answer the last value
                # now. Live run A5: every observe paid the full 3 s.
                return bool(_vision_state["value"])
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.1)


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
        res = await _RT.run(_do_open(conversation_id, url, emit), _OPEN_TIMEOUT_S)
        return await _with_observation(conversation_id, res, emit)
    except asyncio.TimeoutError:
        return _fail(f"browser unavailable: opening {url} timed out")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[browser_tools] open failed conv=%s: %s", conversation_id, exc)
        return _fail(f"browser unavailable: {str(exc)[:200]}")


async def _with_observation(conv: str, res: Dict[str, Any], emit: Optional[Emit]) -> Dict[str, Any]:
    """Append the page's observation to a successful open / page-changing act.

    Live 2026-10-02 run A8: 51 tool calls for one lookup - 23 were
    browser_observe, almost each one right after an open or an act whose
    result said only "call browser_observe". One call now returns both. A
    failed observe leaves the result as it was (the model can still observe).
    """
    if not (isinstance(res, dict) and res.get("success")):
        return res
    try:
        want_image = await _vision_live()
        obs = await _RT.run(_do_observe(conv, want_image, emit), _OBSERVE_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - the action stands without the list
        logger.debug("[browser_tools] attached observe failed conv=%s: %s", conv, exc)
        return res
    if not (isinstance(obs, dict) and obs.get("success")):
        return res
    out = dict(res)
    head = str(res.get("content") or "").replace(
        " Call browser_observe to see what you can click or type into.", "").replace(
        " The page changed; call browser_observe again to renumber the elements.",
        " The page changed.")
    out["content"] = "\n".join((head, str(obs.get("content") or "")))
    for key in ("marks", "marks_seq", "marked_screenshot"):
        if key in obs:
            out[key] = obs[key]
    return out


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
        res = await _RT.run(_do_act(conversation_id, action, element_id, text, emit), _ACT_TIMEOUT_S)
        if isinstance(res, dict) and res.get("changed"):
            res = await _with_observation(conversation_id, res, emit)
        return res
    except asyncio.TimeoutError:
        return _fail(f"browser_act {action} timed out")
    except Exception as exc:  # noqa: BLE001
        return _fail(f"browser_act failed: {str(exc)[:200]}")


async def browser_explore(
    conversation_id: str, goal: str, max_pages: Any = 5, emit: Optional[Emit] = None,
) -> Dict[str, Any]:
    """Read the goal-relevant same-site pages linked from the live page (read-only)."""
    goal = (goal or "").strip()
    if not goal:
        return _fail("browser_explore needs a goal")
    try:
        pages = max(1, min(int(max_pages or _EXPLORE_MAX_PAGES), _EXPLORE_MAX_PAGES))
    except (TypeError, ValueError):
        pages = _EXPLORE_MAX_PAGES
    try:
        return await _RT.run(_do_explore(conversation_id, goal, pages, emit), _EXPLORE_TIMEOUT_S + 5.0)
    except asyncio.TimeoutError:
        return _fail("browser_explore timed out")
    except Exception as exc:  # noqa: BLE001
        return _fail(f"browser_explore failed: {str(exc)[:200]}")


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
        )
        try:
            await session.open()
        except Exception as exc:  # noqa: BLE001 — open() released what it held
            await session.close()
            return _fail(f"browser unavailable: {str(exc)[:200]}")
        if not session.available():
            await session.close()
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


async def _gate_action(entry: _Entry, action: str, mark: dict, text: Optional[str]) -> Optional[Dict[str, Any]]:
    """The click-safety gate for one element action: ``None`` = go ahead, else the
    refusal result (``ok=false, pivot=true``). No input is dispatched on a refusal.

    safe -> act; unsafe -> refuse; unsure -> ask the user (bounded); a timeout or
    a "no" refuses. Refused elements are remembered for the rest of the task.
    One shadow row per assessment, off this path.
    """
    session = entry.session
    ctx = click_safety.ACT_CONTEXT.get() or {}
    page_url = str(getattr(getattr(session, "_page", None), "url", "") or getattr(session, "url", "") or "")
    key = click_safety.mark_key(mark, page_url)
    what = click_safety.describe(action, mark, page_url, text)
    if key in entry.refused:
        return click_safety.refusal(f"{what} was already refused in this task", "refused")

    verdict, reason = await click_safety.assess(ctx.get("goal") or "", action, mark, page_url, text)
    try:
        from backend.agent import click_safety_shadow

        click_safety_shadow.submit_assessment(f'{ctx.get("goal") or ""} | {what}', verdict)
    except Exception as exc:  # noqa: BLE001 - the shadow never blocks an action
        logger.debug("[browser_tools] click_safety shadow skipped: %s", exc)
    if verdict == click_safety.SAFE:
        return None
    # Taxonomy SAFETY: the verdict becomes an event (no element text: it is untrusted).
    # The rules' reason names the element's label, so only the action and role are kept.
    _facts = {"action": action, "role": str(mark.get("role") or "")}
    if verdict == click_safety.UNSAFE:
        click_safety.emit_event(ctx, "UNSAFE_REFUSED", evidence="verifier", payload=_facts)
        entry.refused.append(key)
        return click_safety.refusal(f"{what} is not allowed: {reason}", verdict)
    click_safety.emit_event(ctx, "ESCALATED_UNSURE", payload=_facts)
    question = (
        f"IRIS wants to {what}. Task: {(ctx.get('goal') or 'browse')[:160]}. "
        f"Why I ask: {reason}. Allow it?"
    )
    if await click_safety.escalate(question, ctx):
        return None
    entry.refused.append(key)
    return click_safety.refusal(f"the user did not approve: {what}", verdict)


async def _do_act(
    conv: str, action: str, element_id: Any, text: Optional[str], emit: Optional[Emit],
) -> Dict[str, Any]:
    entry, problem = _need_session(conv, emit)
    if entry is None:
        return _fail(problem)
    session = entry.session
    mark = None
    try:
        mark = next((m for m in session.last_marks if m.get("id") == int(element_id)), None)
    except (TypeError, ValueError):
        pass
    target = _label(mark)
    # An unknown element id never reaches the gate: interact() reports the stale id
    # itself, before any input or cursor event.
    if mark is not None:
        blocked = await _gate_action(entry, action, mark, text)
        if blocked is not None:
            # Taxonomy CONTROL: a refused element means the agent reaches the goal another
            # way (trigger = the NodeOutcome Reason of a policy refusal).
            click_safety.emit_event(
                click_safety.ACT_CONTEXT.get(), "PIVOT", evidence="verifier",
                trigger=click_safety.PIVOT_TRIGGER, action_signature=f"browser_act:{action}",
                payload={"verdict": blocked.get("verdict"), "action": action},
            )
            return blocked
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


def _best_passage(text: str, goal: str) -> str:
    """The paragraph of ``text`` that shares the most goal words (the first one when
    none does), at most ``_EXPLORE_PASSAGE_CHARS`` long."""
    from backend.crawler.cite import _tok
    from backend.crawler.site_links import goal_tokens

    want = goal_tokens(goal)
    chunks = [c.strip() for c in (text or "").split("\n") if len(c.strip()) >= 40]
    if not chunks:
        return (text or "").strip()[:_EXPLORE_PASSAGE_CHARS]
    best = max(chunks, key=lambda c: len(want & _tok(c)))
    return best[:_EXPLORE_PASSAGE_CHARS]


async def _read_related_page(context: Any, url: str, goal: str, budget_s: float) -> Dict[str, Any]:
    """Open ``url`` in a throwaway tab of the session's context, read it, close it."""
    from backend.vision.browser_pool import block_heavy_resources

    page = await context.new_page()
    try:
        await block_heavy_resources(page)
        await page.goto(url, wait_until="domcontentloaded",
                        timeout=int(min(_EXPLORE_NAV_MS, max(1.0, budget_s) * 1000)))
        title = (await page.title() or "").strip()[:120]
        text = await page.evaluate(_MAIN_TEXT_JS)
        return {"url": str(page.url or url), "title": title, "passage": _best_passage(text, goal)}
    finally:
        try:
            await page.close()
        except Exception:  # noqa: BLE001 - a leaked tab is closed with its context
            pass


async def _do_explore(conv: str, goal: str, max_pages: int, emit: Optional[Emit]) -> Dict[str, Any]:
    """Visit the goal-relevant same-site links of the session's current page, one
    background tab at a time, within ``_EXPLORE_TIMEOUT_S``. Reads only."""
    from backend.crawler.site_links import rank_same_site

    entry, problem = _need_session(conv, emit)
    if entry is None:
        return _fail(problem)
    session = entry.session
    page, context = getattr(session, "_page", None), getattr(session, "_context", None)
    if page is None or context is None:
        return _fail("no open browser for this conversation; call browser_open(url) first")
    base = str(getattr(page, "url", "") or session.url)
    links = [(str(h), str(t)) for h, t in await page.evaluate(_LINKS_JS)]
    targets = rank_same_site(links, base, goal, limit=max_pages)
    deadline = time.monotonic() + _EXPLORE_TIMEOUT_S
    visited: list = []
    for url in targets:
        left = deadline - time.monotonic()
        if left < 1.0:
            break  # the time bound holds: what is read so far is returned
        if await _egress_error(url):
            continue
        try:
            visited.append(await _read_related_page(context, url, goal, left))
        except Exception as exc:  # noqa: BLE001 - one bad page does not stop the rest
            logger.debug("[browser_tools] explore %s failed conv=%s: %s", url, conv, exc)
    try:
        session._renew_lease()
    except Exception:  # noqa: BLE001
        pass
    if not visited:
        body = "No other page of this site that matches the goal could be read."
    else:
        body = f'Read {len(visited)} related page(s) of {base} for "{goal}":\n' + "\n".join(
            f'[{i}] {p["url"]} - "{p["title"]}"\n    {p["passage"]}' for i, p in enumerate(visited, 1)
        )
    return {
        "success": True, "content": body, "pages": visited,
        "skipped": len(targets) - len(visited), "url": base, "trust": "untrusted",
    }
