#!/usr/bin/env python3
"""Wave 0 unit tests (part 2) — T0e (Pacman spillage) + T0f (smart-crawl loop).

Run:  pytest backend/tests/unit/test_document_rehydration_wave0_prov.py -q
"""
import asyncio
import sys
import unittest.mock as mock
from datetime import datetime, timezone

REPO_ROOT = r"C:\dev\IRISVOICE"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.agent.mcm_protocol.actions import pacman_fragment as pf
from backend.crawler.crawler_engine import CrawlResult, PageData
from backend.crawler.orchestrator import CrawlOrchestrator
from backend.crawler.source_registry import SourceRegistry


# ── T0e: Pacman document-linked provenance ─────────────────────────────────
class FakeEpisodic:
    def __init__(self):
        self.calls = []

    def fragment_and_store(self, content, session_id, chunk_type, zone, tool_name=None):
        self.calls.append({
            "content": content, "session_id": session_id,
            "chunk_type": chunk_type, "zone": zone, "tool_name": tool_name,
        })


def test_t0e_document_provenance_written_and_queryable():
    ep = FakeEpisodic()
    pf.fragment_document_provenance(
        ep, "doc-123", "conv-1",
        sources=[{"url": "http://x.com/a", "title": "A"}],
        har_path="data/har/job9.har",
    )
    assert len(ep.calls) == 1
    c = ep.calls[0]
    assert c["zone"] == "reference"  # untrusted zone reused, not a new enum
    assert "doc-123" in c["content"]
    assert "DOC_PROVENANCE" in c["content"]
    assert "http://x.com/a" in c["content"]
    assert "data/har/job9.har" in c["content"]


def test_t0e_existing_credibility_blob_path_preserved():
    ep = FakeEpisodic()
    pf._store_credibility_metadata(
        ep, "conv-1", "crawler_query",
        credibility_map={"per_source": {"http://x.com": 0.9}},
        citation_index={"c1": "http://x.com"},
    )
    assert len(ep.calls) == 1
    assert "CREDIBILITY_META" in ep.calls[0]["content"]
    assert ep.calls[0]["zone"] == "reference"


def test_t0e_provenance_write_failure_does_not_raise():
    # episodic without fragment_and_store -> helper must no-op, not raise.
    pf.fragment_document_provenance(
        object(), "doc-x", "conv-1", sources=[], har_path=None)


# ── T0f: smart-crawl learning loop ────────────────────────────────────────
def _fake_registry():
    reg = SourceRegistry(store={})
    reg._extract_topics = mock.AsyncMock(return_value=["ai hardware"])  # type: ignore[assignment]
    return reg


def test_t0f_learn_from_crawl_registers_urls():
    reg = _fake_registry()
    with mock.patch("backend.crawler.source_registry.get_source_registry",
                    return_value=reg):
        orch = CrawlOrchestrator()
        fetched = CrawlResult(
            query="ai hardware", pages=[PageData(url="http://x.com/a", title="A",
                                                 markdown="m", html=None, metadata={})],
            duration_ms=1, crawled_at="")
        asyncio.run(orch._learn_from_crawl(fetched, "ai hardware"))
    res = asyncio.run(reg.resolve("ai hardware"))
    urls = [s["url"] for s in res["sources"]]
    assert "http://x.com/a" in urls


def test_t0f_healthy_har_reuse_decisions():
    recent = datetime.now(timezone.utc).isoformat()
    old = "2000-01-01T00:00:00+00:00"
    healthy = [{"url": "u1", "status": 200}, {"url": "u2", "status": 201}]
    dead = [{"url": "u1", "status": 404}]
    assert CrawlOrchestrator._healthy_har_reuse(healthy, recent, 7) is True
    assert CrawlOrchestrator._healthy_har_reuse(dead, recent, 7) is False
    assert CrawlOrchestrator._healthy_har_reuse(healthy, old, 7) is False
    assert CrawlOrchestrator._healthy_har_reuse([], recent, 7) is False


def test_t0f_delta_urls_fetches_only_new_when_prior_healthy():
    orch = CrawlOrchestrator()
    recent = datetime.now(timezone.utc).isoformat()
    plan = ["http://x.com/a", "http://x.com/b", "http://x.com/c"]
    prior = [{"url": "http://x.com/a", "status": 200},
             {"url": "http://x.com/b", "status": 200}]
    # Healthy prior -> only the uncovered URL is fetched (fewer than plan).
    delta = orch._delta_urls(plan, prior, recent, 7)
    assert delta == ["http://x.com/c"]
    # Unhealthy prior (a 404) -> re-fetch everything.
    prior_dead = [{"url": "http://x.com/a", "status": 404}]
    assert orch._delta_urls(plan, prior_dead, recent, 7) == plan


def test_t0f_learn_failure_does_not_raise():
    reg = _fake_registry()
    reg.learn = mock.AsyncMock(side_effect=RuntimeError("registry down"))
    with mock.patch("backend.crawler.source_registry.get_source_registry",
                    return_value=reg):
        orch = CrawlOrchestrator()
        fetched = CrawlResult(
            query="q",
            pages=[PageData(url="http://x.com/a", title="", markdown="",
                            html=None, metadata={})],
            duration_ms=1, crawled_at="")
        asyncio.run(orch._learn_from_crawl(fetched, "q"))  # must not raise
