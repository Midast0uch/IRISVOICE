"""
Contract tests for ExaSearchProvider.

Tests verify:
1. HTTP payload shape sent to Exa API
2. Response mapping (full fields, empty fields)
3. Error mapping (401, 429, timeout, non-JSON)
4. Missing API key
"""
from __future__ import annotations

import os
from unittest.mock import ANY

import httpx
import pytest
from pytest_httpx import HTTPXMock

from backend.crawler.search_providers.exa import ExaSearchProvider
from backend.crawler.search_providers.base import SearchProviderError


# ── Helpers ─────────────────────────────────────────────────────────────

_SAMPLE_RESPONSE = {
    "results": [
        {
            "url": "https://example.com/article",
            "title": "Test Article",
            "publishedDate": "2026-07-15",
            "author": "Jane Doe",
            "score": 0.95,
            "content": {
                "text": "Full article text here...",
                "highlights": ["Key excerpt one", "Key excerpt two"],
            },
        },
        {
            "url": "https://other.com/page",
            "title": "Other Page",
            "publishedDate": "",
            "author": "",
            "score": 0.75,
            "content": None,
        },
    ],
}


@pytest.fixture
def provider():
    """ExaSearchProvider with a test API key (no real HTTP calls)."""
    return ExaSearchProvider(api_key="test-key-123")


# ── Payload shape ───────────────────────────────────────────────────────

class TestExaPayloadShape:
    """REQ-2 AC2: verify the POST body sent to Exa."""

    def test_sends_correct_endpoint_and_headers(self, provider, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json={"results": []})
        import anyio
        async def go():
            await provider.search("test query")
            request = httpx_mock.get_request()
            assert request is not None
            assert request.url == "https://api.exa.ai/search"
            assert request.headers["x-api-key"] == "test-key-123"
            assert request.headers["content-type"] == "application/json"
        anyio.run(go)

    def test_sends_query_and_num_results(self, provider, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json={"results": []})
        import anyio, json
        async def go():
            await provider.search("semiconductor market share", max_results=5)
            request = httpx_mock.get_request()
            assert request is not None, "no HTTP request was made"
            body = json.loads(request.content)
            assert body["query"] == "semiconductor market share"
            assert body["numResults"] == 5
            assert body["type"] == "auto"
            assert body["contents"]["text"] is True
            assert body["contents"]["highlights"] is True
        anyio.run(go)

    def test_empty_query_returns_empty(self, provider, httpx_mock: HTTPXMock):
        # Empty query should not call the API
        import anyio
        async def go():
            result = await provider.search("")
            assert result.query == ""
            assert len(result.results) == 0
            assert result.provider == "exa"
            # Verify no HTTP call was made
            assert httpx_mock.get_request() is None
        anyio.run(go)


# ── Response mapping ────────────────────────────────────────────────────

class TestExaResponseMapping:
    """REQ-2 AC3: verify Exa JSON → SearchResultItem mapping."""

    def test_maps_full_response(self, provider, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json=_SAMPLE_RESPONSE)
        import anyio
        async def go():
            result = await provider.search("nvidia market share")
            assert len(result.results) == 2
            assert result.provider == "exa"

            r0 = result.results[0]
            assert r0.url == "https://example.com/article"
            assert r0.title == "Test Article"
            assert "Key excerpt one" in r0.snippet
            assert "Full article text" in r0.content
            assert r0.score == 0.95
            assert r0.published_date == "2026-07-15"

            r1 = result.results[1]
            assert r1.url == "https://other.com/page"
            assert r1.title == "Other Page"
            assert r1.snippet == ""   # no content block → empty
            assert r1.content == ""    # no content block → empty
            assert r1.score == 0.75
        anyio.run(go)

    def test_empty_results_list(self, provider, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json={"results": []})
        import anyio
        async def go():
            result = await provider.search("anything")
            assert len(result.results) == 0
            assert result.provider == "exa"
        anyio.run(go)


# ── Error mapping ───────────────────────────────────────────────────────

class TestExaErrorMapping:
    """REQ-2 edge cases: error responses mapped to SearchProviderError."""

    def test_401_raises_invalid_key(self, provider, httpx_mock: HTTPXMock):
        httpx_mock.add_response(status_code=401)
        import anyio
        async def go():
            with pytest.raises(SearchProviderError) as exc:
                await provider.search("test")
            msg = str(exc.value).lower()
            assert "invalid" in msg and "key" in msg
        anyio.run(go)

    def test_429_raises_rate_limited(self, provider, httpx_mock: HTTPXMock):
        httpx_mock.add_response(status_code=429, headers={"Retry-After": "30"})
        import anyio
        async def go():
            with pytest.raises(SearchProviderError) as exc:
                await provider.search("test")
            msg = str(exc.value).lower()
            assert "rate" in msg and "limited" in msg
            assert exc.value.retry_after == 30.0
        anyio.run(go)

    def test_429_no_retry_after(self, provider, httpx_mock: HTTPXMock):
        httpx_mock.add_response(status_code=429)
        import anyio
        async def go():
            with pytest.raises(SearchProviderError) as exc:
                await provider.search("test")
            msg = str(exc.value).lower()
            assert "rate" in msg and "limited" in msg
            assert exc.value.retry_after is None
        anyio.run(go)

    def test_500_raises_upstream_error(self, provider, httpx_mock: HTTPXMock):
        httpx_mock.add_response(status_code=502)
        import anyio
        async def go():
            with pytest.raises(SearchProviderError) as exc:
                await provider.search("test")
            msg = str(exc.value).lower()
            assert "upstream" in msg
        anyio.run(go)

    def test_timeout_raises_upstream_timeout(self, provider, httpx_mock: HTTPXMock):
        httpx_mock.add_exception(httpx.ReadTimeout("timed out"))
        import anyio
        async def go():
            with pytest.raises(SearchProviderError) as exc:
                await provider.search("test")
            assert "timeout" in str(exc.value).lower()
        anyio.run(go)

    def test_non_json_response(self, provider, httpx_mock: HTTPXMock):
        httpx_mock.add_response(text="<html>not json</html>")
        import anyio
        async def go():
            with pytest.raises(SearchProviderError) as exc:
                await provider.search("test")
            msg = str(exc.value).lower()
            assert "non-json" in msg or "unexpected" in msg
        anyio.run(go)


# ── Missing key ─────────────────────────────────────────────────────────

class TestExaMissingKey:
    """REQ-2 AC5: missing API key raises ValueError."""

    def test_no_key_raises_value_error(self):
        with pytest.raises(ValueError, match="EXA_API_KEY"):
            ExaSearchProvider(api_key="")  # empty
        with pytest.raises(ValueError, match="EXA_API_KEY"):
            ExaSearchProvider(api_key=None)
