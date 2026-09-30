"""
Contract tests: the Exa quick tier (websearch-vision-browser spec, A1 / REQ-1 AC1.1-1.2).

Two code bugs emptied the quick tier (RC3, measured 2026-09-30):

1. Exa returns ``text`` / ``highlights`` at each result's TOP level; the provider read
   ``r["content"]`` -> every item had empty content and snippet.
2. A module-cached ``httpx.AsyncClient`` was reused on the fresh event loop every tool call
   runs in -> "Event loop is closed" -> the quick tier fell back to the full crawl.

``exa_search_response.json`` is a REAL Exa response body (one live call, 2026-09-30, API key
never stored; ``text`` trimmed to 2000 chars to keep the fixture small).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from pytest_httpx import HTTPXMock

from backend.crawler.search_providers.exa import ExaSearchProvider

_FIXTURE = Path(__file__).resolve().parent.parent / "data" / "exa_search_response.json"


def _real_body() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_real_response_items_carry_content_and_snippet(httpx_mock: HTTPXMock):
    """AC1.1: a recorded real response parses into items with content AND snippet."""
    body = _real_body()
    assert body["results"], "fixture must hold results"
    # the real shape: text/highlights at the TOP level, no nested "content" block
    assert all("text" in r and "content" not in r for r in body["results"])

    httpx_mock.add_response(json=body)
    result = asyncio.run(ExaSearchProvider(api_key="test-key").search("python creator"))

    assert len(result.results) == len(body["results"])
    for item, raw in zip(result.results, body["results"]):
        assert item.url == raw["url"]
        assert item.title == raw["title"]
        assert item.content.strip(), f"empty content for {item.url}"
        assert item.snippet.strip(), f"empty snippet for {item.url}"
        assert item.content == raw["text"]
        assert raw["highlights"][0] in item.snippet


def test_nested_content_block_still_parses(httpx_mock: HTTPXMock):
    """AC1.1 fallback: the older nested ``content.text`` shape keeps working."""
    httpx_mock.add_response(json={"results": [{
        "url": "https://example.com/a", "title": "A",
        "content": {"text": "nested body", "highlights": ["nested hl"]},
    }]})
    item = asyncio.run(ExaSearchProvider(api_key="test-key").search("q")).results[0]
    assert item.content == "nested body"
    assert item.snippet == "nested hl"


def test_two_searches_on_two_event_loops_both_succeed(httpx_mock: HTTPXMock, monkeypatch):
    """AC1.2: one cached provider, two separate ``asyncio.run`` loops (how each tool call
    runs). Both must succeed, and no HTTP client may be shared across the two loops -
    a client bound to the first (closed) loop is what raised "Event loop is closed"."""
    body = _real_body()
    httpx_mock.add_response(json=body)
    httpx_mock.add_response(json=body)

    used_clients: list = []  # objects, not ids: a freed client's id can be reused
    _Real = httpx.AsyncClient

    class _SpyClient(_Real):
        async def post(self, *a, **kw):
            used_clients.append(self)
            return await super().post(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", _SpyClient)

    provider = ExaSearchProvider(api_key="test-key")  # built once, like the cached singleton
    first = asyncio.run(provider.search("first query"))
    second = asyncio.run(provider.search("second query"))

    assert first.results and second.results
    assert len(used_clients) == 2
    assert used_clients[0] is not used_clients[1], (
        "the same httpx client served two event loops - it will be bound to a closed loop"
    )
