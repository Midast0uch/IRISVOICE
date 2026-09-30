"""Spec A4 (websearch-vision-browser, REQ-1 AC1.3-1.4, RC4): factual web goals try `search` first.

`_mem_lookup` (the gather gate) used to hard-route EVERY web goal to `crawler_query` with the
whole goal sentence as the query - the heavy multi-page crawl for a one-line fact. Now:

- a web goal resolves to `search` (quick tier) with the question shaped out of the sentence;
- a quick result that says `requires_deep_crawl` escalates the NEXT web goal to
  `crawler_query`, ONCE;
- the quick envelope carries title/url/snippet per source and the `requires_deep_crawl` flag
  (True under 300 chars of combined content).

Hermetic: no live web, no model.
"""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from backend.agent import tool_bridge as tb
from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_execution_ledger import make_action_key
from backend.agent.explorer import _is_web_intent
from backend.crawler.search_providers.base import SearchResult, SearchResultItem

# the real eval prompts (evals/tasks.json r01..r08) - the goals the quick tier must serve
_EVAL_GOALS = [
    "Who created the Python programming language, and in what year was its first version "
    "released? Search the web to confirm.",
    "Search the web: which RFC number defines the WebSocket protocol?",
    "Look up who wrote the paper 'Attention Is All You Need' and the year it was published.",
    "What is the tallest mountain in Africa, and how tall is it in meters? Check a source online.",
    "Look up which open-source license the FastAPI project on GitHub uses.",
    "Search the web for the populations of Tokyo and Osaka and tell me which city is larger.",
    "Using a web search, find the year the first iPhone was released and the company that made it.",
    "What does the HTTP status code 418 mean? Look it up.",
]
_FILLER = ("search the web", "look up", "check a source online", "using a web search",
           "look it up", "to confirm")


def _kernel_and_lookup(monkeypatch):
    monkeypatch.setattr("backend.agent.tool_registry.capability_allowed", lambda _spec: True)
    k = AgentKernel.__new__(AgentKernel)
    k._memory_interface = SimpleNamespace(_mycelium=SimpleNamespace())
    k.session_id = f"sess_{uuid.uuid4().hex[:8]}"
    k.conversation_id = f"conv_{uuid.uuid4().hex[:8]}"
    k._der_crawl_attempts = {}
    k._der_task_class = "full"
    k._der_completed_tools = []
    k._router = SimpleNamespace()
    k._tool_bridge = SimpleNamespace()
    k._tool_box = None
    k.infer = lambda *a, **kw: "reason"  # type: ignore[method-assign]
    return k, k._get_tool_box()._memory_lookup


@pytest.mark.parametrize("goal", _EVAL_GOALS)
def test_shaper_strips_the_how_to_look_filler(goal):
    from backend.agent.explorer import _shape_web_query

    query = _shape_web_query(goal)
    assert query and query != goal
    assert not any(f in query.lower() for f in _FILLER), query
    assert len(query.split()) >= 4, "the question itself must survive"


@pytest.mark.parametrize("goal", [g for g in _EVAL_GOALS if _is_web_intent(g)])
def test_factual_web_goal_resolves_to_search_with_a_shaped_query(monkeypatch, goal):
    # (the gate hints only goals the web-intent check accepts; engine-less here, so the
    # keyword triggers decide - "Look up ..." / "Check a source online" are the engine's call)
    _k, lookup = _kernel_and_lookup(monkeypatch)

    hint = lookup(goal)

    assert hint and hint["tool"] == "search", hint
    query = hint["params"]["query"]
    assert query and query != goal
    assert not any(f in query.lower() for f in _FILLER), query
    assert set(hint["params"]) == {"query"}, "search takes only a query"


def test_search_the_web_no_longer_reaches_the_query(monkeypatch):
    _k, lookup = _kernel_and_lookup(monkeypatch)
    hint = lookup("Search the web for recent Python 3.13 features")
    assert hint["tool"] == "search"
    assert "search the web" not in hint["params"]["query"].lower()
    assert "python 3.13 features" in hint["params"]["query"].lower()


def test_requires_deep_crawl_escalates_to_crawler_query_once(monkeypatch):
    k, lookup = _kernel_and_lookup(monkeypatch)
    goal = "Search the web: which RFC number defines the WebSocket protocol?"

    # 1. first resolution: quick tier
    assert lookup(goal)["tool"] == "search"

    # 2. the search was dispatched (the gate's bookkeeping marks the goal attempted) and came
    #    back insufficient
    k._der_crawl_attempts[k.conversation_id] = {make_action_key(goal)}
    k._der_note_quick_tier("search", {"success": True, "requires_deep_crawl": True})

    # 3. the SAME goal now escalates - not steered to "already gathered", not search again
    esc = lookup(goal)
    assert esc["tool"] == "crawler_query", esc
    assert esc["params"]["query"] == goal

    # 4. once: dispatching the crawl spends the escalation
    k._der_note_quick_tier("crawler_query", {"success": True})
    assert lookup(goal)["tool"] != "crawler_query", "the escalation fired twice"


def test_a_sufficient_quick_result_does_not_escalate(monkeypatch):
    k, lookup = _kernel_and_lookup(monkeypatch)
    k._der_note_quick_tier("search", {"success": True, "requires_deep_crawl": False})
    assert lookup("Search the web for which license FastAPI uses")["tool"] == "search"


def test_the_escalation_flag_is_per_conversation(monkeypatch):
    k, lookup = _kernel_and_lookup(monkeypatch)
    k._der_note_quick_tier("search", {"requires_deep_crawl": True})
    k.conversation_id = "some-other-conversation"
    assert lookup("Search the web for which license FastAPI uses")["tool"] == "search"


# ── the quick envelope (AC1.4) ───────────────────────────────────────────────

class _FakeProvider:
    def __init__(self, items):
        self._items = list(items)

    async def search(self, query, max_results=10):
        return SearchResult(query=query, results=self._items[:max_results], provider="exa")


def _quick(monkeypatch, items):
    from backend.crawler import search_providers as sp_mod

    monkeypatch.setattr(sp_mod, "get_search_provider", lambda: _FakeProvider(items))
    env, fallback = asyncio.run(
        tb._quick_search_via_provider("q", 5, lambda _p: None, lambda *a, **k: None)
    )
    assert fallback == "" and env is not None
    return env


def test_thin_quick_result_requires_deep_crawl(monkeypatch):
    env = _quick(monkeypatch, [
        SearchResultItem(url="https://e.com/1", title="T1", snippet="short", content="short"),
        SearchResultItem(url="https://e.com/2", title="T2", snippet="also short", content=""),
    ])
    assert env["requires_deep_crawl"] is True


def test_title_and_url_stand_in_is_not_content(monkeypatch):
    """An item with NO body falls back to its title/url in the blob - that must not count."""
    env = _quick(monkeypatch, [
        SearchResultItem(url="https://e.com/" + "x" * 400, title="T" * 400),
    ])
    assert env["requires_deep_crawl"] is True


def test_full_quick_result_does_not_require_deep_crawl_and_lists_sources(monkeypatch):
    body = "A fact-bearing sentence about the topic. " * 10  # 410 chars
    env = _quick(monkeypatch, [
        SearchResultItem(url="https://e.com/1", title="T1", snippet="snip one", content=body),
        SearchResultItem(url="https://e.com/2", title="T2", snippet="snip two", content=body),
    ])
    assert env["requires_deep_crawl"] is False
    assert env["source_list"] == [
        {"title": "T1", "url": "https://e.com/1", "snippet": "snip one"},
        {"title": "T2", "url": "https://e.com/2", "snippet": "snip two"},
    ]
    assert env["sources"] == ["https://e.com/1", "https://e.com/2"]
