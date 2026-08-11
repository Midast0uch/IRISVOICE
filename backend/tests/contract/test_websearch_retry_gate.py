"""
REQ-2 contract: the broaden-and-retry gate reads page_is_usable.

Pins specs/vision-browser-websearch/requirements.md REQ-2:

  AC1  gate on page_is_usable, not `error is None`
  AC2  no usable page -> broaden the query and re-run Plan->Fetch exactly once
  AC3  emit a progress event describing the retry while it runs
  AC4  never retry more than once per research call

The fixture reproduces the exact reference-failure shape: the stub backend
returns pages with ``error=None`` but EMPTY markdown. The OLD gate
(``[p for p in fetched.pages if not p.error]``) counted those as usable and
the retry never fired — zero times in 401MB of history. The NEW gate must
fire. Downstream stages (credibility / rerank / extract+cite) are stubbed so
this test exercises the gate, not the Wave-1-later stages.

Anchored to pin_4d251b65674d (T0 baseline).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from crawler.orchestrator import CrawlOrchestrator, CrawlProgress, FetchBackend
from crawler.crawler_engine import CrawlResult, PageData
from crawler.crawl_planner import CrawlPlan


@pytest.fixture
def events():
    return []


@pytest.fixture
def emitter(events):
    def _cb(progress: CrawlProgress):
        events.append((progress.event, progress.payload))
    return _cb


class _RetryCountingBackend(FetchBackend):
    """First call: the Palworld shape — 2 pages, error=None, EMPTY markdown.

    Second call: one usable page. Records every query it was given.
    """

    def __init__(self):
        self.calls: list[str] = []

    async def fetch(self, query, urls, instructions, max_pages, on_page_done, timeout_s, **kwargs):
        self.calls.append(query)
        if len(self.calls) == 1:
            pages = [
                PageData(url="https://x.gov/a", title="A", markdown="", html="", metadata={}),
                PageData(url="https://x.gov/b", title="B", markdown="   ", html="", metadata={}),
            ]
        else:
            pages = [
                PageData(
                    url="https://x.gov/c", title="C",
                    markdown="Real usable content about the quantum model and its verification.",
                    html="", metadata={},
                )
            ]
        for i, p in enumerate(pages):
            if on_page_done:
                on_page_done(p.url, i + 1, len(pages))
        return CrawlResult(
            query=query, pages=pages, duration_ms=10,
            crawled_at="2026-01-01T00:00:00+00:00",
        )


class _StubPlanner:
    async def plan(self, query):
        return CrawlPlan(
            urls=["https://x.gov/a", "https://x.gov/b"],
            instructions="extract key facts", result_type="mixed", title="T",
        )


def _stub_downstream(monkeypatch):
    """Stub the Wave-1-later stages; the gate is what is under test."""
    from crawler.credibility import CredibilityMap
    from crawler.rerank import RerankOutcome, RerankState

    def _fake_credibility(pages, passages):
        return CredibilityMap(
            per_source={p.url: 0.9 for p in pages},
            unsourced_claims=[], top_score=0,
        )

    async def _fake_extract(query, fetched, passages, instructions, result_type, title, extractor=None):
        return ({"title": "T", "summary": "s", "sources": []},
                "cited [1](https://x.gov/c)", [])

    def _fake_rerank(passages, query, cred_map):
        # REQ-3 (T3) contract: rerank returns a RerankOutcome, not a bare list.
        return RerankOutcome(state=RerankState.OK, kept=passages)

    monkeypatch.setattr("crawler.credibility.score_credibility", _fake_credibility)
    monkeypatch.setattr("crawler.rerank.rerank_passages", _fake_rerank)
    monkeypatch.setattr("crawler.cite.extract_and_cite", _fake_extract)


def test_retry_gate_fires_on_empty_markdown(monkeypatch, events, emitter):
    """REQ-2 AC1+AC2: empty-markdown pages with error=None do NOT count as
    usable; the gate opens, broadens, and re-runs Plan->Fetch exactly once."""
    backend = _RetryCountingBackend()
    orch = CrawlOrchestrator(planner=_StubPlanner())
    orch._backend_override = backend
    monkeypatch.setattr(orch, "_learn_from_crawl", _noop)
    _stub_downstream(monkeypatch)

    result = asyncio.run(orch.research(
        "palworld boss tower builds", mode="agent", session_id="", on_progress=emitter, max_pages=5,
    ))

    # AC2 + AC4: retried exactly once (2 fetches total, second on a broadened query)
    assert len(backend.calls) == 2, f"expected exactly 1 retry, got {len(backend.calls)} calls"
    assert backend.calls[1] != backend.calls[0], f"retry must use a broadened query: {backend.calls}"

    # the retried page flowed through to the result
    assert result.pages, "usable retry page must be present"
    assert any(p.markdown.strip() for p in result.pages), "retry page must carry content"

    # AC3: a progress event describing the retry was emitted
    ev_types = [e[0] for e in events]
    assert "CRAWLER_PROGRESS" in ev_types, f"retry progress event missing: {ev_types}"


def test_retry_fires_once_even_when_second_batch_also_empty(monkeypatch, events, emitter):
    """REQ-2 AC2/AC4: a second empty batch does NOT trigger a second retry —
    the run ends honestly (REQ-15 path) after exactly one broaden."""
    backend = _AlwaysEmptyBackend()
    orch = CrawlOrchestrator(planner=_StubPlanner())
    orch._backend_override = backend
    monkeypatch.setattr(orch, "_learn_from_crawl", _noop)

    result = asyncio.run(orch.research(
        "what is X", mode="agent", session_id="", on_progress=emitter, max_pages=5,
    ))

    assert len(backend.calls) == 2, f"must not retry twice: {len(backend.calls)}"
    # honest failure — CRAWLER_ERROR emitted, error surfaced (REQ-15 pre-step)
    assert any(e[0] == "CRAWLER_ERROR" for e in events)
    assert result.error, "zero usable content must surface as error, not success"


async def _noop(*a, **k):
    return None


class _AlwaysEmptyBackend(FetchBackend):
    def __init__(self):
        self.calls: list[str] = []

    async def fetch(self, query, urls, instructions, max_pages, on_page_done, timeout_s, **kwargs):
        self.calls.append(query)
        pages = [
            PageData(url="https://x.gov/a", title="A", markdown="", html="", metadata={}),
        ]
        for i, p in enumerate(pages):
            if on_page_done:
                on_page_done(p.url, i + 1, len(pages))
        return CrawlResult(
            query=query, pages=pages, duration_ms=10,
            crawled_at="2026-01-01T00:00:00+00:00",
        )
