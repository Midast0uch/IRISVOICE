"""fetch.vision capability node (T10, REQ-6/REQ-7).

Composes the Wave-2 pieces into one goal-directed fetch capability:
  - BrowserSession (T8): persistent Playwright page, bounded by SessionBounds
  - vision lease (T9): hard-expiry lease holds the owned vision server alive
    for the whole multi-action loop; released on EVERY exit path
  - frame extraction (T12a): triage-before-extract, bounded by max_extractions
  - page_is_usable (T1): vision-derived text is NOT trusted by virtue of being
    vision-derived — it goes through the same predicate as crawl content

Outcome contract (REQ-6 AC5): the settled DOM is handed back via
FetchOutcome.settled_dom so a fetch.crawl pass can run on it — the reversal
edge that makes `crawl -> vision -> crawl` a normal traversal. Wall detection
feeds T14 (REQ-7): CAPTCHA / LOGIN / PAYWALL are returned in FetchOutcome.wall.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Callable, Optional

from backend.crawler.capabilities import FetchCapability, FetchOutcome, WallKind
from backend.crawler.crawler_engine import PageData
from backend.crawler.usability import (
    MIN_CONTENT_CHARS,
    UsabilityReason,
    UsabilityVerdict,
    page_is_usable,
)
from backend.tools.lfm_vl_provider import acquire_vision_lease
from backend.vision.browser_session import (
    BrowserSession,
    SessionBounds,
    VisionAction,
)
from backend.vision.frame_extraction import extract_page_frames, reconcile
from backend.vision.session_vision_adapter import SessionVisionAdapter

logger = logging.getLogger(__name__)

# Vision loops need a hard iteration cap independent of wall-clock: a model
# that keeps suggesting actions must not loop forever even within budget.
_MAX_LOOP_STEPS = int(os.environ.get("IRIS_VISION_MAX_LOOP_STEPS", "8"))


def _make_session(session_cls, job_id, url, goal, bounds, page_offset: int):
    """Construct a browser session, passing ``page_offset`` only if it takes one.

    session_cls is injectable (test doubles implement the 4-positional shape),
    so the capture-block offset is passed by capability, not assumed. Decided by
    signature rather than by catching TypeError from the constructor: a
    TypeError raised inside a real __init__ would be misread as "no such
    parameter" and silently drop the offset, restoring the overwrite bug.
    """
    if page_offset:
        try:
            import inspect

            _params = inspect.signature(session_cls).parameters
            if "page_offset" in _params or any(
                p.kind is inspect.Parameter.VAR_KEYWORD for p in _params.values()
            ):
                return session_cls(job_id, url, goal, bounds, page_offset=page_offset)
            logger.warning(
                "[fetch.vision] session_cls %s takes no page_offset — frames for "
                "job_id=%s will number from 1 and may overwrite another URL's capture",
                getattr(session_cls, "__name__", session_cls), job_id,
            )
        except (TypeError, ValueError):
            pass
    return session_cls(job_id, url, goal, bounds)


class FetchVisionCapability(FetchCapability):
    """Vision-guided browser fetch (REQ-6/REQ-7)."""

    name = "fetch.vision"

    def __init__(
        self,
        provider: Optional[object] = None,
        session_cls: type = BrowserSession,
        bounds: Optional[SessionBounds] = None,
    ):
        self._provider = provider  # lazy get_lfm_vl_provider() when None
        self._session_cls = session_cls
        self._bounds = bounds or SessionBounds()
        self._provider_singleton = None

    # ── FetchCapability ───────────────────────────────────────────────────

    async def available(self) -> bool:
        """True when the vision provider resolves AND a browser session could
        open. Never raises; a missing stack degrades to unavailable (REQ-6
        AC1 edge)."""
        try:
            provider = self._get_provider()
            if provider is None:
                return False
            return True
        except Exception as exc:  # noqa: BLE001
            logger.info("[fetch.vision] unavailable: %s", exc)
            return False

    async def fetch_one(
        self,
        url: str,
        goal: str,
        job_id: str,
        on_action: Optional[Callable[[dict], None]] = None,
        page_offset: int = 0,
    ) -> FetchOutcome:
        """Run the goal-directed action loop for one URL, bounded by
        SessionBounds. Always returns a FetchOutcome — never raises.

        ``on_action`` (REQ-11 AC4) receives one payload per performed action so
        the panel can annotate its existing animation surface. It is an OPTIONAL
        keyword: the FetchCapability protocol is a 3-positional-arg call, so
        fetch.crawl and fetch.vision stay interchangeable (REQ-6 AC1). It is a
        per-call parameter rather than instance state on purpose — the capability
        singleton is shared across concurrent runs, and an emitter stored on it
        would cross-wire their events.

        ``page_offset`` is this URL's reserved block of the job's CAPTURE address
        space, and it is a CORRECTNESS fix, not a cosmetic one. A session
        publishes one capture per distinct frame, numbering from 1, into the
        SHARED job_id directory — so an escalation on URL 4 overwrote the crawl
        captures of URLs 1, 2, 3 and the panel served URL 4's frames under URL
        1's tab. Wrong bytes presented as evidence is worse than a 404. Also a
        per-call parameter: concurrent dispatch runs several sessions at once,
        each owning a different block.
        """
        t0 = time.monotonic()
        bounds = self._bounds
        # T9: hold the vision server for the whole loop; release on exit.
        lease = acquire_vision_lease(max_ms=bounds.max_wall_ms)
        session = _make_session(self._session_cls, job_id, url, goal, bounds, page_offset)
        wall: Optional[WallKind] = None
        actions = 0
        try:
            await session.open()
            if not session.available():
                return FetchOutcome(
                    url=url, capability=self.name, page=None,
                    verdict=UsabilityVerdict(
                        usable=False, reason=UsabilityReason.TRANSPORT_ERROR,
                        detail="vision browser unavailable",
                    ),
                    actions_taken=0,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )

            # ── action loop (REQ-7): suggest -> act -> wall check ──
            repeats: list[str] = []
            for step in range(_MAX_LOOP_STEPS):
                # Wall check first (cheap DOM heuristics, no VLM).
                try:
                    wall = await session.detect_wall()
                except Exception as exc:  # noqa: BLE001
                    logger.info("[fetch.vision] wall-detect failed: %s", exc)
                    wall = None
                if wall is not None:
                    logger.info(
                        "[fetch.vision] job_id=%s url=%s wall=%s (REQ-7)",
                        job_id, url, wall.value,
                    )
                    break

                suggestion = await self._suggest_action(session, goal)
                action = self._map_action(suggestion)
                if action is None:
                    # Model said error/unknown or the loop would repeat itself
                    # 3x in a row (stuck in a click loop) — settle and hand back.
                    logger.info(
                        "[fetch.vision] job_id=%s url=%s stop-loop step=%d suggestion=%r (REQ-7)",
                        job_id, url, step, suggestion,
                    )
                    break

                # Loop-prevention: 3 identical action kinds in a row = stuck.
                repeats.append(action.kind)
                if len(repeats) >= 3 and len(set(repeats[-3:])) == 1:
                    logger.info(
                        "[fetch.vision] job_id=%s url=%s stuck on %s — settling (REQ-7)",
                        job_id, url, action.kind,
                    )
                    break

                try:
                    await session.act(action)
                    actions += 1
                    # REQ-11 AC4: announce the action so the panel can annotate
                    # it. Best-effort — a failing emitter must never break the
                    # loop (REQ-16 AC7: instrumentation is off the critical path).
                    if on_action is not None:
                        try:
                            payload = {
                                "job_id": job_id,
                                "url": url,
                                "kind": action.kind,
                                "reason": action.reason or "",
                                "action_index": actions,
                                "total": _MAX_LOOP_STEPS,
                            }
                            # REQ-16 AC7: fold in the best-effort cursor point
                            # BrowserSession captured for this action (click/
                            # type -> x/y/viewport_w/viewport_h; scroll ->
                            # scroll_dx/scroll_dy). Read via getattr — fakes in
                            # the contract tests do not set this attribute, and
                            # its absence must never break emission.
                            point = getattr(session, "last_action_point", None)
                            if point:
                                payload.update(point)
                            # The session publishes a capture per distinct frame,
                            # but nothing told the panel WHERE. Without the
                            # address those frames were written and never read —
                            # the built-but-never-reached shape this codebase
                            # keeps producing. getattr: fakes do not set it.
                            _frame = getattr(session, "current_capture_page", None)
                            if _frame is not None:
                                payload["capture_page"] = int(_frame)
                            on_action(payload)
                        except Exception as _emit_exc:  # noqa: BLE001
                            logger.debug(
                                "[fetch.vision] on_action emit failed: %s", _emit_exc,
                            )
                except Exception as exc:  # noqa: BLE001
                    # SessionBudgetExceeded or a broken action: observation is
                    # surfaced, loop ends gracefully (REQ-7 AC6).
                    logger.info(
                        "[fetch.vision] job_id=%s url=%s act %s failed: %s (REQ-7 AC6)",
                        job_id, url, action.kind, exc,
                    )
                    break

            # ── extraction (T12a): triage-before-extract, bounded ──
            # SessionVisionAdapter binds the SESSION (frames + scrolling) and
            # the PROVIDER (VLM calls) into the single object
            # extract_page_frames expects (backend/vision/
            # session_vision_adapter.py) — this call site used to pass
            # `session` positionally into extract_page_frames' `provider`
            # parameter AND `provider=` as a keyword, a guaranteed
            # `TypeError: got multiple values for argument 'provider'` that
            # ran in EVERY vision session and was swallowed silently below.
            provider = self._get_provider()
            frames = []
            if provider is not None:
                try:
                    adapter = SessionVisionAdapter(session, provider)
                    frames = await extract_page_frames(adapter, goal, bounds)
                except Exception as exc:  # noqa: BLE001 — non-fatal: the
                    # session still returns its settled DOM below. WARNING
                    # (not info) + url/job_id: this exact failure ran silent
                    # in production for weeks because it logged at info and
                    # nothing asserted extraction actually produced frames.
                    logger.warning(
                        "[fetch.vision] extraction failed job_id=%s url=%s: %s",
                        job_id, url, exc,
                    )

            # ── settled-DOM handback (REQ-6 AC5) + page build ──
            settled_dom = await session.settle()
            vision_text = "\n\n".join(f.text for f in frames if f.text).strip()
            page = self._build_page(url, settled_dom, vision_text)
            verdict = page_is_usable(page)
            # REQ-17 AC3/AC4: reconcile crawl vs vision into an evidence record
            # is done by the caller (orchestrator). Here we only build the page.
            return FetchOutcome(
                url=url,
                capability=self.name,
                page=page if verdict.usable else None,
                verdict=verdict,
                settled_dom=settled_dom or None,
                wall=wall,
                actions_taken=actions,
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
        except Exception as exc:  # noqa: BLE001 — capability must never raise
            logger.warning("[fetch.vision] job_id=%s url=%s error: %s", job_id, url, exc)
            return FetchOutcome(
                url=url, capability=self.name, page=None,
                verdict=UsabilityVerdict(
                    usable=False, reason=UsabilityReason.TRANSPORT_ERROR,
                    detail=str(exc)[:200],
                ),
                actions_taken=actions,
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
        finally:
            try:
                await session.close()
            except Exception as exc:  # noqa: BLE001
                logger.info("[fetch.vision] close failed: %s", exc)
            # T9: lease releases on EVERY path (normal + exception).
            if lease is not None:
                lease.release()

    # ── internals ─────────────────────────────────────────────────────────

    def _get_provider(self):
        if self._provider is not None:
            return self._provider
        if self._provider_singleton is None:
            try:
                from backend.tools.lfm_vl_provider import get_lfm_vl_provider

                self._provider_singleton = get_lfm_vl_provider()
            except Exception as exc:  # noqa: BLE001
                logger.info("[fetch.vision] provider init failed: %s", exc)
                self._provider_singleton = None
        return self._provider_singleton

    async def _suggest_action(self, session: BrowserSession, goal: str) -> dict:
        """Ask the VLM for the next action, feeding a BROWSER screenshot
        (REQ-9 AC2: never the desktop). Graceful when vision is down."""
        provider = self._get_provider()
        if provider is None:
            return {"action": "error", "target": "", "reasoning": "vision unavailable"}
        try:
            img = await session.screenshot()
            if img is None:
                return {"action": "error", "target": "", "reasoning": "no browser frame"}
            # to_thread, NOT a direct call. suggest_action is SYNCHRONOUS and
            # reaches _ensure_vision_server_running, whose readiness loop sleeps
            # 0.5s x 60 = up to THIRTY SECONDS, followed by a blocking httpx
            # call with a 30s timeout. Called inline from this already-running
            # event loop it froze the whole backend — WebSocket, TTS and all —
            # which is the "app stopped responding when the vision server
            # launched" observed live on 2026-08-11. SessionVisionAdapter
            # already dispatches every provider call this way; this was the one
            # provider call that had been left on the loop.
            return await asyncio.to_thread(provider.suggest_action, img, goal) or {}
        except Exception as exc:  # noqa: BLE001
            logger.info("[fetch.vision] suggest failed: %s", exc)
            return {"action": "error", "target": "", "reasoning": str(exc)}

    def _map_action(self, suggestion: dict) -> Optional[VisionAction]:
        """Map a VLM suggestion dict to a VisionAction, or None to stop."""
        action = str((suggestion or {}).get("action", "")).strip().lower()
        target = str((suggestion or {}).get("target", "")).strip()
        reason = str((suggestion or {}).get("reasoning", "")).strip()
        if action in ("error", "unknown", "done", "stop", "none"):
            return None
        kind = {
            "click": "click",
            "type": "type",
            "scroll": "scroll",
            "wait": "wait",
            "navigate": "navigate",
            "reload": "reload",
            "back": "back",
            "forward": "forward",
        }.get(action)
        if kind is None:
            return None
        return VisionAction(kind=kind, target=target or None, value=target or None, reason=reason)

    def _build_page(self, url: str, settled_dom: str, vision_text: str) -> PageData:
        """Build PageData for the outcome. Vision text wins when present and
        usable; otherwise a light strip of the settled DOM is the fallback so
        page_is_usable can judge it (REQ-17 AC5: vision text is not trusted by
        provenance — it is judged by the same predicate)."""
        import re

        def _strip(html: str) -> str:
            text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
            text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            return re.sub(r"\s+", " ", text).strip()

        md = vision_text or _strip(settled_dom or "")
        return PageData(
            url=url,
            title="",
            markdown=md,
            html=settled_dom or None,
            metadata={},
            error=None,
            html_bytes=len(settled_dom or ""),
        )


_vision_capability: Optional[FetchVisionCapability] = None


def get_fetch_vision() -> FetchVisionCapability:
    """Module-level singleton so the registry holds ONE vision capability."""
    global _vision_capability
    if _vision_capability is None:
        _vision_capability = FetchVisionCapability()
    return _vision_capability
