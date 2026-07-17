"""
Search provider package — pluggable search backends for URL discovery.

Usage::

    from backend.crawler.search_providers import get_search_provider

    provider = get_search_provider()
    result = await provider.search("AI hardware companies", max_results=10)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from backend.crawler.search_providers.base import (
    SearchProvider,
    SearchResult,
    SearchResultItem,
    SearchProviderError,
)
from backend.crawler.search_providers.llm import LLMSearchProvider

logger = logging.getLogger(__name__)

_provider_instance: Optional[SearchProvider] = None

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # C:\dev\IRISVOICE
_CONFIG_FILE = _PROJECT_ROOT / "data" / "iris_config.json"


def _read_search_config() -> dict:
    """Read the ``search`` section of ``iris_config.json``.

    Returns an empty dict on any read/parse error (safe fallback).
    """
    try:
        with open(_CONFIG_FILE) as f:
            cfg = json.load(f)
        return cfg.get("search", {})
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logger.warning("[SearchProvider] cannot read config: %s — using defaults", exc)
        return {}


def get_search_provider() -> SearchProvider:
    """Return the configured ``SearchProvider`` (cached).

    Reads ``iris_config.json`` → ``search.provider``:

    * ``"llm"`` (default) → :class:`LLMSearchProvider`  — LLM-generated URLs.
    * ``"exa"`` → :class:`ExaSearchProvider` — Exa neural search (requires
      ``EXA_API_KEY`` env var).

    Falls back to ``LLMSearchProvider`` when:
    * the provider value is unknown or missing,
    * ``"exa"`` is configured but ``EXA_API_KEY`` is not set,
    * or any other error occurs during provider construction.

    The instance is cached so the HTTP client is created once. Call
    :func:`clear_search_provider_cache` after config changes to
    pick up the new settings on the next call.
    """
    global _provider_instance

    if _provider_instance is not None:
        return _provider_instance

    config = _read_search_config()
    provider_name = config.get("provider", "llm")

    if provider_name == "exa":
        try:
            from backend.crawler.search_providers.exa import ExaSearchProvider

            _provider_instance = ExaSearchProvider()
            logger.info("[SearchProvider] using Exa neural search")
        except ValueError as exc:
            logger.warning(
                "[SearchProvider] %s — falling back to LLM provider", exc
            )
            _provider_instance = LLMSearchProvider()
    else:
        if provider_name != "llm":
            logger.warning(
                "[SearchProvider] unknown provider %r — using LLM", provider_name
            )
        _provider_instance = LLMSearchProvider()
        logger.info("[SearchProvider] using LLM-generated URLs")

    return _provider_instance


def clear_search_provider_cache() -> None:
    """Clear the cached provider instance.

    Call after updating ``iris_config.json`` or ``.env`` so the next
    :func:`get_search_provider` call creates a fresh provider with the
    new settings.
    """
    global _provider_instance
    _provider_instance = None
    logger.debug("[SearchProvider] cache cleared")


# Re-export for convenience
__all__ = [
    "SearchProvider",
    "SearchResult",
    "SearchResultItem",
    "SearchProviderError",
    "get_search_provider",
    "clear_search_provider_cache",
]
