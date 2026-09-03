"""
One shared definition of a usable page (REQ-1).

The three-layer disagreement this module eliminates:

    crawl_runner.py:347   `if p.markdown`          -> counted 0 usable pages
    orchestrator.py:204   `if not p.error`         -> counted 2 usable pages
    rerank.py:141         score >= 0.30            -> counted 0 usable pages

…all judged the SAME fetch differently on the traced Palworld run. Every
layer that judges fetch success must call :func:`page_is_usable` and nothing
else — introducing a fourth local predicate repeats the defect.

This module is also the canonical home of bot-challenge detection. The
detection previously lived at ``crawl_runner.py:453`` with exactly one caller
inside the plain-HTTP fallback; the primary Playwright path had zero awareness
(REQ-4). It moved here so the shared predicate can judge challenges and so the
primary path can reach it without importing crawl_runner.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .crawler_engine import PageData

# Minimum content length for a page to be judged usable (REQ-1 AC2). Tuned
# from REQ-16 AC2 data — start conservative (definition/stub pages must not be
# rejected), raise from measured empty-extraction distributions. 20 chars
# rejects only near-empty shells (redirects, loading stubs, error fragments);
# genuine definitions/stubs are far longer.
MIN_CONTENT_CHARS = int(os.environ.get("CRAWL_MIN_CONTENT_CHARS", "20"))


class UsabilityReason(str, Enum):
    """Why a page is or is not usable (REQ-1 AC4)."""

    OK = "ok"
    EMPTY = "empty"                # no markdown at all
    TOO_SHORT = "too_short"        # below MIN_CONTENT_CHARS
    CHALLENGE = "challenge"        # bot interstitial (REQ-4)
    TRANSPORT_ERROR = "transport_error"


@dataclass(frozen=True)
class UsabilityVerdict:
    usable: bool
    reason: UsabilityReason
    detail: str = ""  # e.g. "status=403", "markdown len=0"


# ── Bot-challenge signatures (REQ-4) ──────────────────────────────────────
# Full set for HTML, where structural markers (challenge-platform script,
# challenge-form, turnstile widget) make detection unambiguous.
_BOT_CHALLENGE_SIGNATURES = (
    # Cloudflare: interstitial JS challenge, the "Just a moment..." page
    "cf-chl-",
    "challenge-platform",
    "cf-mitigated",
    "__cf_chl",
    "just a moment...",
    # Turnstile (Cloudflare's anti-bot widget) — a CAPTCHA the crawler cannot
    # solve; content behind it is NOT the page's real content.
    "cf-turnstile",
    "turnstile",
    "challenges.cloudflare.com",
    # Generic bot-challenge interstitials
    "challenge-form",
    "verify you are human",
    "you are being redirected",
)

# Structural-only subset for markdown. Prose strings like "just a moment..."
# are excluded: a legitimate page whose body text contains that phrase must
# not be misjudged (REQ-4 edge case). Challenge boilerplate in stripped text
# still carries the structural markers.
_MARKDOWN_CHALLENGE_SIGNATURES = (
    "cf-chl-",
    "challenge-platform",
    "cf-mitigated",
    "__cf_chl",
    "cf-turnstile",
    "turnstile",
    "challenges.cloudflare.com",
    "challenge-form",
    "verify you are human",
    "you are being redirected",
)


def is_challenge_page(html: Optional[str]) -> bool:
    """True when *html* is a bot-challenge interstitial (Cloudflare/Turnstile).

    A challenged page is NOT the page's real content — judging it usable would
    feed the challenge's boilerplate into evidence. ``None``/empty input is
    never a challenge.
    """
    if not html:
        return False
    _low = html.lower()
    return any(_sig in _low for _sig in _BOT_CHALLENGE_SIGNATURES)


def text_is_challenge(text: Optional[str]) -> bool:
    """True when extracted TEXT is challenge boilerplate rather than content.

    Public because evidence reconciliation needs it too: a challenge page the
    crawler wrongly extracted must not be able to win a merge against real
    content just by being longer (REQ-17 AC5 / BT-9). Uses the structural-only
    signature set, so a legitimate page whose prose contains "just a moment..."
    is not misjudged.
    """
    if not text:
        return False
    _low = text.lower()
    return any(_sig in _low for _sig in _MARKDOWN_CHALLENGE_SIGNATURES)


def _markdown_is_challenge(markdown: str) -> bool:
    return text_is_challenge(markdown)


def page_is_usable(page: PageData) -> UsabilityVerdict:
    """Judge whether *page* is usable — the single predicate (REQ-1 AC1).

    Order of judgement:
      1. challenge (structural markers in HTML, or error="challenge")
      2. transport error (any other ``page.error`` — REQ-1 AC3: ``error is
         None`` is NOT sufficient evidence of usability on its own)
      3. empty markdown (no text at all)
      4. too short (whitespace-only, or below MIN_CONTENT_CHARS)
      else usable.

    Every unusable verdict records its specific reason in ``detail`` for
    per-URL outcome logging (REQ-1 AC4 / REQ-16 AC2).
    """
    if page.error == "challenge":
        return UsabilityVerdict(
            False, UsabilityReason.CHALLENGE, "error=challenge",
        )
    if page.html and is_challenge_page(page.html):
        return UsabilityVerdict(
            False, UsabilityReason.CHALLENGE, "structural challenge marker",
        )
    if page.markdown and _markdown_is_challenge(page.markdown):
        return UsabilityVerdict(
            False, UsabilityReason.CHALLENGE, "challenge boilerplate in text",
        )
    if page.error:
        return UsabilityVerdict(
            False, UsabilityReason.TRANSPORT_ERROR, "error=%s" % str(page.error)[:80],
        )
    if not page.markdown:
        return UsabilityVerdict(False, UsabilityReason.EMPTY, "markdown len=0")
    _stripped = page.markdown.strip()
    if not _stripped:
        return UsabilityVerdict(
            False, UsabilityReason.TOO_SHORT, "whitespace-only markdown",
        )
    if len(_stripped) < MIN_CONTENT_CHARS:
        return UsabilityVerdict(
            False,
            UsabilityReason.TOO_SHORT,
            "markdown len=%d < %d" % (len(_stripped), MIN_CONTENT_CHARS),
        )
    return UsabilityVerdict(True, UsabilityReason.OK, "")
