"""T10 (REQ-15): native PDF extraction capability (fetch.pdf).

Pins:
- Available + named fetch.pdf; lazily imports fitz (never at module load).
- GETs bytes, parses text with PyMuPDF, returns usable PageData markdown.
- Fast path: a synthetic 50-page document extracts well inside the 1.5s AC.
- Robots-gated before any download (REQ-5 AC3, same gate as fetch.crawl).
- Targeted single-page PNG render helper for VLM chart inspection (AC15.3).
- Never raises (REQ-8/AC8 pattern): transport/parse failures return an
  unusable FetchOutcome, not an exception.

Hermetic: httpx GET is stubbed; no live web, no PDF download.
"""
from __future__ import annotations

import asyncio
import io

from backend.crawler.capabilities import (
    CAPABILITIES,
    FetchPDFCapability,
    get_capability,
    register_capability,
)
from backend.crawler.usability import UsabilityReason


def _make_pdf_bytes(n_pages: int = 50, text: str = "Requirement AC1: the system shall parse this text.") -> bytes:
    import fitz

    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"page {i + 1}: {text}")
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def _fake_httpx_get(pdf_bytes: bytes, content_type: str = "application/pdf"):
    """Patch httpx.AsyncClient.get to return the synthetic PDF bytes."""
    import httpx

    class _Resp:
        status_code = 200
        headers = {"content-type": content_type}
        content = pdf_bytes

        def raise_for_status(self):
            pass

    async def _get(self, *a, **k):
        return _Resp()

    return _get


def test_fetch_pdf_registered_and_available():
    """REQ-15 AC15.1: fetch.pdf exists in the registry and is available."""
    register_capability(FetchPDFCapability())
    cap = get_capability("fetch.pdf")
    assert cap.name == "fetch.pdf"
    assert asyncio.run(cap.available()) is True


def test_fetch_pdf_extracts_text_fast(monkeypatch, tmp_path):
    """AC15.1/AC15.2: downloads bytes over httpx and returns usable markdown
    from a 50-page document in under 1.5 s, no browser involved."""
    pdf_bytes = _make_pdf_bytes(50)
    monkeypatch.setattr("httpx.AsyncClient.get", _fake_httpx_get(pdf_bytes))

    cap = FetchPDFCapability()
    outcome = asyncio.run(cap.fetch_one("https://example.com/spec.pdf", "", "j-pdf"))

    assert outcome.capability == "fetch.pdf"
    assert outcome.verdict.usable is True
    assert outcome.page is not None
    assert "page 1: Requirement AC1" in outcome.page.markdown
    assert "page 50: Requirement AC1" in outcome.page.markdown
    assert outcome.duration_ms < 1500, (
        f"50-page extraction took {outcome.duration_ms}ms — the 1.5s bound "
        f"against browser scrolling is the point of this capability"
    )
    assert outcome.har_entries and outcome.har_entries[0]["status"] == 200
    assert outcome.har_entries[0]["content_length"] == len(pdf_bytes)


def test_fetch_pdf_robots_gated(monkeypatch):
    """REQ-5 AC3 parity with fetch.crawl: the gate runs BEFORE any download."""
    gate_seen: list[str] = []

    class _DenyAll:
        async def is_allowed(self, url, ua=""):
            gate_seen.append(url)
            return False

    monkeypatch.setattr(
        "backend.crawler.capabilities.get_robots_checker", lambda: _DenyAll()
    )

    def _no_network(*a, **k):
        raise AssertionError("download attempted for a robots-refused PDF")

    monkeypatch.setattr("httpx.AsyncClient", _no_network)

    outcome = asyncio.run(
        FetchPDFCapability().fetch_one("https://walled.example/x.pdf", "", "j-pdf")
    )
    assert gate_seen == ["https://walled.example/x.pdf"]
    assert outcome.page is None
    assert outcome.verdict.usable is False
    assert outcome.verdict.reason == UsabilityReason.TRANSPORT_ERROR
    assert "robots" in outcome.verdict.detail


def test_fetch_pdf_never_raises_on_bad_bytes(monkeypatch):
    """AC8 pattern: corrupt PDF bytes yield an unusable outcome, not a crash."""
    monkeypatch.setattr("httpx.AsyncClient.get", _fake_httpx_get(b"not a pdf at all"))
    outcome = asyncio.run(
        FetchPDFCapability().fetch_one("https://example.com/broken.pdf", "", "j-pdf")
    )
    assert outcome.page is None
    assert outcome.verdict.usable is False


def test_fetch_pdf_render_target_page_png():
    """AC15.3: render_target_page_png renders ONLY the named page (0-based)."""
    pdf_bytes = _make_pdf_bytes(5)
    cap = FetchPDFCapability()
    png = asyncio.run(cap.render_target_page_png(pdf_bytes, page_index=2))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    # A second render of the same bytes is pure (no carry-over state).
    again = asyncio.run(cap.render_target_page_png(pdf_bytes, page_index=2))
    assert again == png


def test_fetch_pdf_render_target_out_of_range_returns_none():
    pdf_bytes = _make_pdf_bytes(3)
    cap = FetchPDFCapability()
    assert asyncio.run(cap.render_target_page_png(pdf_bytes, page_index=99)) is None
