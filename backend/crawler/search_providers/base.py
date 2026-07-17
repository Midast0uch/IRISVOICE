"""
SearchProvider abstraction layer.

Defines the common interface for all search backends (Exa, LLM, Brave, Tavily).
New providers inherit from ``SearchProvider`` and implement ``search()``.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SearchResultItem:
    """One search result from any provider.

    Fields:
        url:             The result URL.
        title:           Page title (may be empty if not returned by provider).
        snippet:         Short excerpt / highlights for quick display (~500 chars).
        content:         Full extracted text (for deep use / RAG).
        score:           Relevance score [0, 1] from the provider.
        published_date:  ISO 8601 date string or empty.
        metadata:        Provider-specific extra fields (e.g. raw JSON snippet).
    """
    url: str
    title: str = ""
    snippet: str = ""
    content: str = ""
    score: float = 0.0
    published_date: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class SearchResult:
    """Normalised result returned by any ``SearchProvider.search()``."""
    query: str
    results: list[SearchResultItem] = field(default_factory=list)
    provider: str = ""          # "exa", "llm", etc.


class SearchProviderError(Exception):
    """Raised when a search provider encounters a recoverable failure.

    Attributes:
        message:      Human-readable error description.
        retry_after:  Optional seconds to wait before retrying (e.g. HTTP 429).
    """

    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class SearchProvider(ABC):
    """Abstract base for all search backends.

    Implement ``search(query, max_results)`` and return a ``SearchResult``.
    Errors that may be retried later should raise ``SearchProviderError``.
    Unrecoverable errors (e.g. missing API key) may raise ``ValueError``.
    """

    @abstractmethod
    async def search(self, query: str, max_results: int = 10) -> SearchResult:
        ...
