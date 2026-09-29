"""Contract tests: quick-search tier wiring (REQ-8, T11).

CT-DEI-4 — Quick-Search Path Contract: `search` is served by
``backend/crawler/search_providers/`` with ZERO browser-subprocess spawns and
no LLM URL planning, ``crawler_query`` keeps the deep CrawlOrchestrator path,
and the two registry descriptions separate the tiers.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

from backend.agent.tool_bridge import AgentToolBridge
from backend.crawler.search_providers.base import SearchResult, SearchResultItem

_REPO = Path(__file__).resolve().parents[3]


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeProvider:
    """A REAL-provider stand-in (never the LLM URL generator)."""

    def __init__(self, items):
        self._items = list(items)
        self.calls = 0
        self.queries: list = []

    async def search(self, query, max_results=10):
        self.calls += 1
        self.queries.append(query)
        return SearchResult(query=query, results=self._items[:max_results],
                            provider="exa")


# ---------------------------------------------------------------------------
# AC8.1 — provider path, no subprocess, no LLM planning
# ---------------------------------------------------------------------------


def test_provider_path_no_subprocess(monkeypatch):
    """AC8.1 / CT-DEI-4: the quick tier answers from the provider layer and
    never constructs the CrawlOrchestrator (the browser subprocess)."""
    from backend.agent import tool_bridge as tb
    from backend.crawler import search_providers as sp_mod
    import backend.crawler.orchestrator as orch_mod

    fake = _FakeProvider([
        SearchResultItem(url="https://e.com/a", title="A", content="body a"),
        SearchResultItem(url="https://e.com/b", title="B", snippet="snip b"),
    ])
    monkeypatch.setattr(sp_mod, "get_search_provider", lambda: fake)

    constructed: list = []

    class _ForbiddenOrchestrator:
        def __init__(self, *a, **kw):
            constructed.append(True)
            raise AssertionError("CrawlOrchestrator constructed on the quick path")

    monkeypatch.setattr(orch_mod, "CrawlOrchestrator", _ForbiddenOrchestrator)

    out = _run(AgentToolBridge()._execute_web_search(
        {"query": "rtx 5090 price"}, "s-quick"))

    assert constructed == [], (
        "the browser crawl subprocess was spawned on the quick-search tier "
        "(AC8.1 forbids it)"
    )
    assert fake.calls == 1, "the provider layer was not the thing that answered"
    assert out["success"] is True
    assert out["sources"] == ["https://e.com/a", "https://e.com/b"]
    assert out["trust"] == "untrusted"
    assert out["meta"]["quick_search"] is True
    assert out["meta"]["provider"] == "exa"
    assert "body a" in out["content"]
    assert "snip b" in out["content"]


def test_provider_path_falls_back_to_deep_path(monkeypatch):
    """REQ-8 edge: zero results degrades to the deep path, recorded in meta —
    and never fails the step."""
    from backend.agent import tool_bridge as tb
    from backend.crawler import search_providers as sp_mod
    import backend.crawler.orchestrator as orch_mod

    monkeypatch.setattr(sp_mod, "get_search_provider",
                        lambda: _FakeProvider([]))

    used: list = []

    class _FakePage:
        url = "https://deep.example/x"
        markdown = "deep body"
        error = None

    class _FakeCrawl:
        error = None
        pages = [_FakePage()]

    class _FakeOrch:
        def __init__(self, *a, **kw):
            used.append(True)

        async def research(self, **kw):
            return _FakeCrawl()

    monkeypatch.setattr(orch_mod, "CrawlOrchestrator", _FakeOrch)

    out = _run(AgentToolBridge()._execute_web_search(
        {"query": "an obscure thing"}, "s-fb"))

    assert used == [True], "zero provider results must fall back to the deep path"
    assert out["success"] is True
    assert out["sources"] == ["https://deep.example/x"]
    assert out["meta"]["quick_search_fallback"] == "provider_zero_results"


# ---------------------------------------------------------------------------
# AC8.3 — crawler_query keeps the deep path
# ---------------------------------------------------------------------------


def _func_source(cls_src: str, name: str) -> str:
    """Source text of one method, found by AST (no text-matching games)."""
    tree = ast.parse(cls_src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(cls_src, node) or ""
    raise AssertionError(f"{name} not found")


def test_crawler_path_unchanged():
    """AC8.3: `crawler_query` still constructs CrawlOrchestrator and never
    routes through the quick-search helper."""
    src = (_REPO / "backend" / "agent" / "tool_bridge.py").read_text(
        encoding="utf-8", errors="replace")
    body = _func_source(src, "_execute_crawler_query")

    assert "CrawlOrchestrator" in body, (
        "crawler_query no longer uses the CrawlOrchestrator deep path (AC8.3)"
    )
    assert "_quick_search_via_provider" not in body, (
        "crawler_query was rerouted onto the quick-search tier — AC8.3 requires "
        "it to keep the deep multi-page path"
    )


def test_crawler_path_does_not_consult_the_provider_layer(monkeypatch):
    """AC8.3: the provider layer is never consulted for `crawler_query`."""
    from backend.crawler import search_providers as sp_mod
    import backend.crawler.orchestrator as orch_mod

    def _forbidden():
        raise AssertionError("crawler_query consulted the quick-search provider")

    monkeypatch.setattr(sp_mod, "get_search_provider", _forbidden)

    class _FakeOrch:
        async def research(self, **kw):
            raise RuntimeError("orchestrator reached — the deep path is intact")

    monkeypatch.setattr(orch_mod, "CrawlOrchestrator", _FakeOrch)

    # Reaching the orchestrator IS the assertion; the provider must not be
    # touched first (it would raise AssertionError instead).
    out = _run(AgentToolBridge()._execute_crawler_query(
        {"query": "deep research topic"}, "s-deep"))
    assert out["success"] is False  # the fake orchestrator raised on purpose


# ---------------------------------------------------------------------------
# AC8.4 — registry descriptions separate the tiers
# ---------------------------------------------------------------------------


def test_registry_descriptions_split():
    """AC8.4: the engine menu must be able to tell the tiers apart from the
    description alone — the discriminator has to survive the 90-char frame
    truncation."""
    from backend.agent.tool_registry import register_builtin_tools, resolve_tool

    register_builtin_tools()
    search = resolve_tool("search")
    crawler = resolve_tool("crawler_query")
    assert search is not None and crawler is not None

    s_desc = search.description
    c_desc = crawler.description
    assert s_desc != c_desc

    # The discriminator is in the FIRST 90 chars — that is what the engine's
    # option frame actually carries (tool_decision.py desc_map [:90]).
    s_head = s_desc[:90].lower()
    c_head = c_desc[:90].lower()
    assert "instant" in s_head, f"search head lacks the instant-lookup marker: {s_head!r}"
    assert "deep" in c_head, f"crawler_query head lacks the deep marker: {c_head!r}"

    # And each points at the other, so the choice is not a guess.
    assert "crawler_query" in s_desc
    assert "search" in c_desc
