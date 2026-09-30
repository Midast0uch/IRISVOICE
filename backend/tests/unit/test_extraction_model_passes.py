"""Spec A5, the parts that do not move work off the answer path (REQ-3 AC3.2-3.3, RC5).

- AC3.2: the DataExtractor's model call uses the light inference path (`infer`, no tools), never
  `_respond_direct` (episodic retrieval + tool attachment + an 8-round tool loop).
- AC3.3: topic extraction for the source registry makes at most ONE model call per distinct
  query, however many callers ask (one search used to make four ~1 s calls on the same query).

Hermetic: the kernel and the model call are stubs.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from backend.crawler.data_extractor import DataExtractor
from backend.crawler.search_providers.base import SearchResult, SearchResultItem
from backend.crawler.source_registry import SourceRegistry


class _Kernel:
    def __init__(self):
        self.infer_calls: list[dict] = []
        self.direct_calls = 0

    def infer(self, prompt, role="EXECUTION", max_tokens=200, temperature=0.0):
        self.infer_calls.append({"role": role, "max_tokens": max_tokens})
        return SimpleNamespace(raw_text='{"title": "T", "summary": "S", "sections": []}')

    def _respond_direct(self, text, context):
        self.direct_calls += 1
        return "{}"


def test_extractor_model_call_is_the_light_path(monkeypatch):
    kernel = _Kernel()
    monkeypatch.setattr("backend.agent.get_agent_kernel", lambda *a, **k: kernel)

    raw = DataExtractor()._call_llm("extract this")

    assert json.loads(raw)["summary"] == "S"
    assert len(kernel.infer_calls) == 1
    assert kernel.direct_calls == 0, "the extractor went through _respond_direct"
    assert kernel.infer_calls[0]["max_tokens"] >= 1000, "a dashboard JSON needs room"


def test_extractor_light_path_failure_returns_empty_text_not_a_raise(monkeypatch):
    class _Dead(_Kernel):
        def infer(self, *a, **k):
            return SimpleNamespace(raw_text="")

    monkeypatch.setattr("backend.agent.get_agent_kernel", lambda *a, **k: _Dead())
    assert DataExtractor()._call_llm("x") == ""


def _registry_with_counter(monkeypatch):
    reg = SourceRegistry()
    calls: list[str] = []

    def _call_llm(prompt):
        calls.append(prompt)
        return '["python", "guido van rossum"]'

    monkeypatch.setattr(reg, "_call_llm", _call_llm)
    return reg, calls


def test_one_topic_model_call_per_distinct_query(monkeypatch):
    reg, calls = _registry_with_counter(monkeypatch)
    q = "who created python and when"

    async def go():
        # the four callers of one search: plan (resolve), rerank-learn, tool-bridge learn, resolve
        await reg.resolve(q)
        await reg.learn(q, SearchResult(query=q, results=[SearchResultItem(url="https://a.com/x")]))
        await reg.learn(q, SearchResult(query=q, results=[SearchResultItem(url="https://b.com/x")]))
        await reg.resolve(q.upper())  # same query, different case

    asyncio.run(go())
    assert len(calls) == 1, f"{len(calls)} topic-extraction model calls for ONE query"


def test_a_different_query_is_a_different_model_call(monkeypatch):
    reg, calls = _registry_with_counter(monkeypatch)

    async def go():
        await reg._extract_topics("query one")
        await reg._extract_topics("query two")
        await reg._extract_topics("query one")

    asyncio.run(go())
    assert len(calls) == 2


def test_topic_cache_is_bounded(monkeypatch):
    import backend.crawler.source_registry as sr

    monkeypatch.setattr(sr, "_TOPIC_CACHE_MAX", 3)
    reg, calls = _registry_with_counter(monkeypatch)

    async def go():
        for i in range(10):
            await reg._extract_topics(f"distinct query {i}")

    asyncio.run(go())
    assert len(reg._topic_cache) == 3
    assert len(calls) == 10
