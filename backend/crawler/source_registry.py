"""
SourceRegistry — learned topic→URL knowledge base.

Maps natural-language topics to authoritative URLs discovered from past
searches. Stored in ``SemanticStore`` (category ``source_registry``) for
cross-session persistence. The registry answers two questions:

* **resolve(query)** — do we already know good URLs for this query?
* **learn(query, search_result, credibility_map)** — save what we learned.

Coverage scoring uses credibility × freshness decay × crawl frequency.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlparse

from backend.crawler.search_providers.base import SearchResult

logger = logging.getLogger(__name__)

_TOPIC_PROMPT = """\
Extract 3-5 key topic keywords from the following search query.
Return ONLY a valid JSON array of strings. No markdown, no explanation.
Example: ["ai hardware", "semiconductor", "nvidia", "market share"]
Query: {query}
"""


class SourceRegistry:
    """Learned topic→URL knowledge base.

    Stores topic-to-URL mappings in a persistent store (``SemanticStore``
    with category ``source_registry``, or a plain dict for testing).

    Args:
        store: An object duck-typed as either a ``SemanticStore`` (has
            ``get(category, key)`` and ``update(category, key, value, …)``)
            or a plain ``dict``.
        threshold: Coverage score above which ``resolve()`` returns
            ``hit=True`` (default 2.0).
        ttl_days: Days before a cached URL's freshness decays (default 7).
    """

    def __init__(
        self,
        store: Optional[Any] = None,
        threshold: float = 2.0,
        ttl_days: int = 7,
    ):
        self._store = store if store is not None else {}
        self._threshold = threshold
        self._ttl_days = ttl_days
        self._category = "source_registry"

    # ── Public API ──────────────────────────────────────────────────────

    async def resolve(self, query: str, quick: bool = False) -> dict:
        """Check whether known sources adequately cover *query*.

        Returns::

            {
                "hit": True,           # coverage >= threshold
                "sources": [...],      # list of RegisteredSource dicts
                "coverage_score": 2.65,
                "topics": ["nvidia", "market share", "gpu"],
            }

        Even on a MISS, ``sources`` is populated with whatever partial
        matches were found (usable as seed URLs for the fallback search).

        ``quick=True`` skips the LLM topic-extraction call and uses the query
        itself as the single topic — intended for the DER resolution gate,
        which runs on EVERY web-intent step. Burning an LLM quota slot just to
        check coverage of known sources made every step resolution slow AND
        consumed provider quota (observed: 429 storms + 40s gate evaluations).
        Full extraction remains on the learn path.
        """
        if quick:
            topics = [query.lower().strip()[:60]] if query and query.strip() else []
        else:
            topics = await self._extract_topics(query)
        sources = self._lookup_topics(topics)
        coverage = self._score_coverage(sources)
        return {
            "hit": coverage >= self._threshold,
            "sources": sources,
            "coverage_score": coverage,
            "topics": topics,
        }

    async def learn(
        self,
        query: str,
        search_result: SearchResult,
        credibility_map: Optional[dict[str, float]] = None,
    ):
        """Register URLs from a successful search result.

        Only saves URLs whose domain credibility >= 0.3. Updates existing
        entries with a weighted running average of credibility, increments
        ``crawl_count``, and refreshes ``last_crawled``.
        """
        topics = await self._extract_topics(query)
        cred_map = credibility_map or {}

        # DIAGNOSTIC: the learn path was silent, so a MISS on the next identical
        # query could not be attributed. The three candidate causes need
        # opposite fixes, and only the pair (topics stored here vs topics
        # extracted at resolve) can tell them apart:
        #   (a) nothing saved      -> saved=0 below
        #   (b) saved but unmatched-> saved>0 here, but resolve() logs different topics
        #   (c) saved and matched  -> resolve() logs coverage below threshold
        # Topics are the JOIN KEY between learn and resolve; log them both sides.
        _saved = 0
        _skipped: list[str] = []
        for item in search_result.results:
            domain = _extract_domain(item.url)
            if not domain:
                continue
            cred = cred_map.get(domain, 0.5)
            if cred >= 0.3:
                self._save_entry(item.url, domain, topics, cred)
                _saved += 1
            else:
                _skipped.append("%s(cred=%.2f)" % (domain, cred))
        logger.info(
            "[SourceRegistry] learn q=%r topics=%s saved=%d skipped_low_cred=%s",
            query[:60], topics[:6], _saved, _skipped[:5] or "none",
        )

    def penalize_url(self, url: str, topics: list[str], last_error: str = "crawl_failed"):
        """Reduce credibility for a URL whose crawl failed.

        Call from the orchestrator/tool when ``PageData.error`` is set.

        REQ-10 (T12): ``last_error="challenge"`` marks a bot-challenge
        interstitial (Cloudflare/Turnstile) — the source is penalized the same
        way (credibility halved) but the error reason distinguishes it so the
        outer loop can tell "page is dead" from "page is behind a CAPTCHA".
        """
        for topic in topics:
            key = _topic_key(topic)
            raw = self._get_store(key)
            if not raw:
                continue
            try:
                entries = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            for entry in entries:
                if entry.get("url") == url:
                    old = entry.get("credibility", 0.5)
                    entry["credibility"] = round(old * 0.5, 3)
                    entry["last_error"] = last_error
                    self._set_store(key, json.dumps(entries, indent=2))
                    break

    # ── Topic extraction ────────────────────────────────────────────────

    async def _extract_topics(self, query: str) -> list[str]:
        """LLM classifies the query into 3-5 topic keywords.

        Falls back to the query itself as a single topic on any error.
        """
        if not query or not query.strip():
            return []
        prompt = _TOPIC_PROMPT.format(query=query)
        try:
            raw = await asyncio.get_event_loop().run_in_executor(
                None, self._call_llm, prompt
            )
            raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
            match = re.search(r"\[.*\]", raw, re.DOTALL)
            if match:
                topics = json.loads(match.group())
                cleaned = [t.lower().strip() for t in topics if isinstance(t, str)]
                return cleaned[:5]
        except Exception as exc:
            logger.warning("[SourceRegistry] topic extraction failed: %s", exc)
        return [query.lower().strip()[:60]]

    def _call_llm(self, prompt: str) -> str:
        """Synchronous LLM call via agent kernel (runs in executor pool)."""
        from backend.agent import get_agent_kernel  # lazy import

        kernel = get_agent_kernel("source_registry")
        return kernel._respond_direct(text=prompt, context={})  # noqa: SLF001

    # ── Store helpers ───────────────────────────────────────────────────

    def _lookup_topics(self, topics: list[str]) -> list[dict]:
        """Collect all unique sources matching any of the given topics."""
        seen_urls: set[str] = set()
        sources: list[dict] = []
        for topic in topics:
            raw = self._get_store(_topic_key(topic))
            if not raw:
                continue
            try:
                entries = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            for entry in entries:
                url = entry.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    sources.append(entry)
        return sources

    def _score_coverage(self, sources: list[dict]) -> float:
        """Weighted sum over sources: credibility × (1 + log(crawl_count)).

        Applies freshness decay: URLs older than ``ttl_days`` have their
        credibility halved; URLs older than ``2 × ttl_days`` are nearly
        discarded.
        """
        now = datetime.now()
        total = 0.0
        for src in sources:
            cred = src.get("credibility", 0.5)
            age_days = _age_days(src.get("last_crawled", ""), now)

            if age_days > self._ttl_days * 2:
                cred *= 0.1
            elif age_days > self._ttl_days:
                cred *= 0.5

            count = src.get("crawl_count", 1)
            total += cred * (1.0 + math.log(count))
        return round(total, 2)

    def _save_entry(
        self, url: str, domain: str, topics: list[str], credibility: float
    ):
        """Upsert a URL entry under each topic key."""
        now = datetime.now().isoformat()
        for topic in topics:
            key = _topic_key(topic)
            raw = self._get_store(key) or "[]"
            try:
                entries = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                entries = []

            updated = False
            for entry in entries:
                if entry.get("url") == url:
                    old_cred = entry.get("credibility", 0.5)
                    entry["credibility"] = round(old_cred * 0.7 + credibility * 0.3, 3)
                    entry["last_crawled"] = now
                    entry["crawl_count"] = entry.get("crawl_count", 0) + 1
                    updated = True
                    break

            if not updated:
                entries.append({
                    "url": url,
                    "domain": domain,
                    "topics": topics,
                    "credibility": round(credibility, 3),
                    "last_crawled": now,
                    "crawl_count": 1,
                    "last_error": "",
                })

            self._set_store(key, json.dumps(entries, indent=2))

    def _get_store(self, key: str) -> Optional[str]:
        """Read from SemanticStore (has ``.db``) or plain dict."""
        if isinstance(self._store, dict):
            return self._store.get(key)
        entry = self._store.get(self._category, key)
        return entry.value if entry else None

    def _set_store(self, key: str, value: str, confidence: float = 1.0):
        """Write to SemanticStore (has ``.db``) or plain dict."""
        if isinstance(self._store, dict):
            self._store[key] = value
        else:
            self._store.update(
                self._category, key, value, confidence=confidence, source="crawl"
            )


# ── Module-level singleton ──────────────────────────────────────────────

_source_registry: Optional[SourceRegistry] = None


def init_source_registry(
    store: Optional[Any] = None,
    threshold: float = 2.0,
    ttl_days: int = 7,
) -> SourceRegistry:
    """Initialise the global SourceRegistry singleton.

    Called once from the application bootstrap (e.g. tool_bridge init)
    with a real SemanticStore. If never called, ``get_source_registry()``
    creates a transient in-memory registry (useful for testing / early
    sessions before the memory layer is wired).
    """
    global _source_registry
    _source_registry = SourceRegistry(store=store, threshold=threshold, ttl_days=ttl_days)
    return _source_registry


def get_source_registry() -> SourceRegistry:
    """Return the global SourceRegistry singleton.

    Creates a transient in-memory registry on first call if
    :func:`init_source_registry` was never called.
    """
    global _source_registry
    if _source_registry is None:
        _source_registry = SourceRegistry()
        logger.info("[SourceRegistry] created transient in-memory instance")
    return _source_registry


# ── Module-level helpers ────────────────────────────────────────────────


def _topic_key(topic: str) -> str:
    """Normalise a topic into a store key.

    >>> _topic_key("AI Hardware")
    "topic:ai_hardware"
    """
    return f"topic:{topic.lower().replace(' ', '_')}"


def _extract_domain(url: str) -> str:
    """Return the netloc of a URL (or empty string)."""
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def _age_days(last_crawled: str, now: datetime) -> int:
    """Compute approximate age of an entry in days."""
    if not last_crawled:
        return 999
    try:
        return (now - datetime.fromisoformat(last_crawled)).days
    except (ValueError, TypeError):
        return 999
