"""Contract tests for fetch capabilities + vision frame extraction (T7/T12a/T12b).

Hermetic: no live web, no real vision server. The crawler path is stubbed at
CrawlOrchestrator.fetch_url; the vision provider is a fake injected into
extract_page_frames.
"""

import asyncio
import re

import pytest

from backend.crawler.capabilities import (
    CAPABILITIES,
    FetchCrawlCapability,
    FetchOutcome,
    get_capability,
    register_capability,
    register_default_capabilities,
)
from backend.crawler.usability import UsabilityReason
from backend.vision.frame_extraction import (
    BudgetExceeded,
    ContentOrigin,
    SessionBounds,
    extract_page_frames,
    reconcile,
    under_capture_heuristic,
)


# ---------------------------------------------------------------------------
# T7 — capabilities
# ---------------------------------------------------------------------------

class _Page:
    def __init__(self, markdown="useful content here " * 5, error=None):
        self.url = "https://example.com/"
        self.title = "Example"
        self.markdown = markdown
        self.html = f"<html><body><p>{markdown}</p></body></html>"
        self.metadata = {}
        self.error = error
        self.html_bytes = len(self.html)


class _OkResult:
    error = None
    pages = [_Page()]


class _ErrResult:
    error = "fetch failed: boom"
    pages = []


class _ThinResult:
    error = None
    pages = [_Page(markdown="hi")]  # far below MIN_CONTENT_CHARS=20


def _patch_fetch_url(monkeypatch, result):
    """Stub CrawlOrchestrator.fetch_url to return `result` (never hits network)."""
    import backend.crawler.orchestrator as orch_mod

    async def _fake_fetch_url(self_or_none, url, **kwargs):
        return result

    monkeypatch.setattr(orch_mod.CrawlOrchestrator, "fetch_url", _fake_fetch_url)


def test_fetch_crawl_wraps_orchestrator(monkeypatch):
    """fetch_one routes through CrawlOrchestrator.fetch_url (REQ-6 AC2)."""
    import backend.crawler.orchestrator as orch_mod

    calls = []

    async def _fake_fetch_url(self_or_none, url, **kwargs):
        calls.append((url, kwargs))
        return _OkResult()

    monkeypatch.setattr(orch_mod.CrawlOrchestrator, "fetch_url", _fake_fetch_url)

    cap = FetchCrawlCapability()
    outcome = asyncio.run(cap.fetch_one("https://example.com/", "goal", "job-1"))
    assert isinstance(outcome, FetchOutcome)
    assert outcome.capability == "fetch.crawl"
    assert outcome.url == "https://example.com/"
    assert outcome.verdict.usable is True
    assert outcome.page is not None
    assert calls and calls[0][0] == "https://example.com/"
    assert calls[0][1]["job_id"] == "job-1"


def test_fetch_crawl_error_page_is_none(monkeypatch):
    """Fetch failure -> page None, verdict unusable (REQ-6, never raises)."""
    _patch_fetch_url(monkeypatch, _ErrResult())
    cap = FetchCrawlCapability()
    outcome = asyncio.run(cap.fetch_one("https://example.com/", "goal", "job-2"))
    assert outcome.page is None
    assert outcome.verdict.usable is False


def test_fetch_crawl_unusable_page_detected(monkeypatch):
    """Page below MIN_CONTENT_CHARS -> unusable verdict (page_is_usable)."""
    _patch_fetch_url(monkeypatch, _ThinResult())
    cap = FetchCrawlCapability()
    outcome = asyncio.run(cap.fetch_one("https://example.com/", "goal", "job-3"))
    assert outcome.verdict.usable is False
    assert outcome.verdict.reason == UsabilityReason.TOO_SHORT


def test_registry_register_and_get():
    """register/get round-trips; unknown name -> KeyError (REQ-6 AC3)."""
    cap = FetchCrawlCapability()
    register_capability(cap)
    assert get_capability("fetch.crawl") is cap
    with pytest.raises(KeyError):
        get_capability("no.such.capability")


def test_register_default_capabilities_has_crawl():
    """fetch.crawl always registered; fetch.vision best-effort."""
    reg = register_default_capabilities()
    assert "fetch.crawl" in reg
    assert "fetch.crawl" in CAPABILITIES


def test_register_default_never_breaks_on_vision_missing():
    """fetch.vision import failing must not break fetch.crawl registration.

    backend/vision/fetch_vision does not exist in this build yet, so the
    best-effort registration inside register_default_capabilities exercises
    its try/except path for real: fetch.crawl still lands, no raise.
    """
    from backend.crawler import capabilities as cap_mod

    cap_mod.CAPABILITIES.clear()
    try:
        reg = cap_mod.register_default_capabilities()
    finally:
        cap_mod.CAPABILITIES.clear()
        register_default_capabilities()  # restore shared registry
    assert "fetch.crawl" in reg
    assert "fetch.crawl" in CAPABILITIES


# ---------------------------------------------------------------------------
# T12a — frame extraction loop
# ---------------------------------------------------------------------------

class _FakeProvider:
    """Fake vision provider. triage_map: scroll -> verdict; texts per scroll.

    ASYNC (matching frame_extraction.VisionProvider): extract_page_frames
    itself became async so it can be awaited from inside the already-running
    event loop of FetchVisionCapability.fetch_one (see
    backend/vision/session_vision_adapter.py for the full rationale) — every
    call site here now goes through asyncio.run().
    """

    def __init__(self, triage_map, texts=None, analyze_text=""):
        self.triage_map = triage_map
        self.texts = texts or {}
        self.analyze_text = analyze_text
        self.describe_calls = 0
        self.read_calls = 0

    async def describe_live_frame(self, prompt):
        self.describe_calls += 1
        # scroll is the number following "scroll position" in the prompt
        m = re.search(r"scroll position (\d+)", prompt)
        scroll = int(m.group(1)) if m else -1
        return self.triage_map.get(scroll, "no_new_content")

    async def read_text(self):
        self.read_calls += 1
        return self.texts.get("read", "")

    async def analyze_screen(self, question):
        return self.analyze_text

    async def screenshot_to_bytes(self):
        return b""


def test_extract_frames_triage_and_full_extract():
    """new_content frames get read_text; no_new_content stops loop (D8)."""
    provider = _FakeProvider(
        triage_map={0: "new_content", 1: "new_content", 2: "no_new_content"},
        texts={"read": "article text"},
    )
    frames = asyncio.run(extract_page_frames(provider, "research goal", SessionBounds()))
    assert len(frames) == 2
    assert frames[0].triage_verdict == "new_content"
    assert frames[0].text == "article text"
    assert frames[1].triage_verdict == "new_content"
    assert provider.read_calls == 2


def test_extract_frames_challenge_stops():
    """Challenge frame recorded with empty text, loop stops (REQ-7)."""
    provider = _FakeProvider(
        triage_map={0: "challenge"},
        texts={"read": "should not be read"},
    )
    frames = asyncio.run(extract_page_frames(provider, "goal", SessionBounds()))
    assert len(frames) == 1
    assert frames[0].triage_verdict == "challenge"
    assert frames[0].text == ""
    assert provider.read_calls == 0


def test_extract_frames_respects_max_extractions():
    """Never exceeds bounds.max_extractions (REQ-17 AC8) — BudgetExceeded."""
    provider = _FakeProvider(
        triage_map={i: "new_content" for i in range(12)},
        texts={"read": "x"},
    )
    with pytest.raises(BudgetExceeded):
        asyncio.run(extract_page_frames(provider, "goal", SessionBounds(max_extractions=3)))
    assert provider.read_calls == 3


def test_extract_frames_provider_failure_degrades():
    """Provider exception in triage -> treated as no_new_content (no crash)."""

    class _BrokenProvider(_FakeProvider):
        async def describe_live_frame(self, prompt):
            raise RuntimeError("vision server down")

    frames = asyncio.run(extract_page_frames(_BrokenProvider({}), "goal", SessionBounds()))
    assert frames == []


# ---------------------------------------------------------------------------
# T12b — reconciliation
# ---------------------------------------------------------------------------

def test_reconcile_both_similar_reconciled():
    """Both present + similar -> RECONCILED, merged = longer (D9)."""
    crawl = "quantum verification protocols run on hardware"
    vision = "quantum verification protocols run on hardware today"
    rec = reconcile(crawl, vision, "https://example.com/")
    assert rec.origin == ContentOrigin.RECONCILED
    assert rec.merged_text == vision  # longer
    assert rec.disagreement is None


def test_reconcile_crawl_text_vision_empty():
    """Crawl has text, vision empty -> CRAWL."""
    rec = reconcile("real content here", "", "https://example.com/")
    assert rec.origin == ContentOrigin.CRAWL
    assert rec.merged_text == "real content here"
    assert rec.disagreement is None


def test_reconcile_vision_text_crawl_empty():
    """Vision has text, crawl empty -> VISION + disagreement (REQ-17 AC5)."""
    rec = reconcile("", "visible page text", "https://example.com/")
    assert rec.origin == ContentOrigin.VISION
    assert rec.merged_text == "visible page text"
    assert rec.disagreement == "vision_has_text_crawl_empty"


def test_reconcile_both_diverge_records_disagreement():
    """Both present but dissimilar -> disagreement diagnostic, never silent."""
    crawl = "quantum verification hardware pipeline results"
    vision = "weather forecast sunny skies tomorrow afternoon"
    rec = reconcile(crawl, vision, "https://example.com/")
    assert rec.origin == ContentOrigin.RECONCILED
    assert rec.disagreement is not None


def test_reconcile_neither_empty_record():
    rec = reconcile(None, None, "https://example.com/")
    assert rec.origin == ContentOrigin.CRAWL
    assert rec.merged_text == ""


def test_under_capture_heuristic():
    """Thin markdown over big HTML -> True; rich markdown -> False (REQ-17 AC7)."""
    assert under_capture_heuristic("tiny", "<html>" + "x" * 25_000 + "</html>") is True
    assert under_capture_heuristic("", "<html>big</html>") is True
    assert under_capture_heuristic("substantial content " * 60, "<html>big</html>") is False
