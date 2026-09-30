"""Contract tests: research memory (spec research-memory R1, R4, R5; REQ-1..3).

R1  a landed research result -> ONE document_data row (fmt research), ONE chain
    row (nbl_outcome research, file_path = document id, result a reference),
    ONE fragment job (chunk_type research_summary, zone reference) - all from a
    lane, none on the answer path; the registry result gains the summary.
R4  ``recall_research`` is a read-only registry tool, never captured (S11),
    and reads by document id and by query.
R5  ``GET /api/research/history`` lists metadata only; ``GET /api/research/{id}``
    returns the record; an unknown id is 404.

The episodic store here is a recording stand-in (no embedder): the embedding
path is covered by the behavioral test, which uses the real EpisodicStore.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from backend.agent import research_memory as rm
from backend.agent.document_store import DocumentDataStore
from backend.agent.tool_bridge import AgentToolBridge
from backend.crawler.search_providers.base import SearchResult, SearchResultItem
from backend.utils.durability_queue import lane

_COORD = {"x": 1.0, "y": 0.0, "xi": 1.05, "u": 0.2}


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _StubEpisodic:
    """Records fragment writes; recalls them by a crude word match (no embedder)."""

    def __init__(self) -> None:
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.fragments: list = []

    def fragment_and_store(self, content, session_id, chunk_type="context_fragment",
                           zone=None, tool_name=None):
        self.fragments.append({"content": content, "session_id": session_id,
                               "chunk_type": chunk_type, "zone": zone, "tool_name": tool_name})
        return ["chunk"]

    def retrieve_context_chunks(self, query, session_id=None, limit=6, min_similarity=0.25,
                                chunk_types=None, zones=None, max_context_tokens=None):
        words = {w for w in query.lower().split() if len(w) > 3}
        return [
            f["content"] for f in self.fragments
            if f["chunk_type"] in (chunk_types or [f["chunk_type"]])
            and f["zone"] in (zones or [f["zone"]])
            and words & set(f["content"].lower().split())
        ][:limit]


class _Recorder:
    def __init__(self, coord) -> None:
        self._coord = coord

    def get_latest_coordinate(self, session_id):
        return self._coord if session_id == "sess-1" else None


@pytest.fixture
def mem(monkeypatch):
    import backend.agent.caducean_trajectory as ct
    import backend.gateway.iris_ffi as ffi

    DocumentDataStore._stores.clear()
    episodic = _StubEpisodic()
    mi = SimpleNamespace(episodic=episodic)
    chain: list = []
    coord = {"value": _COORD}
    monkeypatch.setattr(rm, "_get_mi", lambda: mi)
    monkeypatch.setattr(ffi, "ffi_immortus_chain_append", lambda **kw: chain.append(kw) or 0)
    monkeypatch.setattr(ct, "get_trajectory_recorder", lambda _mi: _Recorder(coord["value"]))
    yield SimpleNamespace(mi=mi, episodic=episodic, chain=chain, coord=coord,
                          store=DocumentDataStore.get_for(mi))
    DocumentDataStore._stores.clear()


def _wait(pred, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def _quick_provider(monkeypatch, items):
    from backend.crawler import search_providers as sp_mod

    class _P:
        async def search(self, query, max_results=10):
            return SearchResult(query=query, results=items[:max_results], provider="exa")

    monkeypatch.setattr(sp_mod, "get_search_provider", lambda: _P())


_ITEMS = [
    SearchResultItem(url="https://stats.example.org/tokyo", title="Tokyo census",
                     snippet="Tokyo had 13,960,000 residents in 2021 according to the census.",
                     content="Tokyo had 13,960,000 residents in 2021 according to the census."),
    SearchResultItem(url="https://atlas.example.com/jp", title="Japan atlas",
                     snippet="Tokyo remains the largest city of Japan by population.",
                     content="Tokyo remains the largest city of Japan by population."),
]


def _bridge():
    bridge = AgentToolBridge()
    bridge._active_conversation_id["sess-1"] = "conv-A"
    return bridge


# ── R1 ─────────────────────────────────────────────────────────────────────


def test_quick_search_lands_three_homes_from_a_lane_not_the_answer_path(mem, monkeypatch):
    """A blocked research_memory lane delays nothing the reply needs; once the
    lane runs, the one record lands in all three homes."""
    _quick_provider(monkeypatch, _ITEMS)
    release = threading.Event()
    assert lane("research_memory").submit("test-block", release.wait, 30)
    try:
        t0 = time.monotonic()
        out = _run(_bridge()._execute_web_search({"query": "tokyo population"}, "sess-1"))
        elapsed = time.monotonic() - t0
        assert out["success"] is True and "13,960,000" in out["content"]
        assert elapsed < 3.0, f"the lane blocked the tool result ({elapsed:.1f}s)"
        assert mem.store.list_by_format("research") == [], "written on the answer path"
        assert mem.chain == [] and mem.episodic.fragments == []
    finally:
        release.set()
    assert lane("research_memory").flush(10)
    assert _wait(lambda: len(mem.episodic.fragments) == 1), "fragment job never ran"

    rows = mem.store.list_by_format("research")
    assert len(rows) == 1
    doc_id = rows[0]["document_id"]
    doc = mem.store.get(doc_id)
    assert doc["format"] == "research" and doc["conversation_id"] == "conv-A"
    record = json.loads(doc["content"])
    assert record["query"] == "tokyo population"
    assert record["conversation_id"] == "conv-A"
    assert any("13,960,000" in c["text"] and c["urls"] for c in record["claims"])
    assert record["sources"] == [i.url for i in _ITEMS]
    assert record["created_at"]

    assert len(mem.chain) == 1
    row = mem.chain[0]
    assert row["nbl_outcome"] == "research" and row["file_path"] == doc_id
    assert row["thread_id"] == "conv-A" and row["topic_domain"]
    assert row["coords_from"] == row["coords_to"] == "1.00,0.00,1.05,0.20"
    ref = json.loads(row["result"])
    assert len(row["result"]) < 2048 and ref["document_id"] == doc_id
    assert "claims" not in ref and "dashboard" not in ref, "chain row must be a reference"

    frag = mem.episodic.fragments[0]
    assert frag["chunk_type"] == "research_summary" and frag["zone"] == "reference"
    assert f"doc={doc_id}" in frag["content"] and record["created_at"][:10] in frag["content"]
    assert len(frag["content"]) <= 1024, "the fragment must be ONE embedder chunk"


def test_chain_row_has_null_coordinates_when_none_is_known(mem, monkeypatch):
    """AC4.1: an unknown coordinate is NULL - never '', a list or 0,0,0,0."""
    mem.coord["value"] = None
    _quick_provider(monkeypatch, _ITEMS)
    _run(_bridge()._execute_web_search({"query": "tokyo population"}, "sess-1"))
    assert lane("research_memory").flush(10)
    assert len(mem.chain) == 1
    assert mem.chain[0]["coords_from"] is None and mem.chain[0]["coords_to"] is None


def test_record_without_summary_or_claims_stores_nothing(mem):
    assert rm.record_research({"query": "q", "summary": "", "claims": []}) is False
    assert lane("research_memory").flush(10)
    assert mem.store.list_by_format("research") == [] and mem.chain == []


def test_same_job_relands_one_row(mem):
    rec = {"query": "tokyo population", "summary": "Tokyo had 13,960,000 residents.",
           "job_id": "job-1", "conversation_id": "conv-A"}
    rm.record_research(dict(rec))
    rm.record_research(dict(rec))
    assert lane("research_memory").flush(10)
    assert len(mem.store.list_by_format("research")) == 1


def test_research_rows_are_never_offered_as_cards(mem):
    """A research record is memory, not a card: rehydration and the thread
    index must not list it (no phantom card)."""
    mem.store.store("doc-1", "conv-A", "markdown", "a real card body here", {}, [], "trusted")
    rm.record_research({"query": "tokyo population", "summary": "Tokyo had 13,960,000.",
                        "conversation_id": "conv-A"})
    assert lane("research_memory").flush(10)
    assert len(mem.store.list_by_format("research")) == 1
    cards = mem.store.list_for_conversation("conv-A", metadata_only=True)
    assert [c["document_id"] for c in cards] == ["doc-1"]
    full = mem.store.list_for_conversation("conv-A", metadata_only=False)
    assert [c["document_id"] for c in full] == ["doc-1"]
    assert {c["conversation_id"]: c["doc_count"] for c in mem.store.list_conversations()} == {"conv-A": 1}


def test_crawler_query_registry_result_gains_the_summary(mem, monkeypatch):
    """AC1.3: the agent path's registry result has an empty summary until the
    deferred extraction lands; the landing hook the orchestrator is given fills
    it in AND queues the record - also when it fires before the result is
    stored, and from another thread."""
    from backend.crawler.crawler_engine import CrawlResult, PageData
    from backend.crawler.job_registry import get_job_registry
    from unittest.mock import patch

    captured: dict = {}

    class _Orch:
        async def research(self, query, **kw):
            captured.update(kw)
            return CrawlResult(
                query=query, duration_ms=5, crawled_at="2026-09-30T00:00:00+00:00",
                pages=[PageData(url="https://stats.example.org/tokyo", title="Tokyo",
                                markdown="Tokyo is the capital of Japan. " * 12, html="", metadata={})],
            )

    with patch("backend.crawler.orchestrator.get_crawl_orchestrator", return_value=_Orch()):
        out = _run(_bridge()._execute_crawler_query({"query": "tokyo population"}, "sess-1"))
    assert out["success"] is True and out["summary"] == ""
    job_id = out["job_id"]
    hook = captured["on_dashboard"]
    assert captured["defer_extraction"] is True

    registry = get_job_registry()
    try:
        job = _run(registry.get(job_id))
        assert job.result["summary"] == ""
        dashboard = {"summary": "Tokyo had 13,960,000 residents in 2021.", "sections": []}
        landed = threading.Thread(
            target=hook,
            args=(dashboard, "Tokyo had 13,960,000 residents in 2021. [1](https://stats.example.org/tokyo)",
                  ["https://stats.example.org/tokyo"]),
        )
        landed.start()
        landed.join(10)
        assert _run(registry.get(job_id)).result["summary"] == "Tokyo had 13,960,000 residents in 2021."
        assert lane("research_memory").flush(10)
        rec = json.loads(mem.store.get(mem.store.list_by_format("research")[0]["document_id"])["content"])
        assert rec["job_id"] == job_id and rec["conversation_id"] == "conv-A"
        assert rec["claims"][0]["urls"] == ["https://stats.example.org/tokyo"]
        assert rec["dashboard"]["summary"].startswith("Tokyo had")
    finally:
        _run(registry.evict_now(job_id))


def test_registry_summary_landing_before_complete_is_kept():
    from backend.crawler.job_registry import JobRegistry

    async def go():
        reg = JobRegistry()
        await reg.register("j1", "s", "q")
        reg.attach_summary("j1", "early summary", "cited")
        await reg.complete("j1", {"summary": "", "content": "c"})
        return (await reg.get("j1")).result

    result = _run(go())
    assert result["summary"] == "early summary" and result["cited_markdown"] == "cited"


def test_deferred_extraction_hook_fires_after_the_caller_loop_closed():
    """The agent path's loop is gone by the time the extraction lands: the hook
    must still fire (it runs on the web_extract lane thread)."""
    from backend.crawler.crawl_planner import CrawlPlan
    from backend.crawler.crawler_engine import CrawlResult
    from backend.crawler.orchestrator import CrawlOrchestrator, Passage

    got: list = []
    done = threading.Event()

    class _Extractor:
        async def extract(self, result, instructions, result_type, title, pin_id=None):
            return {"title": title, "summary": "X is the quantum model.", "sections": []}

    orch = CrawlOrchestrator(planner=None, extractor=_Extractor())
    passages = [Passage(chunk_id="u#0", url="https://example.gov/doc", text="X is the quantum model")]

    def hook(dashboard, cited, urls):
        got.append((dashboard, cited, urls))
        done.set()

    async def submit_then_close_loop():
        orch._submit_deferred_extract(
            lambda *_a, **_k: None, query="what is X",
            fetched=CrawlResult(query="what is X", pages=[], duration_ms=1, crawled_at="x"),
            passages=passages, plan=CrawlPlan(urls=[], instructions="i", result_type="mixed", title="T"),
            cred_map=SimpleNamespace(unsourced_claims=[]), session_id="s", job_id="j", page_count=1,
            on_dashboard=hook,
        )

    asyncio.run(submit_then_close_loop())  # the loop is closed when this returns
    assert done.wait(15), "on_dashboard never fired"
    dashboard, cited, urls = got[0]
    assert dashboard["summary"] == "X is the quantum model."
    assert "[1](https://example.gov/doc)" in cited and urls == ["https://example.gov/doc"]


# ── R4 ─────────────────────────────────────────────────────────────────────


def test_recall_research_is_a_read_only_registry_tool_and_never_captured():
    from backend.agent.agent_kernel import AgentKernel
    from backend.agent.tool_registry import get_registry_tools, resolve_tool

    spec = resolve_tool("recall_research")
    assert spec is not None and spec.permission_tier == "read_only"
    assert spec.requires_internet is False and spec.parallel_safe is True
    assert set(spec.parameters) == {"query", "document_id"}
    assert "recall_research" in {t.get("name") for t in get_registry_tools()}
    assert "recall_research" in AgentKernel._DER_READ_TOOLS

    kernel = AgentKernel.__new__(AgentKernel)
    listing = {"success": True, "records": [{"id": "r", "claims": [{"text": "x" * 500}]}],
               "content": "x" * 800}
    assert AgentKernel._is_capture_worthy(kernel, "recall_research", listing) is False
    assert AgentKernel._is_capture_worthy(kernel, "crawler_query", listing) is True


def test_recall_research_reads_by_id_and_by_query_through_the_bridge(mem):
    rm.record_research({"query": "tokyo population", "conversation_id": "conv-A",
                        "summary": "Tokyo had 13,960,000 residents in 2021.",
                        "claims": [{"text": "Tokyo had 13,960,000 residents in 2021",
                                    "urls": ["https://stats.example.org/tokyo"]}]})
    assert lane("research_memory").flush(10)
    assert _wait(lambda: len(mem.episodic.fragments) == 1)
    doc_id = mem.store.list_by_format("research")[0]["document_id"]

    bridge = _bridge()
    by_id = _run(bridge.execute_tool("recall_research", {"document_id": doc_id}, session_id="sess-1"))
    assert by_id["success"] is True and by_id["records"][0]["id"] == doc_id
    assert "13,960,000" in by_id["content"] and "dashboard" not in by_id["records"][0]

    by_query = _run(bridge.execute_tool("recall_research", {"query": "tokyo population"}, session_id="sess-1"))
    assert by_query["success"] is True and by_query["records"][0]["id"] == doc_id
    assert "permission_response" not in by_query, "a store read must not raise a permission prompt"

    missing = _run(bridge.execute_tool("recall_research", {"document_id": "nope"}, session_id="sess-1"))
    assert missing["success"] is True and missing["records"] == []
    assert _run(bridge.execute_tool("recall_research", {}, session_id="sess-1"))["success"] is False


# ── R5 ─────────────────────────────────────────────────────────────────────


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api.research import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_research_history_lists_metadata_only_and_get_returns_the_record(mem):
    dashboard = {"title": "Tokyo", "summary": "Tokyo had 13,960,000 residents in 2021.", "sections": []}
    rm.land_dashboard("tokyo population", dashboard, "", ["https://stats.example.org/tokyo"],
                      conversation_id="conv-A", session_id="sess-1", job_id="job-A")
    rm.land_quick_search("osaka transit ridership", {
        "source_list": [{"title": "Osaka", "url": "https://o.example/1",
                        "snippet": "Osaka metro carries 2,400,000 riders daily."}],
        "sources": ["https://o.example/1"]}, conversation_id="conv-B", session_id="sess-2")
    assert lane("research_memory").flush(10)
    client = _client()

    body = client.get("/api/research/history").json()
    assert body["ok"] is True and body["count"] == 2
    assert {i["query"] for i in body["items"]} == {"tokyo population", "osaka transit ridership"}
    for item in body["items"]:
        assert set(item) == {"id", "query", "created_at", "conversation_id", "job_id",
                             "source_count", "claim_count"}, "metadata only - no content blob"

    only_a = client.get("/api/research/history", params={"conversation_id": "conv-A"}).json()
    assert [i["query"] for i in only_a["items"]] == ["tokyo population"]
    assert client.get("/api/research/history", params={"limit": 1}).json()["count"] == 1

    # `q` is a semantic filter (the stand-in matches words; the real one embeds).
    filtered = client.get("/api/research/history", params={"q": "tokyo residents"}).json()
    assert _wait(lambda: len(mem.episodic.fragments) == 2)
    filtered = client.get("/api/research/history", params={"q": "tokyo residents"}).json()
    assert [i["query"] for i in filtered["items"]] == ["tokyo population"]

    doc_id = only_a["items"][0]["id"]
    got = client.get(f"/api/research/{doc_id}")
    assert got.status_code == 200
    record = got.json()["record"]
    assert record["id"] == doc_id and record["summary"].startswith("Tokyo had")
    assert record["dashboard"]["title"] == "Tokyo", "the stored dashboard payload rides the record"

    missing = client.get("/api/research/research_doesnotexist")
    assert missing.status_code == 404 and missing.json()["ok"] is False


def test_get_refuses_a_document_that_is_not_research(mem):
    mem.store.store("doc-1", "conv-A", "markdown", "a real card body here", {}, [], "trusted")
    assert _client().get("/api/research/doc-1").status_code == 404
