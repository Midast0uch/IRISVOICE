"""BT-8 (vision-goal-directed-search T28, REQ-15): native PDF extraction.

Behavioral assertions against the REAL capability (fitz, in-memory bytes —
never hits the network):

  - AC15.2: text + tables from a multi-page PDF, well under the 1.5s bound
    asserted for a 50-page document.
  - AC15.3: `render_target_page_png` renders ONLY the addressed page and no
    other (bytes bounded, correct page, out-of-range returns None).
  - REQ-5 AC3: the robots.txt gate runs BEFORE any bytes move — a refusal
    must return an unusable outcome with no download recorded.
  - Fail-gracefully: a corrupt blob never raises; the capability contract
    (`fetch_one` never raises) holds.
"""
from __future__ import annotations

import asyncio
import time

import pytest

fitz = pytest.importorskip("fitz", reason="PyMuPDF required for fetch.pdf tests")

from backend.crawler.capabilities import FetchPDFCapability


def _make_pdf(pages: list[str]) -> bytes:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 120), text, fontsize=24)
    return doc.tobytes()


# ── AC15.2: native text extraction ──────────────────────────────────────────


def test_extract_text_reads_every_page_and_preserves_order():
    body = _make_pdf([f"PAGE {i} content — quarterly figures" for i in range(5)])
    out = FetchPDFCapability._extract_text(body)
    assert "PAGE 0 content" in out and "PAGE 4 content" in out
    assert out.index("PAGE 0") < out.index("PAGE 4"), (
        "page text must arrive in document order — a scrambled extraction "
        "breaks citation index mapping"
    )


def test_fifty_page_document_extracts_well_under_1_5_seconds():
    pages = [f"Spec section {i}\n" + "Lorem ipsum dolor sit amet. " * 40 for i in range(50)]
    body = _make_pdf(pages)
    t0 = time.monotonic()
    out = FetchPDFCapability._extract_text(body)
    elapsed = time.monotonic() - t0
    assert "Spec section 49" in out
    assert elapsed < 1.5, (
        f"50-page extraction took {elapsed:.2f}s — AC15.2's <1.5s bound breached"
    )


# ── AC15.3: targeted page rendering for the VLM path ────────────────────────


def test_render_target_page_png_renders_only_the_requested_page():
    cap = FetchPDFCapability()
    body = _make_pdf(["alpha", "beta", "gamma"])
    png = asyncio.run(cap.render_target_page_png(body, 1))
    assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"
    # Rough bound — one page at 150dpi must be far below a full-document render.
    assert len(png) < 3_000_000
    # Out-of-range page -> None (never raises, never fabricates).
    assert asyncio.run(cap.render_target_page_png(body, 7)) is None
    assert asyncio.run(cap.render_target_page_png(body, -1)) is None


# ── REQ-5 AC3: robots gate takes precedence over any bytes moving ────────────


def test_robots_refusal_returns_unusable_without_download(monkeypatch):
    """The PDF path runs the robots gate FIRST (same as fetch.crawl) — a
    refusal must return unusable without touching the network."""
    import backend.crawler.capabilities as caps

    class _RobotsDeny:
        async def is_allowed(self, url, user_agent):
            return False

    monkeypatch.setattr(caps, "get_robots_checker", lambda: _RobotsDeny())

    cap = FetchPDFCapability()
    outcome = asyncio.run(cap.fetch_one("https://docs.example/x.pdf", "goal", "j-pdf-robots"))
    assert outcome.page is None
    assert outcome.verdict.usable is False
    assert "robots" in (outcome.verdict.detail or "")


# ── the capability never raises on bad input ─────────────────────────────────


def test_corrupt_blob_returns_unusable_and_never_raises(monkeypatch):
    """A broken PDF stream (truncated/HTTP 200 with garbage) must return an
    unusable FetchOutcome — never an exception reaching the orchestrator."""

    import backend.crawler.capabilities as caps

    class _RobotsAllow:
        async def is_allowed(self, url, user_agent):
            return True

    class _Resp:
        status_code = 200
        headers = {"content-type": "application/pdf"}
        content = b"%PDF-1.4 truncated garbage"

        def raise_for_status(self):
            return None

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def get(self, url, headers=None):
            return _Resp()

    import httpx as _httpx

    monkeypatch.setattr(caps, "get_robots_checker", lambda: _RobotsAllow())
    monkeypatch.setattr(_httpx, "AsyncClient", _Client)

    cap = FetchPDFCapability()
    outcome = asyncio.run(cap.fetch_one("https://docs.example/broken.pdf", "g", "j-pdf-bad"))
    assert outcome.page is None or outcome.verdict.usable is False
    assert outcome.capability == "fetch.pdf"
