"""
Unit tests for CrawlPlanner retry-with-backoff (Issue C1).

The crawler's only URL source is the LLM (DuckDuckGo removed). A transient
rate-limit/timeout on that single LLM call used to silently collapse to an
empty plan -> "no candidate urls" -> research DER step fails with no recovery.
_plan_with_retry retries transient failures with backoff before falling back.
"""
import asyncio
from unittest.mock import patch

from backend.crawler.crawl_planner import CrawlPlanner


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeKernel:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def _respond_direct(self, text, context):
        self.calls += 1
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class _FakeRegistry:
    async def resolve(self, query):
        return {"hit": False, "sources": []}

    async def learn(self, query, result):
        return None


def _planner_with(kernel, registry):
    planner = CrawlPlanner()
    return planner, kernel, registry


def test_planner_retries_transient_failure_then_succeeds():
    kern = _FakeKernel([
        RuntimeError("rate limited"),
        '{"urls":["https://example.com/a"],"instructions":"extract",'
        '"result_type":"mixed","title":"T"}',
    ])
    reg = _FakeRegistry()
    planner = CrawlPlanner()
    with patch("backend.agent.get_agent_kernel", return_value=kern), \
         patch("backend.crawler.source_registry.get_source_registry", return_value=reg):
        plan = _run(planner.plan("best laptops 2026"))
    assert plan.urls == ["https://example.com/a"]
    assert kern.calls == 2  # first failed, second succeeded


def test_planner_falls_back_after_persistent_failure():
    kern = _FakeKernel([RuntimeError("boom"), RuntimeError("boom"), RuntimeError("boom")])
    reg = _FakeRegistry()
    planner = CrawlPlanner()
    with patch("backend.agent.get_agent_kernel", return_value=kern), \
         patch("backend.crawler.source_registry.get_source_registry", return_value=reg):
        plan = _run(planner.plan("some query"))
    assert plan.urls == []  # empty fallback after exhausting retries
    assert kern.calls == 3


def test_planner_no_retry_when_llm_returns_no_urls():
    # A response that arrives but yields no URLs is NOT a transient error,
    # so it must NOT be retried.
    kern = _FakeKernel(['{"urls":[],"instructions":"x","result_type":"mixed","title":"T"}'])
    reg = _FakeRegistry()
    planner = CrawlPlanner()
    with patch("backend.agent.get_agent_kernel", return_value=kern), \
         patch("backend.crawler.source_registry.get_source_registry", return_value=reg):
        plan = _run(planner.plan("some query"))
    assert plan.urls == []
    assert kern.calls == 1
