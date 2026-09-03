"""
Unit tests for backend/crawler/usability.py — REQ-1 (one shared predicate).

Pins the acceptance criteria of specs/vision-browser-websearch/requirements.md:

  AC1  exactly one predicate; every layer judges fetch success through it.
  AC2  unusable when: markdown empty / below minimum content length / bot
       challenge interstitial.
  AC3  ``error is None`` alone is insufficient evidence of usability.
  AC4  every unusable judgement records the specific reason on the verdict.

Edge cases pinned per requirements.md:
  - whitespace-only markdown -> too_short (not usable)
  - challenge boilerplate -> challenge (not too_short) — the distinction
    drives different recovery
  - legitimately short pages (definitions/stubs) are NOT rejected
  - structural challenge markers in HTML, not prose alone
"""
from __future__ import annotations

import pytest

from backend.crawler.crawler_engine import PageData
from backend.crawler.usability import (
    MIN_CONTENT_CHARS,
    UsabilityReason,
    page_is_usable,
)


def _page(**kw) -> PageData:
    """Build a default-usable page; override fields per test."""
    base = dict(
        url="https://example.gov/doc",
        title="Doc",
        markdown="The quantum model shows X. It was verified by experiment Y.",
        html="<html><body><p>The quantum model shows X.</p></body></html>",
        metadata={},
    )
    base.update(kw)
    return PageData(**base)


# ── AC1/AC2: usable vs unusable ───────────────────────────────────────────

def test_usable_page():
    v = page_is_usable(_page())
    assert v.usable is True
    assert v.reason == UsabilityReason.OK


def test_empty_markdown_is_unusable():
    v = page_is_usable(_page(markdown=""))
    assert v.usable is False
    assert v.reason == UsabilityReason.EMPTY


def test_whitespace_only_markdown_is_too_short():
    """Edge: whitespace-only markdown -> too_short, not usable."""
    v = page_is_usable(_page(markdown="   \n\t  "))
    assert v.usable is False
    assert v.reason == UsabilityReason.TOO_SHORT


def test_below_minimum_length_is_too_short():
    v = page_is_usable(_page(markdown="short"))
    assert v.usable is False
    assert v.reason == UsabilityReason.TOO_SHORT


def test_short_but_legitimate_page_not_rejected():
    """Edge: legitimately short pages (definitions/stubs) stay usable — the
    threshold must not reject real content. A terse dictionary-style entry is
    the canonical stub; it must pass despite being far below an article's
    length."""
    v = page_is_usable(_page(markdown="Ajax: a Greek hero of the Trojan War."))
    assert v.usable is True, v


# ── AC2/AC4: challenge detection ──────────────────────────────────────────

def test_html_challenge_interstitial_is_unusable():
    v = page_is_usable(_page(
        html=(
            "<html><title>Just a moment...</title>"
            '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
            "</html>"
        ),
        markdown="",
    ))
    assert v.usable is False
    assert v.reason == UsabilityReason.CHALLENGE


def test_error_challenge_is_unusable():
    v = page_is_usable(_page(error="challenge"))
    assert v.usable is False
    assert v.reason == UsabilityReason.CHALLENGE


def test_challenge_boilerplate_in_markdown_is_challenge_not_too_short():
    """Edge: markdown consisting solely of challenge boilerplate -> challenge,
    not too_short — the distinction drives different recovery."""
    v = page_is_usable(_page(
        markdown="Verify you are human to continue. Redirecting to challenge-form.",
        html=None,
    ))
    assert v.usable is False
    assert v.reason == UsabilityReason.CHALLENGE


def test_prose_mention_of_just_a_moment_not_a_challenge():
    """Edge: legitimate prose containing 'just a moment' must not be judged a
    challenge — detection keys on structural markers, not prose alone."""
    v = page_is_usable(_page(
        markdown="Just a moment ago the experiment confirmed the result.",
        html=None,
    ))
    assert v.usable is True, v


# ── AC3: error is None is NOT sufficient evidence ─────────────────────────

def test_transport_error_is_unusable_even_with_markdown():
    """A page that carried an error is unusable even if markdown is present —
    error is None alone is insufficient evidence of usability (AC3)."""
    v = page_is_usable(_page(error="status=403"))
    assert v.usable is False
    assert v.reason == UsabilityReason.TRANSPORT_ERROR


def test_error_none_but_empty_markdown_still_unusable():
    """error=None must not by itself make a page usable (AC3)."""
    v = page_is_usable(_page(markdown="", error=None))
    assert v.usable is False
    assert v.reason == UsabilityReason.EMPTY


# ── AC4: specific reason recorded ─────────────────────────────────────────

def test_reason_is_recorded_on_unusable_verdict():
    cases = [
        (_page(markdown=""), UsabilityReason.EMPTY),
        (_page(markdown="tiny"), UsabilityReason.TOO_SHORT),
        (_page(error="challenge"), UsabilityReason.CHALLENGE),
        (_page(error="boom"), UsabilityReason.TRANSPORT_ERROR),
    ]
    for page, expected in cases:
        v = page_is_usable(page)
        assert v.reason == expected, f"{page!r}: {v}"
        assert v.detail, f"detail must be populated for {expected}"


# ── configurable threshold ────────────────────────────────────────────────

def test_min_content_chars_is_configurable():
    assert isinstance(MIN_CONTENT_CHARS, int)
    assert MIN_CONTENT_CHARS > 0
