"""Behavioral test: research builds on research (spec research-memory R2, REQ-2).

A REAL EpisodicStore on a temp DB with the REAL embedder (no stand-in): record A
is about Tokyo's population; a later ``search`` on a PARAPHRASE returns a result
whose content carries A's summary and date with a CROSS-CHECK; an unrelated
query does not; a blocked lookup never delays the result past its bound, and a
slow lookup adds no wall time when the web call is slower.

The embedder is CPU-only (~5 s per KB, a cold model load ~15 s), so the module
fixture embeds the one record once and every test reuses it.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
import time
import uuid
from types import SimpleNamespace

import pytest

from backend.agent import research_memory as rm
from backend.agent.document_store import DocumentDataStore
from backend.agent.tool_bridge import AgentToolBridge
from backend.crawler.search_providers.base import SearchResult, SearchResultItem
from backend.memory.episodic import EpisodicStore
from backend.utils.durability_queue import lane

_SUMMARY = "Tokyo's population was about 13.96 million residents in 2021."
_DAY = "2026-09-20"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def memory():
    path = os.path.join(tempfile.gettempdir(), f"research_mem_{uuid.uuid4().hex}.db")
    DocumentDataStore._stores.clear()
    mi = SimpleNamespace(episodic=EpisodicStore(path, b"test" * 8))
    original = rm._get_mi
    rm._get_mi = lambda: mi
    # Record A, written the way production writes it: the lane writes the row,
    # the fragment worker embeds it. Wait for the embedding to land.
    assert rm.record_research({
        "query": "tokyo population", "summary": _SUMMARY,
        "claims": [{"text": "Tokyo population 13,960,000 (2021)", "urls": ["https://stats.example.org/tokyo"]}],
        "sources": ["https://stats.example.org/tokyo"],
        "conversation_id": "conv-old", "job_id": "job-old", "created_at": f"{_DAY}T09:00:00Z",
    })
    assert lane("research_memory").flush(30)
    end = time.monotonic() + 180
    while time.monotonic() < end:
        n = mi.episodic.db.execute(
            "SELECT COUNT(*) FROM context_chunks WHERE chunk_type='research_summary'"
        ).fetchone()[0]
        if n:
            break
        time.sleep(0.5)
    else:
        pytest.fail("the research fragment was never embedded")
    yield mi
    rm._get_mi = original
    DocumentDataStore._stores.clear()
    try:
        os.remove(path)
    except OSError:
        pass


@pytest.fixture(autouse=True)
def _record_a_is_the_only_memory(monkeypatch):
    """These tests are about the LOOKUP: the searches they run must not add
    records of their own (landing is pinned by test_research_memory_contract)."""
    monkeypatch.setattr(rm, "record_research", lambda *a, **k: False)


def _provider(monkeypatch, items, delay_s=0.0):
    from backend.crawler import search_providers as sp_mod

    class _P:
        async def search(self, query, max_results=10):
            if delay_s:
                await asyncio.sleep(delay_s)
            return SearchResult(query=query, results=items[:max_results], provider="exa")

    monkeypatch.setattr(sp_mod, "get_search_provider", lambda: _P())


def _search(query):
    bridge = AgentToolBridge()
    return _run(bridge._execute_web_search({"query": query}, "sess-b"))


_NEW_TOKYO = [
    SearchResultItem(
        url="https://census.example.jp/2024", title="Census 2024",
        snippet="Tokyo's population is 14,246,219 residents as of 2024.",
        content="Tokyo's population is 14,246,219 residents as of 2024."),
]
_BREAD = [
    SearchResultItem(
        url="https://bread.example.com/sourdough", title="Sourdough",
        snippet="A sourdough hydration ratio near 75 percent gives an open crumb.",
        content="A sourdough hydration ratio near 75 percent gives an open crumb."),
]


def test_paraphrase_search_builds_on_the_earlier_record(memory, monkeypatch):
    _provider(monkeypatch, _NEW_TOKYO)
    out = _search("How many people live in Tokyo these days?")
    assert out["success"] is True
    content = out["content"]
    assert content.startswith("PRIOR RESEARCH"), content[:200]
    assert _SUMMARY in content and _DAY in content
    assert "CROSS-CHECK" in content
    assert f"changed since {_DAY}" in content, "the new census figure differs from the recorded one"
    assert "14,246,219" in content
    assert len(content.split("--- Source:")[0]) <= rm.SECTION_CAP + 4
    assert out["meta"]["prior_research"], "the tool result names the records it built on"
    assert "Tokyo's population is 14,246,219" in content, "the web evidence is still there"


def test_unrelated_search_gets_no_prior_section(memory, monkeypatch):
    _provider(monkeypatch, _BREAD)
    out = _search("best sourdough bread hydration ratio")
    assert out["success"] is True
    assert "PRIOR RESEARCH" not in out["content"] and "prior_research" not in out.get("meta", {})


def test_blocked_lookup_does_not_delay_the_result_past_its_bound(memory, monkeypatch):
    """A lookup stuck on the embedder degrades to 'no prior' at the bound; the
    web result still returns, and the stuck thread is a daemon (a loop close
    never waits for it)."""
    _provider(monkeypatch, _NEW_TOKYO)
    stuck = []
    release = __import__("threading").Event()

    def _blocked(query, **kw):
        stuck.append(True)
        release.wait(60)
        return []

    monkeypatch.setattr(rm, "recall_prior_research", _blocked)
    try:
        t0 = time.monotonic()
        out = _search("How many people live in Tokyo these days?")
        elapsed = time.monotonic() - t0
    finally:
        release.set()
    assert stuck, "the lookup never started"
    assert out["success"] is True and "PRIOR RESEARCH" not in out["content"]
    assert rm.PRIOR_TIMEOUT_S <= elapsed < rm.PRIOR_TIMEOUT_S + 1.5, f"bound broken: {elapsed:.2f}s"


def test_lookup_adds_no_wall_time_when_the_web_call_is_slower(memory, monkeypatch):
    """The lookup runs beside the web call: a 1.0 s lookup under a 1.6 s search
    costs ~1.6 s in total, not 2.6 s."""
    _provider(monkeypatch, _NEW_TOKYO, delay_s=1.6)

    def _slow(query, **kw):
        time.sleep(1.0)
        return []

    monkeypatch.setattr(rm, "recall_prior_research", _slow)
    t0 = time.monotonic()
    out = _search("How many people live in Tokyo these days?")
    elapsed = time.monotonic() - t0
    assert out["success"] is True
    assert 1.6 <= elapsed < 2.3, f"the lookup was serial with the web call: {elapsed:.2f}s"


def test_crawler_query_builds_on_prior_but_excludes_its_own_job(memory, monkeypatch):
    """crawler_query gets the same section; the record the SAME job produced is
    never offered as prior research."""
    from backend.crawler.crawler_engine import CrawlResult, PageData
    from unittest.mock import patch

    class _Orch:
        async def research(self, query, **kw):
            return CrawlResult(
                query=query, duration_ms=5, crawled_at="2026-09-30T00:00:00+00:00",
                pages=[PageData(url="https://census.example.jp/2024", title="Census",
                                markdown="Tokyo's population is 14,246,219 residents as of 2024. " * 6,
                                html="", metadata={})],
            )

    query = "How many people live in Tokyo these days?"
    with patch("backend.crawler.orchestrator.get_crawl_orchestrator", return_value=_Orch()):
        out = _run(AgentToolBridge()._execute_crawler_query({"query": query}, "sess-c"))
    assert out["success"] is True
    assert out["content"].startswith("PRIOR RESEARCH") and _DAY in out["content"]
    assert f"changed since {_DAY}" in out["content"]

    same_job = rm.recall_prior_research(query, exclude_job_id="job-old")
    assert same_job == [], "the record of the excluded job must not come back"
    assert [r["job_id"] for r in rm.recall_prior_research(query)] == ["job-old"]
