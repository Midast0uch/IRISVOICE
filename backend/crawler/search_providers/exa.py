"""
ExaSearchProvider — neural web search via Exa API (https://exa.ai).

Uses Exa's embedding-based search to find pages by *meaning* rather than
keywords. Returns both URLs and extracted content (highlights + full text).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from backend.crawler.search_providers.base import (
    SearchProvider,
    SearchResult,
    SearchResultItem,
    SearchProviderError,
)

logger = logging.getLogger(__name__)

_EXA_BASE_URL = "https://api.exa.ai"
_SEARCH_TIMEOUT_S = 30.0


class ExaSearchProvider(SearchProvider):
    """Search provider using Exa's neural embedding API.

    Reads ``EXA_API_KEY`` from the environment by default. A key can also be
    passed directly to the constructor (useful for testing).

    Raises ``ValueError`` if no API key is available.
    """

    def __init__(self, api_key: Optional[str] = None):
        if api_key is None:
            api_key = os.environ.get("EXA_API_KEY")
        if not api_key:
            raise ValueError(
                "EXA_API_KEY is not set. Provide the key to the constructor "
                "or set the EXA_API_KEY environment variable."
            )
        self._client = httpx.AsyncClient(
            base_url=_EXA_BASE_URL,
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
            },
            timeout=_SEARCH_TIMEOUT_S,
        )

    async def search(self, query: str, max_results: int = 10) -> SearchResult:
        """Execute a neural search via the Exa API.

        Args:
            query: The search query (natural language).
            max_results: Number of results to return (1-100).

        Returns:
            A ``SearchResult`` with items containing URLs, titles, snippets
            (from highlights) and full text content.

        Raises:
            SearchProviderError: On API errors (auth, rate-limit, timeout).
        """
        if not query or not query.strip():
            logger.debug("[ExaSearchProvider] empty query")
            return SearchResult(query=query, provider="exa")

        try:
            resp = await self._client.post("/search", json={
                "query": query,
                "numResults": max_results,
                "type": "auto",
                "contents": {
                    "text": True,
                    "highlights": True,
                },
            })
        except httpx.TimeoutException:
            raise SearchProviderError("upstream timeout")
        except httpx.RequestError as exc:
            raise SearchProviderError(f"request failed: {exc}")

        if resp.status_code == 401:
            raise SearchProviderError("invalid API key")
        if resp.status_code == 429:
            retry_after: Optional[float] = None
            try:
                retry_after = float(resp.headers.get("Retry-After", ""))
            except (ValueError, TypeError):
                pass
            raise SearchProviderError("rate limited", retry_after=retry_after)
        if resp.status_code >= 500:
            raise SearchProviderError(f"upstream error (HTTP {resp.status_code})")

        try:
            data = resp.json()
        except Exception:
            raise SearchProviderError("unexpected response (non-JSON)")

        results = data.get("results", [])
        items = []
        for r in results:
            content = r.get("content") or {}
            content_text = content.get("text") or ""
            highlights = content.get("highlights") or []
            snippet = " ".join(highlights[:3]) if highlights else content_text[:500]

            items.append(SearchResultItem(
                url=r.get("url", ""),
                title=r.get("title", ""),
                snippet=snippet,
                content=content_text or " ".join(highlights),
                score=r.get("score", 0.0),
                published_date=r.get("publishedDate", ""),
                metadata=r,
            ))

        logger.info(
            "[ExaSearchProvider] %d result(s) for %r", len(items), query[:60]
        )
        return SearchResult(query=query, results=items, provider="exa")

    async def close(self):
        """Release the HTTP client (call when shutting down)."""
        await self._client.aclose()
