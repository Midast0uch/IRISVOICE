"""REQ-10 (T12) contract: bot-challenge detection + penalize.

Pins the three T12 behaviors:
  1. `_is_challenge_page` recognizes Cloudflare/Turnstile interstitial
     signatures (a challenged page is NOT content).
  2. `_plain_http_fetch` marks a challenged page's error and does NOT save it
     to the capture store.
  3. `penalize_url(..., last_error="challenge")` records the challenge reason
     on the source (credibility halved, distinguishable from crawl_failed).
"""
import asyncio
import json

import pytest

from backend.crawler.crawl_runner import _is_challenge_page
from backend.crawler.source_registry import SourceRegistry


# ── 1. Detection ─────────────────────────────────────────────────────────

def test_detects_cloudflare_challenge():
    """A Cloudflare 'Just a moment...' interstitial is detected."""
    html = (
        "<html><title>Just a moment...</title>"
        '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
        "</html>"
    )
    assert _is_challenge_page(html) is True


def test_detects_turnstile():
    """A Turnstile CAPTCHA interstitial is detected."""
    html = (
        "<html><body>"
        '<div class="cf-turnstile" data-sitekey="abc"></div>'
        "<script src=\"https://challenges.cloudflare.com/turnstile/v0/api.js\"></script>"
        "</body></html>"
    )
    assert _is_challenge_page(html) is True


def test_does_not_flag_normal_page():
    """Real content with none of the signatures is NOT a challenge."""
    html = "<html><title>Voice assistants explained</title><p>Real content here.</p></html>"
    assert _is_challenge_page(html) is False


def test_empty_html_not_challenge():
    assert _is_challenge_page("") is False
    assert _is_challenge_page(None) is False


# ── 2. Fetch skips saving challenged pages ────────────────────────────────

def test_plain_fetch_marks_challenge_and_skips_save(monkeypatch):
    """A challenged page gets error='challenge' and the capture store is NOT
    written (its boilerplate is not content)."""
    from backend.crawler import crawl_runner
    from backend.crawler.capture_store import CaptureStore

    saved = []

    class _FakeStore(CaptureStore):
        def save(self, job_id=None, page_number=None, url=None, html=None, **kw):
            saved.append((url, html))

    monkeypatch.setattr(crawl_runner, "_is_challenge_page", lambda html: True)
    monkeypatch.setattr("backend.crawler.capture_store.get_capture_store",
                        lambda: _FakeStore())

    urls = ["https://example.com/blocked"]
    pages, hars = asyncio.run(crawl_runner._plain_http_fetch(urls, job_id="j1"))

    assert len(pages) == 1
    assert pages[0].error == "challenge", pages[0].error
    assert hars[0]["error"] == "challenge", hars[0]["error"]
    assert saved == [], f"challenge page must not be saved: {saved}"


# ── 3. Penalize records the challenge reason ──────────────────────────────

def test_penalize_challenge_records_reason(tmp_path, monkeypatch):
    """penalize_url with last_error='challenge' halves credibility and records
    the challenge reason — distinguishable from crawl_failed."""
    reg = SourceRegistry()
    # Seed one entry for the URL under a topic.
    store_key = "topic:auth"
    reg._set_store(store_key, json.dumps([
        {"url": "https://example.com/a", "credibility": 0.8, "last_error": None}
    ]))

    reg.penalize_url("https://example.com/a", topics=["auth"], last_error="challenge")

    entries = json.loads(reg._get_store(store_key))
    assert entries[0]["credibility"] == 0.4, entries[0]  # halved
    assert entries[0]["last_error"] == "challenge", entries[0]


# ── REQ-11 (T14 / CT-C3): single CRAWLER_PAGE_FETCHED emission authority ────

def test_ctc3_single_emission_dedup():
    """The same (job_id, page_number) emits CRAWLER_PAGE_FETCHED exactly once.

    The crawl4ai worker path and the plain-HTTP fallback can both reach the
    page emitter for the same page (worker timeout -> fallback re-fetches the
    same URLs). First emitter wins; later duplicates are dropped.
    """
    from backend.crawler.orchestrator import CrawlOrchestrator

    emitted = []
    orch = CrawlOrchestrator(planner=None)
    cb = orch._page_emitter(lambda e, d: emitted.append((e, d)), job_id="j1")

    # Same page via both paths (the duplicate scenario).
    cb("https://a.gov/1", 1, 3)
    cb("https://a.gov/1", 1, 3)  # duplicate (fallback re-fetch)
    cb("https://a.gov/2", 2, 3)  # distinct page — must emit

    page_events = [d for e, d in emitted if e == "CRAWLER_PAGE_FETCHED"]
    assert len(page_events) == 2, f"expected 2 emits, got {len(page_events)}"
    pages = {(d["job_id"], d["page_number"]) for d in page_events}
    assert pages == {("j1", 1), ("j1", 2)}, pages
    # The duplicate carried the SAME bytes (first-wins, url intact).
    assert page_events[0]["url"] == "https://a.gov/1"


def test_ctc3_dedup_is_per_emitter_isolated():
    """Dedup state is scoped to one emitter (one crawl job) — a second job's
    emitter is not polluted by the first job's seen-pages."""
    from backend.crawler.orchestrator import CrawlOrchestrator

    orch = CrawlOrchestrator(planner=None)
    e1 = []
    e2 = []
    cb1 = orch._page_emitter(lambda e, d: e1.append((e, d)), job_id="j1")
    cb2 = orch._page_emitter(lambda e, d: e2.append((e, d)), job_id="j2")

    cb1("https://a.gov/1", 1, 2)
    cb2("https://a.gov/1", 1, 2)  # same page_number, DIFFERENT job — must emit

    assert len([d for e, d in e1 if e == "CRAWLER_PAGE_FETCHED"]) == 1
    assert len([d for e, d in e2 if e == "CRAWLER_PAGE_FETCHED"]) == 1
