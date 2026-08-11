"""Vision-driven search-engine discovery (T24/T25, REQ-19).

The dead end this fixes was observed live on 2026-08-10:
``[CrawlPlanner] LLM planning produced no URLs for '...'; no search-engine
fallback (DuckDuckGo removed). Crawl will report 'no candidate urls'.`` Every
rung of the existing recovery ladder (REQ-2's broaden-and-retry) assumes the
PLANNER produced URLs; when the planner itself is the failure, re-planning
re-fails identically. A browser that can type into a search box is a
DIFFERENT acquisition channel, not a retry of the same one.

Reuses the EXISTING :class:`~backend.vision.browser_session.BrowserSession`
(REQ-7 AC2 — navigate/type/click/scroll/screenshot/settle are already built;
this is their first caller for search discovery) rather than adding a second
browser-automation path. Extraction prefers the cheap, exact DOM read
(``session.current_frame()`` / ``settle()``) and falls back to the vision
provider's ``read_text`` / ``analyze_screen`` only when the DOM yields
nothing (REQ-19 AC2 — "the reason vision exists here").

Discovered URLs are handed back to the caller as a plain ``list[str]``. The
CALLER (``CrawlOrchestrator``) is responsible for feeding them into the
normal per-URL dispatch path (REQ-19 AC3) — this module does not fetch or
dispatch content itself, so there is exactly one fetch path in the system
(design D2/D4).

Non-Requirements (spec verbatim): a CAPTCHA/bot-challenge on the search
engine is PARKED and reported, NEVER solved (REQ-19 AC5). This module never
attempts to defeat one.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urlparse

from backend.vision.browser_session import BrowserSession, SessionBounds, VisionAction

logger = logging.getLogger(__name__)

# Search engine driven by discovery. Configurable so a blocked engine can be
# swapped without a code change. Bing is used by default because it (unlike
# DuckDuckGo, which was removed per the live trace above) tolerates a plain
# Chromium UA reasonably well for a single query.
_SEARCH_ENGINE_URL = os.environ.get("IRIS_VISION_SEARCH_ENGINE_URL", "https://www.bing.com/")
_SEARCH_INPUT_SELECTOR = os.environ.get(
    "IRIS_VISION_SEARCH_INPUT_SELECTOR", "textarea[name='q'], input[name='q']"
)
_SEARCH_SUBMIT_SELECTOR = os.environ.get(
    "IRIS_VISION_SEARCH_SUBMIT_SELECTOR", "#sb_form_go, button[type='submit']"
)
# REQ-19 AC4: "at most a configurable number of candidate URLs."
_DEFAULT_MAX_RESULTS = int(os.environ.get("IRIS_VISION_DISCOVERY_MAX_URLS", "5"))
# REQ-19 AC4: bounded by SessionBounds — discovery is a handful of actions
# (open, type, submit, maybe one scroll), not a multi-page interactive read.
_DEFAULT_BOUNDS = SessionBounds(max_actions=6, max_wall_ms=30_000, max_extractions=2)

# Search-engine own domain + common ad/redirect hosts filtered from results
# (REQ-19 AC2: "filter out the search engine's own domain, ads, and obvious
# navigation links"). Kept as substrings of netloc, not exact matches, so
# regional subdomains (www.bing.com, cn.bing.com, ...) are all caught.
_EXCLUDED_DOMAIN_FRAGMENTS = (
    "bing.com",
    "microsoft.com",
    "msn.com",
    "duckduckgo.com",
    "google.com",
    "googleadservices.com",
    "googlesyndication.com",
    "doubleclick.net",
)

_HREF_RE = re.compile(r'href=["\'](https?://[^"\'#]+)["\']', re.IGNORECASE)
_BARE_URL_RE = re.compile(r'https?://[^\s\'"<>)]+')


@dataclass
class DiscoveryResult:
    """Outcome of one discovery attempt (REQ-19).

    ``wall`` set means the SEARCH ENGINE itself presented a bot challenge —
    the caller parks it (REQ-13) and never attempts to solve it (AC5).
    ``unavailable`` means the vision/browser stack itself could not be used
    at all (REQ-19 AC8) — the caller falls through to the honest REQ-15
    no-sources outcome exactly as it would for a genuinely empty plan.
    """

    urls: list[str] = field(default_factory=list)
    wall: Optional[str] = None          # WallKind value, e.g. "captcha"
    engine_url: Optional[str] = None    # the walled URL, for _park_source
    unavailable: bool = False
    used_vision_fallback: bool = False


def _looks_like_result_url(url: str) -> bool:
    """REQ-19 AC2: drop the engine's own domain, ads, and non-result links."""
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return False
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    netloc = parsed.netloc.lower()
    if any(frag in netloc for frag in _EXCLUDED_DOMAIN_FRAGMENTS):
        return False
    return True


def _extract_urls_from_html(html: str, limit: int) -> list[str]:
    """Cheap, exact DOM extraction (REQ-19 AC2 primary path)."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _HREF_RE.finditer(html or ""):
        url = m.group(1)
        if not _looks_like_result_url(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= limit:
            break
    return out


def _extract_urls_from_text(text: str, limit: int) -> list[str]:
    """Fallback extraction from vision-read text (REQ-19 AC2 fallback path)."""
    seen: set[str] = set()
    out: list[str] = []
    for m in _BARE_URL_RE.finditer(text or ""):
        url = m.group(0).rstrip(").,;")
        if not _looks_like_result_url(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= limit:
            break
    return out


def _get_provider():
    """Lazy singleton lookup, mirroring `fetch_vision.py`'s pattern. Never
    raises — a missing/broken vision stack just means no fallback tier."""
    try:
        from backend.tools.lfm_vl_provider import get_lfm_vl_provider

        return get_lfm_vl_provider()
    except Exception as exc:  # noqa: BLE001
        logger.info("[search_discovery] provider unavailable: %s", exc)
        return None


async def click_discovered_result(session: BrowserSession, url: str) -> str:
    """Click a specific discovered result rather than only harvesting URLs
    (explicit user ask alongside REQ-19). Returns the settled DOM of the
    destination page, or "" if the click failed — never raises, matching
    `BrowserSession.act`'s REQ-7 AC6 contract (a failed action is an
    observation, not an abort)."""
    try:
        await session.act(VisionAction(
            kind="click", target=f"a[href='{url}']", reason="open selected search result",
        ))
    except Exception as exc:  # noqa: BLE001
        logger.info("[search_discovery] click_discovered_result failed url=%s: %s", url, exc)
        return ""
    return await session.settle()


async def discover_urls_via_vision(
    query: str,
    job_id: str,
    _emit: Optional[Callable[[str, dict], None]] = None,
    *,
    max_results: int = _DEFAULT_MAX_RESULTS,
    bounds: Optional[SessionBounds] = None,
    session_cls: type = BrowserSession,
    provider: Optional[object] = None,
) -> DiscoveryResult:
    """Drive a search engine in the vision browser session and harvest
    candidate result URLs (REQ-19 AC1/AC2). Never raises — every failure
    path returns a `DiscoveryResult` the caller can act on (REQ-19 AC8).

    ``_emit`` is the orchestrator's progress emitter (same shape as
    `_vision_fetch` uses for CRAWLER_VISION_ACTION) — optional so this module
    has no hard dependency on the orchestrator's event plumbing.
    """
    b = bounds or _DEFAULT_BOUNDS
    session = session_cls(job_id, _SEARCH_ENGINE_URL, query, b)
    try:
        await session.open()
        if not session.available():
            logger.info(
                "[search_discovery] job_id=%s unavailable (browser session "
                "could not open) (REQ-19 AC8)",
                job_id,
            )
            return DiscoveryResult(unavailable=True)

        # REQ-19 AC2: navigate to a search engine, enter the query, submit.
        # Per-action failures are recorded as observations by `act()` itself
        # (REQ-7 AC6) — a failed type/click here degrades to "no results
        # extracted" below, it does not raise.
        await session.act(VisionAction(
            kind="type", target=_SEARCH_INPUT_SELECTOR, value=query,
            reason="enter search query (REQ-19)",
        ))
        await session.act(VisionAction(
            kind="click", target=_SEARCH_SUBMIT_SELECTOR,
            reason="submit search (REQ-19)",
        ))
        html = await session.settle()
        _announce(_emit, job_id, "submit_search", query)

        # REQ-19 AC5: a wall on the SEARCH ENGINE itself is parked by the
        # caller, NEVER solved. Checked before extraction so a challenge page
        # is never mistaken for an empty results page.
        wall = await session.detect_wall()
        if wall is not None:
            logger.info(
                "[search_discovery] job_id=%s wall=%s on search engine "
                "-> park, not solve (REQ-19 AC5)",
                job_id, wall.value,
            )
            return DiscoveryResult(wall=wall.value, engine_url=_SEARCH_ENGINE_URL)

        urls = _extract_urls_from_html(html, max_results)
        used_fallback = False
        if not urls:
            # REQ-19 AC2 fallback: vision reads the rendered frame when DOM
            # extraction yields nothing — the reason vision exists here.
            prov = provider if provider is not None else _get_provider()
            if prov is not None:
                try:
                    img = await session.screenshot()
                    if img is not None:
                        text = prov.read_text(img) or ""
                        if not text.strip():
                            text = prov.analyze_screen(
                                img,
                                "List the URLs or article titles of the search "
                                "results visible on this page.",
                            ) or ""
                        urls = _extract_urls_from_text(text, max_results)
                        used_fallback = bool(urls)
                except Exception as exc:  # noqa: BLE001 — fallback is best-effort
                    logger.info(
                        "[search_discovery] job_id=%s vision fallback failed: %s",
                        job_id, exc,
                    )
        logger.info(
            "[search_discovery] job_id=%s query=%s discovered=%d fallback=%s "
            "(REQ-19 AC1/AC2/AC4, REQ-16)",
            job_id, query[:60], len(urls), used_fallback,
        )
        return DiscoveryResult(urls=urls[:max_results], used_vision_fallback=used_fallback)
    except Exception as exc:  # noqa: BLE001 — REQ-19 must never fail the run
        logger.warning("[search_discovery] job_id=%s error=%s (REQ-19 AC8)", job_id, exc)
        return DiscoveryResult(unavailable=True)
    finally:
        try:
            await session.close()
        except Exception as exc:  # noqa: BLE001
            logger.info("[search_discovery] session close failed job_id=%s: %s", job_id, exc)


def _announce(_emit, job_id: str, kind: str, reason: str) -> None:
    """Best-effort action announcement, same shape as `_vision_fetch`'s
    CRAWLER_VISION_ACTION payload (REQ-11 AC4) — never breaks discovery."""
    if _emit is None:
        return
    try:
        _emit("CRAWLER_VISION_ACTION", {
            "job_id": job_id, "url": _SEARCH_ENGINE_URL, "kind": kind,
            "reason": reason, "action_index": 1, "total": 1,
        })
    except Exception:  # noqa: BLE001
        pass


__all__ = [
    "DiscoveryResult",
    "click_discovered_result",
    "discover_urls_via_vision",
]
