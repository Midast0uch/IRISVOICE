"""
Caller-existence pin (CT-9 class of defect) + behavioral coverage for the
Exa search-provider wiring.

Evidence this contract guards against regressing:
  `grep -rn "get_search_provider()" backend/ | grep -v test` returned exactly
  ONE hit — backend/crawler/search_providers/__init__.py:8, the package's
  own usage-example DOCSTRING, not a call. crawl_planner.py never called
  get_search_provider(); it ran its own LLM-only planning path regardless of
  iris_config.json's search.provider / EXA_API_KEY. Live logs never showed
  "[SearchProvider] using Exa neural search" — a configured provider="exa"
  had literally no effect. This is the codebase's dominant failure mode
  (implemented, tested, never wired — 19+ instances tracked in this repo).

Run: python -m pytest backend/tests/contract/test_search_provider_wiring.py -v
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.crawler.crawl_planner import CrawlPlanner
from backend.crawler.search_providers.base import (
    SearchProviderError,
    SearchResult,
    SearchResultItem,
)
from backend.crawler.search_providers.exa import ExaSearchProvider
from backend.crawler.search_providers.llm import LLMSearchProvider

_REPO = Path(__file__).resolve().parents[3]


def _src(rel: str) -> str:
    p = _REPO / rel
    assert p.is_file(), f"expected {rel} to exist at {p}"
    return p.read_text(encoding="utf-8", errors="replace")


def _calls_in(rel: str, name: str) -> bool:
    """True when *rel* contains a real call to *name* (not just an import or
    a docstring mention). Parsed, so a mention inside a comment or docstring
    cannot satisfy the pin. Modeled on
    test_single_judge_and_wiring_contract.py's `_calls_in`."""
    tree = ast.parse(_src(rel))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == name:
                return True
            if isinstance(fn, ast.Attribute) and fn.attr == name:
                return True
    return False


# ══════════════════════════════════════════════════════════════════════════
# Caller-existence pin
# ══════════════════════════════════════════════════════════════════════════

def test_get_search_provider_has_a_production_caller():
    """get_search_provider() must be REACHED, not just importable.

    Before this fix, the only project-wide hit for "get_search_provider()"
    outside tests was the package's own docstring usage example — a
    configured provider='exa' + EXA_API_KEY had no production effect."""
    assert _calls_in("backend/crawler/crawl_planner.py", "get_search_provider"), (
        "get_search_provider has no production caller — a configured "
        "provider='exa' + EXA_API_KEY has no effect again"
    )


def test_docstring_example_alone_would_not_satisfy_the_pin():
    """Guards the exact false-positive that hid the original defect: a
    plain grep for 'get_search_provider()' also matches the package's own
    usage-example docstring. The AST-based pin above must find a real
    ast.Call node, which a docstring string cannot provide — this test
    documents that the docstring still exists (nothing weird happened to
    the file) while the caller-existence pin is what actually proves
    wiring, not the grep."""
    doc_src = _src("backend/crawler/search_providers/__init__.py")
    tree = ast.parse(doc_src)
    module_doc = ast.get_docstring(tree) or ""
    assert "get_search_provider()" in module_doc
    # This file itself has no ast.Call to get_search_provider — the
    # docstring mention does not count, confirming the pin is discriminating.
    assert not _calls_in(
        "backend/crawler/search_providers/__init__.py", "get_search_provider"
    )


# ══════════════════════════════════════════════════════════════════════════
# Fakes shared across behavioral tests
# ══════════════════════════════════════════════════════════════════════════

class _FakeKernel:
    """Stands in for the LLM kernel crawl_planner falls back to."""

    def __init__(self, responses=None, forbid=False):
        self._responses = list(responses or [])
        self.calls = 0
        self._forbid = forbid

    def _respond_direct(self, text, context):
        if self._forbid:
            raise AssertionError(
                "LLM kernel was called even though a configured search "
                "provider should have produced URLs"
            )
        self.calls += 1
        return self._responses.pop(0)


class _FakeRegistry:
    """Always MISSes so plan() reaches the provider/LLM steps, and records
    what it was told to learn (confirms Exa results feed the registry cache
    the same way the LLM path already does)."""

    def __init__(self):
        self.learned = []

    async def resolve(self, query):
        return {"hit": False, "sources": []}

    async def learn(self, query, result):
        self.learned.append((query, result))


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ══════════════════════════════════════════════════════════════════════════
# provider="exa" + key present -> ExaSearchProvider used, LLM never reached
# ══════════════════════════════════════════════════════════════════════════

def test_exa_provider_used_when_configured_and_key_present(caplog):
    """The real ExaSearchProvider class is used end-to-end (isinstance
    checks, calling convention). Its HTTP layer is mocked at the
    provider.search() boundary — no live network, per spec constraint."""
    exa = ExaSearchProvider(api_key="test-key-not-real")
    exa.search = AsyncMock(return_value=SearchResult(
        query="ai hardware companies",
        results=[
            SearchResultItem(url="https://example.com/a", score=0.9),
            SearchResultItem(url="https://example.com/b", score=0.8),
        ],
        provider="exa",
    ))

    kern = _FakeKernel(forbid=True)  # LLM must NOT be called
    reg = _FakeRegistry()
    planner = CrawlPlanner()

    with patch("backend.crawler.search_providers.get_search_provider", return_value=exa), \
         patch("backend.agent.get_agent_kernel", return_value=kern), \
         patch("backend.crawler.source_registry.get_source_registry", return_value=reg), \
         caplog.at_level("INFO"):
        plan = _run(planner.plan("ai hardware companies"))

    assert plan.urls == ["https://example.com/a", "https://example.com/b"]
    assert kern.calls == 0
    exa.search.assert_awaited_once()
    assert "source=exa urls=2" in caplog.text, (
        "no 'source=exa' log line — the path that produced the URLs is "
        "unanswerable from logs again (this is how the original defect "
        "survived undetected)"
    )
    # Exa results feed back into the registry cache, same as the LLM path.
    assert reg.learned and reg.learned[0][1].provider == "exa"


# ══════════════════════════════════════════════════════════════════════════
# provider="exa" + NO key -> falls back to LLM, does not crash
# ══════════════════════════════════════════════════════════════════════════

def test_exa_configured_without_key_falls_back_to_llm(monkeypatch):
    """get_search_provider() itself already falls back to LLMSearchProvider
    when provider='exa' is configured but EXA_API_KEY is unset (see
    search_providers/__init__.py get_search_provider). This pins that
    crawl_planner survives that fallback and reaches the LLM path normally
    rather than crashing on a missing key."""
    from backend.crawler import search_providers as sp_mod

    monkeypatch.setattr(
        sp_mod, "_read_search_config", lambda: {"provider": "exa", "exa_api_key": ""}
    )
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    sp_mod.clear_search_provider_cache()

    kern = _FakeKernel([
        '{"urls":["https://example.com/c"],"instructions":"extract",'
        '"result_type":"mixed","title":"T"}',
    ])
    reg = _FakeRegistry()
    planner = CrawlPlanner()

    try:
        with patch("backend.agent.get_agent_kernel", return_value=kern), \
             patch("backend.crawler.source_registry.get_source_registry", return_value=reg):
            plan = _run(planner.plan("some query"))
    finally:
        sp_mod.clear_search_provider_cache()

    assert plan.urls == ["https://example.com/c"]
    assert kern.calls == 1, (
        "missing-key Exa config must fall back to the LLM path, not crash"
    )


# ══════════════════════════════════════════════════════════════════════════
# provider="llm" -> LLM path unchanged
# ══════════════════════════════════════════════════════════════════════════

def test_llm_provider_configured_reaches_llm_path_directly():
    """provider='llm' (the default) behaves exactly as before this fix —
    straight to the LLM planning path, zero provider.search() detours."""
    llm_provider = LLMSearchProvider()

    kern = _FakeKernel([
        '{"urls":["https://example.com/d"],"instructions":"extract",'
        '"result_type":"mixed","title":"T"}',
    ])
    reg = _FakeRegistry()
    planner = CrawlPlanner()

    with patch("backend.crawler.search_providers.get_search_provider", return_value=llm_provider), \
         patch("backend.agent.get_agent_kernel", return_value=kern), \
         patch("backend.crawler.source_registry.get_source_registry", return_value=reg):
        plan = _run(planner.plan("some query"))

    assert plan.urls == ["https://example.com/d"]
    assert kern.calls == 1


# ══════════════════════════════════════════════════════════════════════════
# Exa returns zero results -> falls back to the LLM path, not a dead end
# ══════════════════════════════════════════════════════════════════════════

def test_exa_zero_results_falls_back_to_llm(caplog):
    exa = ExaSearchProvider(api_key="test-key-not-real")
    exa.search = AsyncMock(return_value=SearchResult(
        query="an obscure query", results=[], provider="exa",
    ))

    kern = _FakeKernel([
        '{"urls":["https://example.com/e"],"instructions":"extract",'
        '"result_type":"mixed","title":"T"}',
    ])
    reg = _FakeRegistry()
    planner = CrawlPlanner()

    with patch("backend.crawler.search_providers.get_search_provider", return_value=exa), \
         patch("backend.agent.get_agent_kernel", return_value=kern), \
         patch("backend.crawler.source_registry.get_source_registry", return_value=reg), \
         caplog.at_level("INFO"):
        plan = _run(planner.plan("an obscure query"))

    assert plan.urls == ["https://example.com/e"]
    assert kern.calls == 1, "zero Exa results must fall through to the LLM path"
    assert "source=exa urls=0" in caplog.text
    assert "source=llm urls=1" in caplog.text


# ══════════════════════════════════════════════════════════════════════════
# Exa error (auth/rate-limit/timeout/upstream) -> falls back, no crash
# ══════════════════════════════════════════════════════════════════════════

def test_exa_error_falls_back_to_llm_without_crashing(caplog):
    exa = ExaSearchProvider(api_key="test-key-not-real")
    exa.search = AsyncMock(side_effect=SearchProviderError("rate limited", retry_after=30.0))

    kern = _FakeKernel([
        '{"urls":["https://example.com/f"],"instructions":"extract",'
        '"result_type":"mixed","title":"T"}',
    ])
    reg = _FakeRegistry()
    planner = CrawlPlanner()

    with patch("backend.crawler.search_providers.get_search_provider", return_value=exa), \
         patch("backend.agent.get_agent_kernel", return_value=kern), \
         patch("backend.crawler.source_registry.get_source_registry", return_value=reg), \
         caplog.at_level("INFO"):
        plan = _run(planner.plan("some query"))

    assert plan.urls == ["https://example.com/f"]
    assert kern.calls == 1
    assert "source=exa failed" in caplog.text
