"""Session + provider adapter for vision frame extraction (fixes the live
production bug: ``extract_page_frames() got multiple values for argument
'provider'``, observed on every vision session, job c3e083435f4c4076ad9aee1db70f67fb,
2026-08-10 23:28-23:30 — zero vision content ever extracted).

``extract_page_frames`` (frame_extraction.py) expects ONE object presenting
the ``VisionProvider`` surface (``screenshot_to_bytes`` / ``describe_live_frame``
/ ``read_text`` / ``analyze_screen``). Nothing in production ever satisfied
that surface: frames + scrolling belong to the BROWSER SESSION
(backend/vision/browser_session.py — ``screenshot()``, and scrolling via
``act(VisionAction(kind="scroll"))``), while the VLM calls belong to the REAL
provider (backend/tools/lfm_vl_provider.py — ``LFMVLProvider``), whose
methods all take ``img_bytes`` as an explicit first argument instead of
implicitly holding "the current frame". This module is the missing binder.

Async/sync boundary (resolved deliberately, not accidentally):
``BrowserSession.screenshot()``/``.act()`` are ``async def``, and this
adapter is constructed and driven from inside the ALREADY-RUNNING event loop
of ``FetchVisionCapability.fetch_one`` — calling ``asyncio.run()`` or
``loop.run_until_complete()`` from in there raises. So ``extract_page_frames``
and its helpers (frame_extraction.py) were made ``async`` and are now
``await``-ed from ``fetch_one`` (option (a) from the fix brief). The
alternative — pre-capturing frames on the async side and serving them
synchronously — was rejected: the extraction loop is ADAPTIVE. How many
scrolls it takes depends on each frame's triage verdict, which is not known
ahead of time, so there is no fixed batch of frames to pre-capture.
``extract_page_frames`` had exactly ONE production caller
(backend/vision/fetch_vision.py) and no caller in
backend/vision/search_discovery.py (that module talks to the session and
provider directly, bypassing this Protocol entirely) — the blast radius of
going async was one call site plus the tests that call this function
directly with hand-rolled fakes.

The real ``LFMVLProvider`` methods are SYNCHRONOUS, blocking HTTP calls
(``httpx.post``, up to ``config.timeout`` seconds, occasionally preceded by a
blocking subprocess spawn on first use). Each is dispatched via
``asyncio.to_thread`` so a slow/hung vision server stalls only this session's
own loop, never the whole asyncio reactor (CLAUDE.md quality bar: no
blocking call on an async hot path).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Protocol

from backend.vision.browser_session import VisionAction

logger = logging.getLogger(__name__)


class _SessionLike(Protocol):
    """The subset of BrowserSession this adapter drives.

    Duck-typed (not `isinstance`-checked against BrowserSession) so tests can
    inject a lightweight fake without subclassing the real session, matching
    the injection pattern the rest of backend/vision already uses.
    """

    async def screenshot(self) -> Optional[bytes]: ...

    async def act(self, action: VisionAction) -> None: ...


class SessionVisionAdapter:
    """Binds a browser session (frames + scrolling) and a vision provider
    (VLM calls) into the ``VisionProvider`` surface ``extract_page_frames``
    expects (backend/vision/frame_extraction.py).

    REQ-9 AC2 is absolute: ``screenshot_to_bytes`` is ALWAYS the SESSION's
    browser-scoped screenshot. It never calls
    ``backend.tools.lfm_vl_provider.screenshot_to_bytes()`` (module-level
    function) — that captures the DESKTOP and must never be reachable from
    any websearch path.
    """

    def __init__(self, session: _SessionLike, provider: object) -> None:
        self._session = session
        self._provider = provider
        # REQ-9 AC2/AC3 (T7): ONE captured frame per settled state. Triage and
        # the extraction tiers for the SAME state share this frame instead of
        # each taking its own screenshot (the old behavior: three VLM-facing
        # calls cost three captures of one unchanged screen). Invalidated when
        # the page actually moves (scroll_down), so a NEW settled state always
        # gets a FRESH observation (REQ-9 AC4).
        self._frame_cache: Optional[bytes] = None

    def invalidate_frame(self) -> None:
        """Drop the cached frame so the next capture is fresh.

        Called when the page changes (scroll_down). REQ-9 AC4: a changed frame
        always gets a fresh observation -- the cache is per settled state, never
        across states.
        """
        self._frame_cache = None

    # ── VisionProvider surface (frame_extraction.extract_page_frames) ──────

    async def screenshot_to_bytes(self) -> Optional[bytes]:
        """The current BROWSER frame (REQ-9 AC2) -- never the desktop.

        REQ-9 AC3 (T7): returns the cached frame for the CURRENT settled state
        when one exists, so triage and extraction share a single capture. The
        cache is cleared by ``scroll_down`` (a new settled state).
        """
        if self._frame_cache is not None:
            return self._frame_cache
        self._frame_cache = await self._session.screenshot()
        return self._frame_cache

    async def describe_live_frame(self, prompt: str) -> str:
        """Triage tier (design D8, cheap-gates-expensive).

        The real provider's ``describe_live_frame(img_bytes)`` ignores any
        caller-supplied prompt — it always asks its own fixed, low-token
        question ("what is happening on this screen"). That is unusable
        here: triage NEEDS the goal-specific
        new_content/no_new_content/challenge question
        (frame_extraction._triage_frame) to classify the frame at all.
        Routed through ``analyze_screen`` instead, which DOES accept an
        arbitrary question. This trades the fixed method's smaller token
        budget for a triage call that can actually answer the question it is
        asked — without this, live triage always falls through to
        frame_extraction's ``no_new_content`` default on the first frame and
        NOTHING is ever extracted, which is the exact silent-failure mode
        this adapter exists to fix.
        """
        img = await self.screenshot_to_bytes()
        if img is None or self._provider is None:
            return ""
        answer = await asyncio.to_thread(self._provider.analyze_screen, img, prompt)
        return answer or ""

    async def read_text(self) -> str:
        """Full-extraction primary tier — OCR-style verbatim text."""
        img = await self.screenshot_to_bytes()
        if img is None or self._provider is None:
            return ""
        text = await asyncio.to_thread(self._provider.read_text, img)
        return text or ""

    async def analyze_screen(self, question: str) -> str:
        """Full-extraction fallback tier, used when ``read_text`` is empty."""
        img = await self.screenshot_to_bytes()
        if img is None or self._provider is None:
            return ""
        text = await asyncio.to_thread(self._provider.analyze_screen, img, question)
        return text or ""

    # ── scrolling (frame_extraction._scroll_down delegates here) ───────────

    async def scroll_down(self, delta: int = 800) -> None:
        """Advance the page for the NEXT extraction iteration.

        ``frame_extraction._scroll_down`` looks this method up via
        ``getattr`` and calls it only when present — pure-VLM test fakes
        without a ``scroll_down`` method keep the old no-op dedupe-bucket
        behaviour untouched. This is the real actuation: without it, every
        extraction iteration re-triages the SAME frame, and a stateless VLM
        (LFMVLProvider docstring: "No state held between calls... every call
        is independent") has no way to notice that on its own — so the loop
        would always read the first frame as unchanging and stop after one
        iteration, extracting nothing beyond it.
        """
        await self._session.act(
            VisionAction(kind="scroll", value=str(delta), reason="frame extraction scroll (T12a)")
        )
        # REQ-9 AC4 (T7): the page moved, so the settled state CHANGED — drop
        # the cached frame so the next triage/extraction captures fresh. Without
        # this the cache would pin the first screenful for the whole loop.
        self.invalidate_frame()


__all__ = ["SessionVisionAdapter"]
