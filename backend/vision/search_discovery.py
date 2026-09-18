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

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import parse_qsl, urlparse

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


def _results_url(query: str) -> str:
    """The search engine's RESULTS url for a query (session-331).

    Submitting via the results URL is markup-independent — it does not depend on
    a submit button existing, or on the box submitting on Enter. Built from the
    configured engine URL's host so a swapped engine still works. Bing's form is
    ``/search?q=``; other engines fall back to a ``?q=`` query on the root.
    """
    from urllib.parse import quote_plus, urlparse

    base = urlparse(_SEARCH_ENGINE_URL)
    host = f"{base.scheme}://{base.netloc}" if base.scheme else _SEARCH_ENGINE_URL
    host = host.rstrip("/")
    if "bing.com" in host:
        return f"{host}/search?q={quote_plus(query)}"
    return f"{host}/search?q={quote_plus(query)}"
# REQ-19 AC4: "at most a configurable number of candidate URLs."
_DEFAULT_MAX_RESULTS = int(os.environ.get("IRIS_VISION_DISCOVERY_MAX_URLS", "5"))
# REQ-19 AC4: bounded by SessionBounds — discovery is a handful of actions
# (open, type, submit, maybe one scroll), not a multi-page interactive read.
# Session-326 (owner: no wall): the wall clock no longer kills a discovery
# mid-run — the 6-action count is the real bound, each goto still holds its
# own nav timeout, and cold launch already sits outside this clock. The wide
# wall value keeps the lease (wall + 30s) valid while the acts finish.
_DEFAULT_BOUNDS = SessionBounds(max_actions=6, max_wall_ms=300_000, max_extractions=2)

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

# T9 (REQ-9 AC9.1–AC9.2): Hybrid Adversarial SEO & Affiliate Trap Filtering.
# Tier A is a pure-URL fast reject (no network, no model): affiliate tracking
# params, redirector paths, spam TLDs. Tier B is title/snippet semantic
# (keyword-stuffing density > 0.35, coupon-aggregator parasite hosting
# reviews). Authority re-rank is a stable sort so equal-score URLs keep SERP
# order (CT-12 existing contract asserts exact order for clean URLs).
_AFFILIATE_QUERY_PARAMS = frozenset({
    "aff_id", "tag", "click_id", "ref", "subid", "afftrack",
})
_REDIRECT_PATH_RES = (
    re.compile(r"/out\.php", re.IGNORECASE),
    re.compile(r"(^|/)go(/|$)", re.IGNORECASE),
)
_SPAM_TLDS = frozenset({
    ".xyz", ".top", ".click", ".loan", ".win", ".bid", ".cricket",
    ".party", ".gq", ".ml", ".cf", ".tk", ".pw", ".stream",
})
_KEYWORD_DENSITY_LIMIT = 0.35
_PARASITE_HOST_FRAGMENTS = (
    "coupon", "coupons", "deal", "deals", "promo", "voucher",
    "cashback", "reward", "giftcard",
)
_PARASITE_CONTENT_HINTS = (
    "review", "reviews", "best", "top 10", "top-10", "vpn", "vs ",
)
_WORD_RE = re.compile(r"[a-z0-9]+")
_TRUSTED_TLD_SUFFIXES = (".gov", ".edu", ".ac.", ".mil")
_DOCS_HOST_PREFIXES = ("docs.", "developer.", "developers.", "support.")


def _is_affiliate_trap(url: str) -> bool:
    """Tier A (REQ-9 AC9.1): True if the URL is an affiliate/redirector trap.

    Never raises — an unparsable URL is treated as a trap (dropped), which is
    the safe direction for a pre-crawl filter.
    """
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return True
    netloc = (parsed.netloc or "").lower()
    if not netloc:
        return True
    if any(netloc == tld[1:] or netloc.endswith(tld) for tld in _SPAM_TLDS):
        return True
    path = parsed.path or ""
    if any(rx.search(path) for rx in _REDIRECT_PATH_RES):
        return True
    try:
        for key, _val in parse_qsl(parsed.query or "", keep_blank_values=True):
            if key.lower() in _AFFILIATE_QUERY_PARAMS:
                return True
    except Exception:  # noqa: BLE001 — malformed query string drops the URL
        return True
    return False


def _keyword_density(text: str) -> float:
    """Max single-token frequency / total tokens (Tier B stuffing signal)."""
    tokens = _WORD_RE.findall((text or "").lower())
    if not tokens:
        return 0.0
    counts: dict[str, int] = {}
    top = 0
    for tok in tokens:
        counts[tok] = counts.get(tok, 0) + 1
        if counts[tok] > top:
            top = counts[tok]
    return top / len(tokens)


def _is_parasite_candidate(url: str, title: str = "", snippet: str = "") -> bool:
    """Tier B parasite check: coupon/deal aggregator host carrying review-style
    content (title/snippet/path hints) or a keyword-stuffed title+snippet."""
    try:
        netloc = (urlparse(url).netloc or "").lower()
    except Exception:  # noqa: BLE001
        return True
    blob = f"{title} {snippet} {url}".lower()
    if any(frag in netloc for frag in _PARASITE_HOST_FRAGMENTS) and any(
        hint in blob for hint in _PARASITE_CONTENT_HINTS
    ):
        return True
    # Density check needs enough tokens to be meaningful — short titles like
    # "os docs / official docs" (4 tokens, one repeat) would false-positive
    # at 0.50, so only evaluate snippets of >= 10 tokens.
    joined = f"{title} {snippet}"
    if len(_WORD_RE.findall(joined.lower())) >= 10 and _keyword_density(joined) > _KEYWORD_DENSITY_LIMIT:
        return True
    return False


def _authority_score(url: str) -> int:
    """AC9.2 re-rank signal: official/primary sources first, farms last."""
    try:
        netloc = (urlparse(url).netloc or "").lower()
    except Exception:  # noqa: BLE001
        return -10
    if any(frag in netloc for frag in _PARASITE_HOST_FRAGMENTS):
        return -2
    score = 0
    if any(sfx in netloc for sfx in _TRUSTED_TLD_SUFFIXES):
        score += 3
    if netloc.startswith(_DOCS_HOST_PREFIXES):
        score += 2
    if netloc.startswith("www."):
        score += 0  # neutral: keep SERP order among ordinary hosts
    return score


def filter_adversarial_candidates(
    candidates: list[tuple[str, str, str]],
    *,
    job_id: str = "",
) -> list[str]:
    """Full Tier A+B filter + authority re-rank over (url, title, snippet).

    Pure function (no I/O): Tier A drops traps, Tier B drops parasite/stuffed
    entries, survivors stable-sort by authority score. Never raises.
    """
    scored: list[tuple[int, int, str]] = []
    dropped_a = 0
    dropped_b = 0
    try:
        for idx, cand in enumerate(candidates or []):
            try:
                url, title, snippet = cand
            except Exception:  # noqa: BLE001 — malformed tuple drops
                dropped_a += 1
                continue
            if _is_affiliate_trap(url):
                dropped_a += 1
                continue
            if _is_parasite_candidate(url, title or "", snippet or ""):
                dropped_b += 1
                continue
            scored.append((_authority_score(url), idx, url))
    except Exception:  # noqa: BLE001 — filter must never break discovery
        logger.info("[search_discovery] job_id=%s seo filter error (REQ-9)", job_id)
        return [c[0] for c in (candidates or []) if c and c[0]]
    scored.sort(key=lambda row: (-row[0], row[1]))
    if dropped_a or dropped_b:
        logger.info(
            "[search_discovery] job_id=%s seo filter dropped_a=%d dropped_b=%d kept=%d (REQ-9)",
            job_id, dropped_a, dropped_b, len(scored),
        )
    return [url for _score, _idx, url in scored]


def filter_adversarial_urls(urls: list[str], *, job_id: str = "") -> list[str]:
    """URL-only fast path for the harvest flow (no titles yet): Tier A +
    authority re-rank. Tier B needs titles/snippets, applied by the caller
    when SERP metadata is available."""
    return filter_adversarial_candidates(
        [(u, "", "") for u in (urls or [])], job_id=job_id
    )


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


def _unwrap_engine_redirect(url: str) -> str:
    """Decode a search engine's redirect wrapper to the real destination.

    Session-331 (live T2): Bing wraps EVERY result as
    ``https://www.bing.com/ck/a?...&u=a1<base64url>`` where the ``u`` param is
    ``a1`` + base64url(destination). Without unwrapping, the destination is on
    ``bing.com`` and `_looks_like_result_url` rejects ALL of them — extraction
    returned ZERO URLs on a page with 10 real results (measured 2026-09-15:
    ziglang.org / github.com links were all present but wrapped).

    The href as it appears in the HTML is entity-escaped (``&amp;`` not ``&``),
    so the raw string is HTML-unescaped BEFORE parsing the query — otherwise
    ``parse_qsl`` sees one bogus ``amp;p`` param and never finds ``u``.
    Returns the url unchanged when it is not a recognised wrapper. Never raises.
    """
    try:
        import html as _html

        url = _html.unescape(url)
        parsed = urlparse(url)
        netloc = (parsed.netloc or "").lower()
        if "bing.com" not in netloc:
            return url
        for key, value in parse_qsl(parsed.query or "", keep_blank_values=True):
            if key == "u" and value.startswith("a1"):
                import base64

                raw = value[2:]
                # base64url -> bytes; pad to a multiple of 4.
                padded = raw + "=" * (-len(raw) % 4)
                try:
                    decoded = base64.urlsafe_b64decode(padded).decode(
                        "utf-8", errors="replace"
                    )
                except Exception:  # noqa: BLE001
                    return url
                if decoded.startswith("http"):
                    return decoded
    except Exception:  # noqa: BLE001 — a malformed wrapper is returned as-is
        pass
    return url


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
        url = _unwrap_engine_redirect(m.group(1))
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
    """Resolve the vision serving client through the ONE resolver (REQ-1).

    Mirrors ``fetch_vision.py``'s pattern: before this, discovery constructed
    the tier-3 ``LFMVLProvider`` directly via ``get_lfm_vl_provider()``, so a
    bound multimodal brain/tool was ignored and tier 3 was always used. The
    resolver preserves the ``read_text`` / ``analyze_screen`` method surface the
    fallback below relies on. Never raises (REQ-1 AC3) -- a missing/broken vision
    stack just means no fallback tier.
    """
    try:
        from backend.agent.inference.router import resolve_vision_client

        _resolution, client = resolve_vision_client()
        return client
    except Exception as exc:  # noqa: BLE001 -- degrade, never raise (REQ-1 AC3)
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
    # Session-332 (live T2): discovery emitted exactly ONE event, AFTER
    # open+type+navigate+settle. A cold browser pool makes that span 70s+
    # with zero frames, and the orchestrator's stall watchdog cancels a
    # silent step at _STALL_S (120s) — so a slow-but-healthy discovery could
    # be killed as if wedged. Announce each phase boundary so the watchdog
    # sees a live step. Best-effort: _announce never raises.
    _phase_total = 4
    try:
        _announce(_emit, job_id, "opening_browser", query, index=1, total=_phase_total)
        await session.open()
        if not session.available():
            logger.info(
                "[search_discovery] job_id=%s unavailable (browser session "
                "could not open) (REQ-19 AC8)",
                job_id,
            )
            return DiscoveryResult(unavailable=True)
        _announce(_emit, job_id, "browser_ready", query, index=2, total=_phase_total)

        # REQ-19 AC2: navigate to a search engine, enter the query, submit.
        # Per-action failures are recorded as observations by `act()` itself
        # (REQ-7 AC6) — a failed type/click here degrades to "no results
        # extracted" below, it does not raise.
        #
        # Session-331 (live T2): type-then-submit is fragile — search engines
        # rewrite their submit markup and their boxes submit via JS, so the
        # click on #sb_form_go / button[type=submit] matched ZERO elements
        # (measured 2026-09-15) and the query never fired; Enter in the box did
        # not submit either. Driving the RESULTS URL directly is
        # markup-independent and returns a real results page (verified live:
        # "About 47,200 results" with ziglang.org / github.com links). We still
        # type the query first so the visible browser panel shows the real
        # search interaction, then navigate the results URL to guarantee the
        # submission.
        try:
            await session.act(VisionAction(
                kind="type", target=_SEARCH_INPUT_SELECTOR, value=query,
                reason="enter search query (REQ-19)",
            ))
        except Exception:  # noqa: BLE001 — the direct URL below still submits
            pass
        await session.act(VisionAction(
            kind="navigate", target=_results_url(query),
            reason="submit search via results URL (REQ-19)",
        ))
        html = await session.settle()
        _announce(_emit, job_id, "submit_search", query, index=3, total=_phase_total)

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

        urls = _extract_urls_from_html(html, max_results * 3 + 10)
        used_fallback = False
        if not urls:
            # REQ-19 AC2 fallback: vision reads the rendered frame when DOM
            # extraction yields nothing — the reason vision exists here.
            prov = provider if provider is not None else _get_provider()
            if prov is not None:
                try:
                    img = await session.screenshot()
                    if img is not None:
                        # F2 (REQ-1, T1): the provider's read_text /
                        # analyze_screen are SYNCHRONOUS blocking HTTP calls.
                        # Called inline from this already-running async function
                        # they block the event loop for every concurrent task
                        # (WS, audio, other crawls) for up to the provider
                        # timeout. Dispatch via asyncio.to_thread exactly as
                        # fetch_vision._suggest_action does, so a slow/hung vision
                        # server stalls only this discovery, never the reactor.
                        text = await asyncio.to_thread(prov.read_text, img) or ""
                        if not text.strip():
                            text = await asyncio.to_thread(
                                prov.analyze_screen,
                                img,
                                "List the URLs or article titles of the search "
                                "results visible on this page.",
                            ) or ""
                        urls = _extract_urls_from_text(text, max_results * 3 + 10)
                        used_fallback = bool(urls)
                except Exception as exc:  # noqa: BLE001 — fallback is best-effort
                    logger.info(
                        "[search_discovery] job_id=%s vision fallback failed: %s",
                        job_id, exc,
                    )
        # T9 (REQ-9): Hybrid Adversarial SEO filter runs BEFORE crawl/vision
        # resources are spent. URL-only Tier A here; Tier B applies when the
        # caller supplies titles/snippets via filter_adversarial_candidates.
        raw_count = len(urls)
        urls = filter_adversarial_urls(urls, job_id=job_id)[:max_results]
        logger.info(
            "[search_discovery] job_id=%s query=%s discovered=%d fallback=%s "
            "(REQ-19 AC1/AC2/AC4, REQ-16; REQ-9 raw=%d kept=%d)",
            job_id, query[:60], len(urls), used_fallback, raw_count, len(urls),
        )
        _announce(_emit, job_id, "results_extracted", query, index=4, total=_phase_total)
        return DiscoveryResult(urls=urls, used_vision_fallback=used_fallback)
    except Exception as exc:  # noqa: BLE001 — REQ-19 must never fail the run
        logger.warning("[search_discovery] job_id=%s error=%s (REQ-19 AC8)", job_id, exc)
        return DiscoveryResult(unavailable=True)
    finally:
        try:
            await session.close()
        except Exception as exc:  # noqa: BLE001
            logger.info("[search_discovery] session close failed job_id=%s: %s", job_id, exc)


def _announce(_emit, job_id: str, kind: str, reason: str,
              *, index: int = 1, total: int = 1) -> None:
    """Best-effort action announcement, same shape as `_vision_fetch`'s
    CRAWLER_VISION_ACTION payload (REQ-11 AC4) — never breaks discovery.

    ``index``/``total`` are the phase counters (Session-332): the orchestrator's
    stall watchdog resets on every event, so announcing each phase keeps a
    slow-but-healthy discovery from being cancelled as if wedged.
    """
    if _emit is None:
        return
    try:
        _emit("CRAWLER_VISION_ACTION", {
            "job_id": job_id, "url": _SEARCH_ENGINE_URL, "kind": kind,
            "reason": reason, "action_index": index, "total": total,
        })
    except Exception:  # noqa: BLE001
        pass


__all__ = [
    "DiscoveryResult",
    "click_discovered_result",
    "discover_urls_via_vision",
    "filter_adversarial_candidates",
    "filter_adversarial_urls",
]
