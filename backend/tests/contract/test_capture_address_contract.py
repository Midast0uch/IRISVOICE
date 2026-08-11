"""The capture ADDRESS a page event advertises must resolve to real bytes.

Defect (live 2026-08-11 16:11, job c6a317db9a4d4041b020c918a2d210d2): every
browser-panel iframe 404'd. `page_number` served two masters — the counter the
header chip renders AND the capture-replay key the iframe src is built from
(/api/browser/capture/{job_id}/{page_number}) — and the two diverge for two
INDEPENDENT reasons:

  1. Per-URL dispatch runs a single-URL fetch per URL, so every URL's only page
     is number 1 and all of them overwrite data/captures/<job>/1.html. Evidence
     at the time: the job directory held ONLY 1.html + 1.json while the panel
     logged "capture unavailable" for pages 1,2,3,4,5.
  2. A vision escalation publishes MANY frames for ONE url, and every session
     numbered from 1 into the SHARED job directory — so an escalation on URL 4
     overwrote URLs 1-3's captured pages and the panel served the WRONG page's
     bytes under URL 1's tab. Wrong evidence is worse than a 404, and no test
     covered it because nothing ever compared two URLs' addresses.

Nothing asserted that an emitted address resolves to an existing capture entry,
which is exactly why this shipped. That is the assertion below.

A third case is not a bug: a challenged page is DELIBERATELY not persisted
(REQ-4 AC2 — the interstitial's boilerplate must not poison replay), so its
address has no bytes BY DESIGN. The contract there is that the payload SAYS so
(capture_available=False) instead of pointing the panel at a dead frame.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.crawler import capture_store as _capture_store_mod
from backend.crawler.capture_store import (
    CAPTURE_SLOT_STRIDE,
    CaptureStore,
    slot_capture_offset,
)
from backend.crawler.crawler_engine import CrawlResult, PageData
from backend.crawler.orchestrator import CrawlOrchestrator

_URLS = [
    "https://a.example.com/one",
    "https://b.example.com/two",
    "https://c.example.com/three",
    "https://d.example.com/four",
    "https://e.example.com/five",
]


def _page(url: str) -> PageData:
    md = "real retrieved content for " + url
    return PageData(
        url=url, title="t", markdown=md, html="<html></html>",
        metadata={}, error=None, html_bytes=len(md),
    )


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Point the capture-store singleton at a temp root for this test."""
    s = CaptureStore(root=str(tmp_path / "captures"))
    monkeypatch.setattr(_capture_store_mod, "_store", s)
    return s


class _CaptureWritingBackend:
    """Stands in for the crawl subprocess ONLY.

    It writes a capture at the address it is handed and relays progress exactly
    as crawl_runner relays the worker's progress lines. Everything above it is
    production code: the real FetchCrawlCapability, the real fetch_url, the real
    _page_emitter that builds the payload. So the fetch is faked and the
    NUMBERING is not — which is the thing under test.
    """

    def __init__(self, challenge_urls=()):
        self.challenge_urls = set(challenge_urls)
        self.offsets_seen: list[int] = []

    async def fetch(
        self, query, urls, instructions, max_pages, on_page_done, timeout_s,
        job_id=None, page_offset=0,
    ):
        self.offsets_seen.append(page_offset)
        pages = []
        for i, url in enumerate(urls):
            capture_page = page_offset + i + 1
            if url not in self.challenge_urls:
                # Mirrors crawler_engine: save BEFORE reporting progress, so the
                # emitter's existence check is authoritative.
                _capture_store_mod.get_capture_store().save(
                    job_id=job_id, page_number=capture_page, url=url,
                    html=f"<html><body>{url}</body></html>",
                )
            pages.append(_page(url))
            if on_page_done:
                on_page_done(
                    url, i + 1, len(urls), "t", "", capture_page=capture_page,
                )
        return CrawlResult(
            query=query, pages=pages, duration_ms=1, crawled_at="2026-08-11T00:00:00Z",
        )


def _dispatch(urls, backend, monkeypatch):
    """Drive dispatch_urls with the REAL fetch.crawl capability.

    SEAM NOTE (pin_12059c9d2cc3): setting `_backend_override` and calling
    research() takes the BATCH path and never reaches dispatch_urls, so an
    override-based version of this test would pass with the fix reverted. The
    backend is swapped in the registry instead, so the real capability -> real
    fetch_url -> real _page_emitter chain is exercised.
    """
    from backend.crawler import orchestrator as _orch_mod
    from backend.crawler.capabilities import FetchCrawlCapability, register_capability

    monkeypatch.setitem(_orch_mod._BACKENDS, "agent", lambda: backend)
    register_capability(FetchCrawlCapability())

    class _NoHistory:
        async def resolve(self, *a, **k):
            return None

    monkeypatch.setattr(
        CrawlOrchestrator, "_domain_failure_history",
        lambda self, url, query: asyncio.sleep(0, result=""),
    )

    events: list[tuple[str, dict]] = []
    orch = CrawlOrchestrator()
    orch._backend_override = None
    asyncio.run(orch.dispatch_urls(
        urls, query="party builds", job_id="job-cap",
        on_progress=lambda p: events.append((p.event, p.payload)),
        concurrency_limit=3,
    ))
    return [pl for e, pl in events if e == "CRAWLER_PAGE_FETCHED"]


# ══════════════════════════════════════════════════════════════════════════
# 1 — the address must resolve (the guard that was missing)
# ══════════════════════════════════════════════════════════════════════════

def test_every_emitted_capture_address_resolves_to_that_urls_stored_bytes(
    store, monkeypatch,
):
    """THE missing guard. Each page event's (job_id, capture_page) must name a
    capture that exists AND holds the bytes of the URL the event is about.

    Existence alone is too weak to discriminate: when every URL collides on
    address 1 the address still "resolves", it just resolves to somebody else's
    page — which is how the panel could show URL 4's content under URL 1's tab.
    """
    backend = _CaptureWritingBackend()
    pages = _dispatch(_URLS, backend, monkeypatch)

    assert len(pages) == len(_URLS), (
        f"{len(pages)} page events for {len(_URLS)} URLs — the panel cannot show "
        f"a page it was never told about"
    )
    for pl in pages:
        addr, url = pl.get("capture_page"), pl.get("url")
        assert addr is not None, (
            "payload carries no capture_page, so the panel falls back to the UI "
            "counter for the iframe src — the original 404"
        )
        stored = store.load("job-cap", addr)
        assert stored is not None, (
            f"capture_page={addr} for {url} has NO stored bytes: "
            f"/api/browser/capture/job-cap/{addr} 404s. Stored addresses: "
            f"{sorted(_stored_addresses(store, 'job-cap'))}"
        )
        assert stored["url"] == url, (
            f"capture_page={addr} was advertised for {url} but holds "
            f"{stored['url']!r} — the panel would present another page's bytes "
            f"as this source's evidence"
        )


def test_five_dispatched_urls_produce_five_distinct_captures(store, monkeypatch):
    """The concrete live symptom: the job directory held ONE capture for five
    fetched URLs, because each single-URL fetch numbered its page 1."""
    backend = _CaptureWritingBackend()
    pages = _dispatch(_URLS, backend, monkeypatch)

    stored = _stored_addresses(store, "job-cap")
    assert len(stored) == len(_URLS), (
        f"{len(stored)} capture(s) on disk for {len(_URLS)} URLs {sorted(stored)} "
        f"— the URLs overwrote each other's bytes"
    )
    addrs = [pl.get("capture_page") for pl in pages]
    assert len(set(addrs)) == len(addrs), (
        f"duplicate capture addresses {addrs} — two URLs claim the same bytes"
    )


def test_dispatch_hands_each_url_a_distinct_capture_block(store, monkeypatch):
    """The mechanism, pinned independently of the emitted payload: the same
    offset for every URL is what made them collide."""
    backend = _CaptureWritingBackend()
    _dispatch(_URLS, backend, monkeypatch)

    assert len(set(backend.offsets_seen)) == len(_URLS), (
        f"offsets {sorted(backend.offsets_seen)} — every URL fetched into the "
        f"same capture block"
    )


def test_ui_counter_stays_the_outer_runs_counter(store, monkeypatch):
    """The counter must NOT inherit the capture address. Blocks are strided, so
    leaking the address into page_number would render "301/5" in the chip."""
    backend = _CaptureWritingBackend()
    pages = _dispatch(_URLS, backend, monkeypatch)

    for pl in pages:
        num, total = pl.get("page_number"), pl.get("total")
        assert total == len(_URLS), f"total={total}, expected {len(_URLS)}"
        assert 1 <= num <= total, (
            f"page_number={num} outside 1..{total} — the capture address leaked "
            f"into the UI counter"
        )


# ══════════════════════════════════════════════════════════════════════════
# 2 — a deliberately unsaved page must SAY it has nothing to show
# ══════════════════════════════════════════════════════════════════════════

def test_challenged_page_reports_capture_unavailable(store, monkeypatch):
    """A challenge interstitial is not persisted on purpose (REQ-4 AC2), so its
    tab 404s BY DESIGN. The payload must say so rather than let the panel open a
    frame that cannot load."""
    walled = _URLS[1]
    backend = _CaptureWritingBackend(challenge_urls={walled})
    pages = _dispatch(_URLS, backend, monkeypatch)

    by_url = {pl["url"]: pl for pl in pages}
    assert by_url[walled].get("capture_available") is False, (
        "a page whose bytes were deliberately NOT stored still advertised an "
        "available capture — the panel opens a tab that can only 404"
    )
    for url in _URLS:
        if url == walled:
            continue
        assert by_url[url].get("capture_available") is True, (
            f"{url} stored bytes but reported capture_available="
            f"{by_url[url].get('capture_available')} — the panel would show a "
            f"'blocked' state for a page it can actually replay"
        )


# ══════════════════════════════════════════════════════════════════════════
# 3 — vision frames must not land on another URL's address
# ══════════════════════════════════════════════════════════════════════════

def test_vision_sessions_for_different_urls_never_share_an_address(store):
    """Cause 2. Two sessions under one job_id both numbered from 1, so URL 4's
    frames overwrote URL 1's captured page and the panel served the wrong bytes.
    """
    from backend.vision.browser_session import BrowserSession

    s0 = BrowserSession("job-cap", _URLS[0], "goal", None, page_offset=slot_capture_offset(0))
    s3 = BrowserSession("job-cap", _URLS[3], "goal", None, page_offset=slot_capture_offset(3))

    frames0 = [_publish(s0, f"<html>a{i}</html>") for i in range(6)]
    frames3 = [_publish(s3, f"<html>d{i}</html>") for i in range(6)]

    assert not (set(frames0) & set(frames3)), (
        f"slot 0 wrote {frames0} and slot 3 wrote {frames3} — overlapping "
        f"addresses mean one URL's frames replace another's captured page"
    )
    for addr, url in [(frames0[-1], _URLS[0]), (frames3[-1], _URLS[3])]:
        loaded = store.load("job-cap", addr)
        assert loaded is not None and loaded["url"] == url, (
            f"address {addr} holds {loaded and loaded['url']!r}, not {url!r}"
        )


def test_vision_frames_cannot_bleed_into_the_next_urls_block(store):
    """The clamp. A runaway session must stop publishing rather than walk into
    the next slot's addresses."""
    from backend.vision.browser_session import BrowserSession

    s = BrowserSession("job-cap", _URLS[0], "goal", None, page_offset=slot_capture_offset(1))
    ceiling = slot_capture_offset(1) + CAPTURE_SLOT_STRIDE - 1
    written = [
        _publish(s, f"<html>{i}</html>") for i in range(CAPTURE_SLOT_STRIDE + 20)
    ]
    published = [a for a in written if a is not None]

    assert published, "no frames published at all"
    assert max(published) <= ceiling, (
        f"published address {max(published)} exceeds this slot's ceiling "
        f"{ceiling} — it overwrites the next URL's captures"
    )
    assert min(published) > slot_capture_offset(1), (
        "a frame took the crawl page's own address within the block"
    )


# ── helpers ────────────────────────────────────────────────────────────────

def _publish(session, html: str):
    """Drive _publish_frame with a stubbed current_frame; return the address the
    frame was stored at, or None when the session refused to publish."""
    async def _frame():
        return html

    session.current_frame = _frame  # type: ignore[method-assign]
    before = session.current_capture_page
    asyncio.run(session._publish_frame())
    after = session.current_capture_page
    return after if after != before else None


def _stored_addresses(store: CaptureStore, job_id: str) -> set:
    import os

    job_dir = os.path.join(store._root, job_id)
    if not os.path.isdir(job_dir):
        return set()
    return {
        int(n[:-5]) for n in os.listdir(job_dir)
        if n.endswith(".html") and n[:-5].isdigit()
    }
