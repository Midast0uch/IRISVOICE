"""Vision frame extraction and evidence reconciliation (T12a/T12b, REQ-17).

Two concerns live here:

1. :func:`extract_page_frames` — the vision extraction loop for one URL. It
   walks scroll positions, uses the CHEAP triage tier (``describe_live_frame``)
   to decide whether a frame holds new content, and only runs the FULL
   extraction tiers (``read_text`` / ``analyze_screen``) on frames that pass
   triage. Bounded by :class:`SessionBounds` (REQ-17 AC8) and deduplicated
   across overlapping scroll positions (design D8).

2. :class:`EvidenceRecord` + :func:`reconcile` — T12b (REQ-17 AC3/AC4/AC5).
   One record per URL that merges crawl text and vision text, marks the
   origin, and NEVER silently picks a winner: every disagreement is a
   recorded diagnostic (design D9).

The vision provider is injected (constructor/function arg) so tests pass a
fake — nothing here may touch the real vision server or the live web.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional, Protocol

logger = logging.getLogger(__name__)


class ContentOrigin(str, Enum):
    """Provenance of an EvidenceRecord's merged text (REQ-17 AC3)."""

    CRAWL = "crawl"
    VISION = "vision"
    RECONCILED = "reconciled"


@dataclass
class SessionBounds:
    """Hard budget for one vision session (REQ-17 AC8, design verbatim)."""

    max_actions: int = 12
    max_wall_ms: int = 60_000
    max_extractions: int = 8


@dataclass
class FrameExtraction:
    """One extracted frame at one scroll position (design verbatim)."""

    scroll_top: int
    text: str
    triage_verdict: Literal["new_content", "no_new_content", "challenge"]
    extraction_ms: int


@dataclass
class EvidenceRecord:
    """One record per URL merging crawl + vision evidence (design verbatim)."""

    url: str
    origin: ContentOrigin
    crawl_text: Optional[str]
    vision_text: Optional[str]
    merged_text: str
    disagreement: Optional[str] = None  # REQ-17 AC5
    frames: list[FrameExtraction] = field(default_factory=list)


class VisionProvider(Protocol):
    """Minimal provider surface used by the extraction loop (injectable).

    ASYNC by design: the real binding (backend/vision/session_vision_adapter
    .SessionVisionAdapter) sources frames from BrowserSession.screenshot()
    and drives scrolling via BrowserSession.act() — both ``async def``. This
    loop runs from inside the already-running event loop of
    FetchVisionCapability.fetch_one, so the surface it drives must be async
    all the way down rather than reaching for asyncio.run()/
    run_until_complete() (which raise from inside a running loop).
    """

    async def screenshot_to_bytes(self) -> Optional[bytes]: ...

    async def describe_live_frame(self, prompt: str) -> str: ...

    async def read_text(self) -> str: ...

    async def analyze_screen(self, question: str) -> str: ...


class BudgetExceeded(Exception):
    """The session hit SessionBounds.max_extractions (REQ-17 AC8)."""


async def extract_page_frames(
    provider: VisionProvider,
    goal: str,
    bounds: SessionBounds | None = None,
    max_scrolls: int = 6,
) -> list[FrameExtraction]:
    """Scroll-loop extraction for one URL's live page.

    Triage tier first (``describe_live_frame``, cheap): frames whose triage is
    "no_new_content" stop the loop (dedupe across scroll positions — D8).
    "challenge" frames (CAPTCHA/login/paywall prose) are recorded with empty
    text and stop the loop. Only "new_content" frames run the full extraction
    tiers. Never exceeds ``bounds.max_extractions`` (raises BudgetExceeded).

    Physically scrolling between iterations is delegated to the provider
    (``_scroll_down``) — a real session-backed provider moves the page; a
    pure-VLM test fake without that capability is a no-op, same as before.
    """
    b = bounds or SessionBounds()
    frames: list[FrameExtraction] = []
    scroll = 0
    while len(frames) < b.max_extractions and scroll <= max_scrolls:
        triage = await _triage_frame(provider, goal, scroll)
        if triage == "challenge":
            frames.append(FrameExtraction(scroll_top=scroll, text="", triage_verdict="challenge", extraction_ms=0))
            break
        if triage == "no_new_content":
            break  # overlapping / settled — stop (D8)
        text = await _full_extract(provider)
        frames.append(
            FrameExtraction(scroll_top=scroll, text=text, triage_verdict="new_content", extraction_ms=_extract_ms())
        )
        scroll += 1
        await _scroll_down(provider, scroll)
    if len(frames) >= b.max_extractions:
        raise BudgetExceeded(f"max_extractions={b.max_extractions} hit for {goal!r}")
    return frames


async def _triage_frame(provider: VisionProvider, goal: str, scroll: int) -> Literal["new_content", "no_new_content", "challenge"]:
    t_start = time.monotonic()
    try:
        prompt = (
            f"Goal: {goal}. This is the page at scroll position {scroll}. "
            "Reply with exactly one word: new_content if this frame shows text "
            "not already seen above, no_new_content if it is a repeat/blank, "
            "challenge if it shows a captcha, login wall, or paywall."
        )
        answer = (await provider.describe_live_frame(prompt) or "").strip().lower()
        logger.debug("[frame_extraction] triage(scroll=%s)=%r in %.0fms", scroll, answer, (time.monotonic() - t_start) * 1000)
    except Exception as exc:  # noqa: BLE001 — provider failure degrades to no_new_content
        logger.warning("[frame_extraction] triage failed: %s", exc)
        return "no_new_content"
    if "challenge" in answer or "captcha" in answer or "paywall" in answer or "login" in answer:
        return "challenge"
    # check "no_new"/"no new"/"repeat"/"blank" BEFORE the bare "new" match,
    # else "no_new_content" would classify as new_content
    if any(neg in answer for neg in ("no_new", "no new", "repeat", "blank", "same")):
        return "no_new_content"
    if "new" in answer or "yes" in answer:
        return "new_content"
    return "no_new_content"


async def _full_extract(provider: VisionProvider) -> str:
    """Full extraction tier: read_text primary, analyze_screen fallback (D8)."""
    try:
        text = (await provider.read_text() or "").strip()
        if text:
            return text
    except Exception as exc:  # noqa: BLE001
        logger.warning("[frame_extraction] read_text failed: %s", exc)
    try:
        return (await provider.analyze_screen("Extract all visible text verbatim.") or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[frame_extraction] analyze_screen failed: %s", exc)
        return ""


async def _scroll_down(provider: VisionProvider, scroll: int) -> None:
    """Advance the page before the next extraction iteration.

    Delegates to the provider's own ``scroll_down`` when present — this
    keeps frame_extraction free of browser concerns (original design intent)
    while letting a real session-backed adapter (SessionVisionAdapter)
    physically move the page between iterations. Providers that do not
    implement scrolling (pure-VLM test fakes) are left as a no-op, matching
    the original dedup-bucket semantics.
    """
    scroller = getattr(provider, "scroll_down", None)
    if scroller is None:
        return
    try:
        await scroller()
    except Exception as exc:  # noqa: BLE001 — a failed scroll degrades to a
        # repeated frame; the next triage call most likely reads
        # no_new_content off it and the loop stops naturally.
        logger.warning("[frame_extraction] scroll_down(scroll=%s) failed: %s", scroll, exc)


def _extract_ms() -> int:
    return int((time.monotonic() % 1000) * 1)  # coarse; real timing in fetch.vision


# ---------------------------------------------------------------------------
# T12b — EvidenceRecord reconciliation (REQ-17 AC3/AC4/AC5, design D9)
# ---------------------------------------------------------------------------


def _tokens(text: str) -> set[str]:
    return {t for t in text.lower().split() if t}


def _similar(a: str, b: str, threshold: float = 0.3) -> bool:
    """Token-overlap Jaccard. Pure, no heavy deps."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= threshold


def reconcile(crawl_text: Optional[str], vision_text: Optional[str], url: str) -> EvidenceRecord:
    """Merge crawl and vision evidence into one record.

    Rules (design D9 — never pick a winner silently):
    - both present and similar      -> origin=RECONCILED, merged=longer text
    - crawl present, vision absent  -> origin=CRAWL, merged=crawl
    - vision present, crawl absent  -> origin=VISION, merged=vision
    - both present, DISSIMILAR      -> origin=RECONCILED but disagreement set
    - neither                       -> origin=CRAWL, merged=""
    """
    from backend.crawler.usability import text_is_challenge

    c = (crawl_text or "").strip()
    v = (vision_text or "").strip()

    # BT-9 / REQ-17 AC5: a challenge interstitial must NEVER win the merge.
    # "longer text wins" hands victory to the challenge, because real Cloudflare
    # pages are verbose (~350 chars of boilerplate) while the content they hide
    # is often shorter. That is the reference trajectory's exact failure: the
    # crawler extracted the interstitial as content and synthesis reasoned over
    # it. Judged BEFORE the length rule so length can never override it.
    c_chal = text_is_challenge(c)
    v_chal = text_is_challenge(v)
    if c and v and (c_chal or v_chal) and not (c_chal and v_chal):
        winner, loser_kind = (v, "crawl") if c_chal else (c, "vision")
        return EvidenceRecord(
            url=url,
            origin=ContentOrigin.RECONCILED,
            crawl_text=c, vision_text=v, merged_text=winner,
            disagreement=f"{loser_kind}_returned_challenge",
        )

    if c and v:
        if _similar(c, v):
            merged = c if len(c) >= len(v) else v
            return EvidenceRecord(
                url=url, origin=ContentOrigin.RECONCILED,
                crawl_text=c, vision_text=v, merged_text=merged,
            )
        merged = c if len(c) >= len(v) else v
        return EvidenceRecord(
            url=url, origin=ContentOrigin.RECONCILED,
            crawl_text=c, vision_text=v, merged_text=merged,
            disagreement=(
                "crawl_vision_diverge"
                if len(c) >= len(v) and len(v) >= 20
                else "vision_crawl_diverge"
            ),
        )
    if c:
        return EvidenceRecord(url=url, origin=ContentOrigin.CRAWL, crawl_text=c, vision_text=None, merged_text=c)
    if v:
        return EvidenceRecord(
            url=url, origin=ContentOrigin.VISION, crawl_text=None, vision_text=v, merged_text=v,
            disagreement="vision_has_text_crawl_empty",
        )
    return EvidenceRecord(url=url, origin=ContentOrigin.CRAWL, crawl_text=None, vision_text=None, merged_text="")


def under_capture_heuristic(crawl_text: Optional[str], crawl_html: Optional[str]) -> bool:
    """REQ-17 AC7: a nominally-usable but suspiciously thin crawl.

    True when the markdown is too thin for the HTML payload — a signal the
    vision path may capture content headless extraction missed. Pure function.
    """
    text_len = len((crawl_text or "").strip())
    html_len = len(crawl_html or "")
    if text_len == 0:
        return True
    if html_len >= 20_000 and text_len < 400:
        return True
    return text_len < 200
