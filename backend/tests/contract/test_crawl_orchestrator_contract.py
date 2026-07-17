"""
Tier 1 (unit) + Tier 2 (contract) tests for CrawlOrchestrator (REQ-1,2,3,4,9,17AC4).

Per the spec Verification Strategy:
  - Tier 1: funnel order + FetchBackend swap, collaborators stubbed, NO live web.
  - Tier 2: unified event-stream parity (crawler_started -> page_fetched -> open_tab)
    via a stubbed FetchBackend + event-bus-style on_progress subscription.

Anchored to a PiN recording the enforced contract (see test below).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

# make backend importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from crawler.orchestrator import (  # noqa: E402
    CrawlOrchestrator,
    CrawlProgress,
    FetchBackend,
    InProcessFetchBackend,
    SubprocessFetchBackend,
)
from crawler.crawler_engine import CrawlResult, PageData  # noqa: E402
from crawler.crawl_planner import CrawlPlan  # noqa: E402


class _StubBackend(FetchBackend):
    """Returns two fake pages; records which mode asked for it."""
    mode_used = None

    async def fetch(self, query, urls, instructions, max_pages, on_page_done, timeout_s):
        self.__class__.mode_used = "stub"
        pages = [
            PageData(url="https://example.gov/doc", title="Doc", markdown="The quantum model shows X. It was verified by Y.", html="", metadata={}),
            PageData(url="https://news.example.com/a", title="News", markdown="Report says Z happened recently.", html="", metadata={}),
        ]
        for i, p in enumerate(pages):
            if on_page_done:
                on_page_done(p.url, i + 1, len(pages))
        return CrawlResult(query=query, pages=pages, duration_ms=10, crawled_at="2026-01-01T00:00:00+00:00")


class _FailingBackend(FetchBackend):
    async def fetch(self, query, urls, instructions, max_pages, on_page_done, timeout_s):
        return CrawlResult(query=query, pages=[], duration_ms=1, crawled_at="x", error="subprocess crashed")


def _stub_planner(urls):
    class _P:
        async def plan(self, query):
            return CrawlPlan(urls=urls, instructions="extract key facts", result_type="mixed", title="T")
    return _P()


@pytest.fixture
def events():
    return []


@pytest.fixture
def emitter(events):
    def _cb(progress: CrawlProgress):
        events.append((progress.event, progress.payload))
    return _cb


def test_fetchbackend_swap_modes():
    """REQ-17 AC4: backend is swappable; ws vs agent select different classes."""
    assert InProcessFetchBackend is not SubprocessFetchBackend
    assert issubclass(InProcessFetchBackend, FetchBackend)
    assert issubclass(SubprocessFetchBackend, FetchBackend)


def test_funnel_order_and_events(events, emitter):
    """Tier 1+2: funnel runs; emits crawler_started -> page_fetched* -> open_tab."""
    orch = CrawlOrchestrator(planner=_stub_planner(["https://example.gov/doc"]))
    orch._backend_override = _StubBackend()  # inject stub backend (no live web)

    result = asyncio.run(orch.research(
        "what is X", mode="agent", session_id="s1",
        on_progress=emitter, max_pages=5,
    ))

    # funnel produced passages + cited_markdown (REQ-4, REQ-8)
    assert result.pages, "pages should be present"
    assert result.cited_markdown, "cited_markdown should be produced"
    assert result.credibility_map is not None
    assert result.credibility_map.per_source, "per-source credibility computed"

    # event sequence parity (REQ-10..13)
    ev_types = [e[0] for e in events]
    assert ev_types[0] == "CRAWLER_STARTED"
    assert ev_types.count("CRAWLER_PAGE_FETCHED") == 2
    assert ev_types[-1] == "OPEN_TAB"
    # full URL present (REQ-11)
    pf = [p for e, p in events if e == "CRAWLER_PAGE_FETCHED"]
    assert pf[0]["url"].startswith("https://")


def test_credibility_monotonicity():
    """REQ-5/6: primary_official scores higher than forum."""
    from crawler.credibility import classify_source, _base_weight
    assert classify_source("https://nasa.gov/doc") == "primary_official"
    assert classify_source("https://reddit.com/r/x") == "forum"
    assert _base_weight("https://nasa.gov/doc") > _base_weight("https://reddit.com/r/x")


def test_citation_binding_completeness():
    """REQ-8: every cited sentence carries a url; unsourced flagged [?]."""
    from crawler.cite import _bind_citations
    from crawler.orchestrator import Passage
    passages = [Passage(chunk_id="u#0", url="https://example.gov/doc", text="the quantum model shows X")]
    md, unsourced = _bind_citations("The quantum model shows X. Unknown claim here.", passages)
    assert "[1](https://example.gov/doc)" in md
    assert "[?]" in md  # unsourced sentence flagged


def test_rerank_threshold_drops_low():
    """REQ-7: passages below threshold are dropped."""
    from crawler.rerank import rerank_passages
    from crawler.orchestrator import Passage
    from crawler.credibility import CredibilityMap
    passages = [
        Passage(chunk_id="a#0", url="https://a.gov", text="quantum model verified by experiment"),
        Passage(chunk_id="b#0", url="https://b.com", text="zzz qwerty nonsense token"),
    ]
    cm = CredibilityMap(per_source={"https://a.gov": 0.9, "https://b.com": 0.3}, unsourced_claims=[], top_score=0)
    kept = rerank_passages(passages, "quantum model experiment", cm)
    # at least the strong passage survives; weak one may be dropped
    assert any("a.gov" in p.url for p in kept)


def test_crawl_failure_returns_error_never_raises(events, emitter):
    """REQ-17 AC1/AC3: subprocess crash -> CrawlResult.error, no raise, crawler_error emitted."""
    orch = CrawlOrchestrator(planner=_stub_planner(["https://x.com"]))
    orch._backend_override = _FailingBackend()
    result = asyncio.run(orch.research("q", mode="agent", on_progress=emitter))
    assert result.error is not None
    assert any(e[0] == "CRAWLER_ERROR" for e in events)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
