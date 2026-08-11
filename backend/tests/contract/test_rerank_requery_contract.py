"""
REQ-3 contract: rerank returns a distinguishable re-query state and the
orchestrator escalates on it instead of citing empty passages.

Pins specs/vision-browser-websearch/requirements.md REQ-3:

  AC1  distinguish "no passages produced" from "all below threshold" as
       separate return states
  AC2  below-threshold rerank -> escalate, never proceed to citation
  AC3  extract_and_cite is unreachable with an empty passage set

The traced Palworld run logged ``top score 0.000 below threshold 0.300 ->
prefer re-query`` one second before CRAWLER_COMPLETE; the signal was computed
and discarded. These tests pin the signal being ACTED on.

``rerank._embed`` is stubbed so scoring is BM25-only: this tests the state
machine and escalation, not the embedding service (which is the recorded
pre-existing hang in the full-funnel tests).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from crawler.orchestrator import CrawlOrchestrator, CrawlProgress, FetchBackend
from crawler.crawler_engine import CrawlResult, PageData
from crawler.crawl_planner import CrawlPlan
from crawler.rerank import rerank_passages, RerankOutcome, RerankState
from crawler.credibility import CredibilityMap


def _passage(text: str, url: str = "https://x.gov/a", score: float = 0.0):
    from crawler.orchestrator import Passage
    return Passage(chunk_id=f"{url}#0", url=url, text=text, heading_path="T", score=score)


def _cm(pages):
    return CredibilityMap(per_source={p.url: 0.9 for p in pages}, unsourced_claims=[], top_score=0)


@pytest.fixture(autouse=True)
def _no_embedding(monkeypatch):
    """BM25-only scoring — no embedding service load in these tests."""
    monkeypatch.setattr("crawler.rerank._embed", lambda texts: None)


# ── AC1: distinguishable states ─────────────────────────────────────────

def test_no_passages_state_is_distinct(monkeypatch):
    """Empty input -> NO_PASSAGES, not a bare []."""
    out = rerank_passages([], "query", _cm([]))
    assert isinstance(out, RerankOutcome)
    assert out.state == RerankState.NO_PASSAGES
    assert out.kept == []


def test_below_threshold_state_carries_top_score():
    """Content scored but all below threshold -> BELOW_THRESHOLD + top_score."""
    out = rerank_passages(
        [_passage("completely unrelated random words with no query overlap whatsoever"),
         _passage("also nothing in common with the query at all")],
        "palworld boss tower builds", _cm([]),
    )
    assert out.state == RerankState.BELOW_THRESHOLD
    assert out.kept == []
    assert out.top_score < 0.3, f"top_score must be below threshold, got {out.top_score}"


def test_ok_state_keeps_passing_passages():
    """Above-threshold content -> OK with kept passages, iterable like a list."""
    out = rerank_passages(
        [_passage("palworld boss tower builds guide explained in detail here"),
         _passage("unrelated noise words with nothing relevant")],
        "palworld boss tower builds", _cm([]),
    )
    assert out.state == RerankState.OK
    assert len(out.kept) == 1
    # backward-compatible iteration over kept
    assert [p for p in out] == out.kept


# ── AC2/AC3: escalation at the orchestrator ─────────────────────────────

class _RecoveryBackend(FetchBackend):
    """First call: usable page but content that scores below threshold.
    Second call (escalation retry): content that clears the threshold."""

    def __init__(self):
        self.calls = 0

    async def fetch(self, query, urls, instructions, max_pages, on_page_done, timeout_s, **kwargs):
        self.calls += 1
        if self.calls == 1:
            text = "completely unrelated random words with no query overlap whatsoever"
        else:
            text = "palworld boss tower builds guide explained in detail here"
        page = PageData(url="https://x.gov/a", title="A", markdown=text, html="", metadata={})
        return CrawlResult(query=query, pages=[page], duration_ms=10,
                           crawled_at="2026-01-01T00:00:00+00:00")


class _AlwaysWeakBackend(FetchBackend):
    """Every call returns content that never clears the threshold — the
    escalation budget must run out and produce an honest failure."""

    def __init__(self):
        self.calls = 0

    async def fetch(self, query, urls, instructions, max_pages, on_page_done, timeout_s, **kwargs):
        self.calls += 1
        page = PageData(url="https://x.gov/a", title="A",
                        markdown="completely unrelated random words with no query overlap whatsoever",
                        html="", metadata={})
        return CrawlResult(query=query, pages=[page], duration_ms=10,
                           crawled_at="2026-01-01T00:00:00+00:00")


class _Planner:
    async def plan(self, query):
        return CrawlPlan(urls=["https://x.gov/a"], instructions="facts", result_type="mixed", title="T")


@pytest.fixture
def events():
    return []


@pytest.fixture
def emitter(events):
    def _cb(progress: CrawlProgress):
        events.append((progress.event, progress.payload))
    return _cb


def _run(orch, query, events, emitter):
    return asyncio.run(orch.research(
        query, mode="agent", session_id="", on_progress=emitter, max_pages=5,
    ))


def test_below_threshold_escalates_and_recovers(monkeypatch, events, emitter):
    """AC2: a below-threshold rerank escalates (broaden + retry once) and the
    recovered content is cited — the signal is acted on, not discarded."""
    backend = _RecoveryBackend()
    orch = CrawlOrchestrator(planner=_Planner())
    orch._backend_override = backend
    monkeypatch.setattr(orch, "_learn_from_crawl", lambda *a, **k: _noop_future())
    # _apply_har_penalties touches SourceRegistry — no-op for this test
    monkeypatch.setattr(orch, "_apply_har_penalties", lambda *a, **k: None)

    result = _run(orch, "palworld boss tower builds", events, emitter)

    assert backend.calls == 2, f"escalation must retry once, got {backend.calls} calls"
    assert result.cited_markdown, "recovered content must be cited (REQ-3 AC2)"
    assert not result.error


def _noop_future():
    import asyncio as _a
    async def _n(*a, **k):
        return None
    return _a.ensure_future(_n())


def test_exhausted_budget_is_honest_failure(monkeypatch, events, emitter):
    """AC2 edge: budget exhausted and still below threshold -> REQ-15 honest
    failure with error set; extract_and_cite must never be reached with empty
    passages (AC3)."""
    backend = _AlwaysWeakBackend()
    orch = CrawlOrchestrator(planner=_Planner())
    orch._backend_override = backend
    monkeypatch.setattr(orch, "_learn_from_crawl", lambda *a, **k: _noop_future())
    monkeypatch.setattr(orch, "_apply_har_penalties", lambda *a, **k: None)

    result = _run(orch, "palworld boss tower builds", events, emitter)

    assert backend.calls == 2, f"exactly one retry, got {backend.calls}"
    assert result.error, "honest failure must set error (REQ-15)"
    assert not result.cited_markdown, "never cite empty passages (REQ-3 AC3)"
