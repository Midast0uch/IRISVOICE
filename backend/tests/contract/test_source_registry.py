"""
Contract tests for SourceRegistry.

Tests verify:
1. resolve() HIT and MISS decision
2. Coverage scoring with freshness decay
3. learn() adds and updates entries
4. penalize_url() reduces credibility
5. Topic extraction (with mocked LLM)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from backend.crawler.source_registry import SourceRegistry, _topic_key, _age_days
from backend.crawler.search_providers.base import SearchResult, SearchResultItem


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def store():
    """In-memory dict used as the store backend."""
    return {}


@pytest.fixture
def registry(store):
    """SourceRegistry with low threshold for testing."""
    return SourceRegistry(store=store, threshold=1.5, ttl_days=7)


def _make_result(urls: list[str], domain: str = "example.com") -> SearchResult:
    """Build a SearchResult with one item per URL."""
    items = [
        SearchResultItem(
            url=u,
            title=f"Page {i}",
            snippet="snippet",
            content="content",
            score=0.9 - i * 0.1,
        )
        for i, u in enumerate(urls)
    ]
    return SearchResult(query="test query", results=items, provider="exa")


# ── Resolve: HIT / MISS ────────────────────────────────────────────────


class TestResolveDecision:
    """REQ-11, REQ-12: resolve() returns HIT when coverage >= threshold."""

    async def _mock_topics(self, q, topics):
        return topics

    async def test_miss_on_empty_store(self, registry):
        registry._extract_topics = lambda q: self._mock_topics(q, ["unknown_topic"])
        result = await registry.resolve("unknown topic")
        assert result["hit"] is False
        assert result["sources"] == []
        assert result["coverage_score"] == 0.0

    async def test_hit_when_coverage_exceeds_threshold(self, registry, store):
        # Pre-populate with high-credibility sources
        key = _topic_key("test_topic")
        store[key] = json.dumps([
            {
                "url": "https://example.com/article",
                "domain": "example.com",
                "topics": ["test topic"],
                "credibility": 0.95,
                "last_crawled": datetime.now().isoformat(),
                "crawl_count": 5,
            },
            {
                "url": "https://other.com/page",
                "domain": "other.com",
                "topics": ["test topic"],
                "credibility": 0.85,
                "last_crawled": datetime.now().isoformat(),
                "crawl_count": 3,
            },
        ])
        registry._extract_topics = lambda q: self._mock_topics(q, ["test_topic"])
        result = await registry.resolve("test_topic query")
        assert result["hit"] is True
        assert result["coverage_score"] >= 1.5
        assert len(result["sources"]) == 2

    async def test_miss_when_below_threshold(self, registry, store):
        key = _topic_key("low_cred")
        store[key] = json.dumps([
            {
                "url": "https://example.com/article",
                "domain": "example.com",
                "topics": ["low cred"],
                "credibility": 0.3,
                "last_crawled": datetime.now().isoformat(),
                "crawl_count": 1,
            },
        ])
        registry._extract_topics = lambda q: self._mock_topics(q, ["low_cred"])
        result = await registry.resolve("low credibility topic")
        assert result["hit"] is False
        assert result["coverage_score"] < 1.5

    async def test_partial_hit_returns_seed_sources(self, registry, store):
        """Even on MISS, known sources are returned as seeds."""
        key = _topic_key("partial")
        store[key] = json.dumps([
            {
                "url": "https://example.com/article",
                "domain": "example.com",
                "topics": ["partial"],
                "credibility": 0.8,
                "last_crawled": datetime.now().isoformat(),
                "crawl_count": 2,
            },
        ])
        registry._extract_topics = lambda q: self._mock_topics(q, ["partial", "unknown"])
        result = await registry.resolve("partial coverage")
        assert len(result["sources"]) >= 1


# ── Learn ───────────────────────────────────────────────────────────────


class TestLearn:
    """REQ-13: learn() saves and updates entries."""

    async def test_learn_adds_new_entries(self, registry, store):
        async def _t(q):
            return ["test_learning"]
        registry._extract_topics = _t
        sr = _make_result(["https://example.com/a", "https://example.com/b"])
        await registry.learn("test query", sr, {"example.com": 0.9})
        key = _topic_key("test_learning")
        assert key in store
        entries = json.loads(store[key])
        assert len(entries) == 2

    async def test_learn_updates_existing_entry(self, registry, store):
        async def _t(q):
            return ["existing"]
        key = _topic_key("existing")
        store[key] = json.dumps([
            {
                "url": "https://example.com/a",
                "domain": "example.com",
                "topics": ["existing"],
                "credibility": 0.5,
                "last_crawled": "2020-01-01T00:00:00",
                "crawl_count": 1,
                "last_error": "",
            },
        ])
        registry._extract_topics = _t
        sr = _make_result(["https://example.com/a"])
        await registry.learn("existing query", sr, {"example.com": 0.9})
        entries = json.loads(store[key])
        entry = next(e for e in entries if e["url"] == "https://example.com/a")
        # Weighted average: 0.5 * 0.7 + 0.9 * 0.3 = 0.62
        assert entry["credibility"] == pytest.approx(0.62, abs=0.01)
        assert entry["crawl_count"] == 2

    async def test_learn_skips_low_credibility(self, registry, store):
        async def _t(q):
            return ["spam"]
        registry._extract_topics = _t
        sr = _make_result(["https://spam.com/page"])
        await registry.learn("spam query", sr, {"spam.com": 0.1})
        # Should not save because credibility < 0.3
        key = _topic_key("spam")
        if key in store:
            entries = json.loads(store[key])
            assert all(e.get("credibility", 1) >= 0.3 for e in entries)


# ── Coverage scoring ────────────────────────────────────────────────────


class TestCoverageScoring:
    """REQ-11, REQ-14: coverage score calculation with freshness."""

    def test_fresh_source_full_score(self, registry):
        sources = [
            {
                "credibility": 0.9,
                "crawl_count": 3,
                "last_crawled": datetime.now().isoformat(),
            },
        ]
        score = registry._score_coverage(sources)
        # 0.9 * (1 + ln(3)) ≈ 0.9 * 2.099 = 1.89
        expected = 0.9 * (1 + __import__("math").log(3))
        assert score == pytest.approx(expected, abs=0.05)

    def test_decayed_score(self, registry):
        now = datetime.now()
        old = (now - timedelta(days=8)).isoformat()  # past TTL (7 days)
        sources = [
            {
                "credibility": 0.9,
                "crawl_count": 3,
                "last_crawled": old,
            },
        ]
        score = registry._score_coverage(sources)
        # credibility halved: 0.45 * (1 + ln(3)) ≈ 0.94
        expected = 0.45 * (1 + __import__("math").log(3))
        assert score == pytest.approx(expected, abs=0.05)

    def test_very_stale_score(self, registry):
        now = datetime.now()
        old = (now - timedelta(days=15)).isoformat()  # past 2 * TTL
        sources = [
            {
                "credibility": 0.9,
                "crawl_count": 3,
                "last_crawled": old,
            },
        ]
        score = registry._score_coverage(sources)
        # credibility * 0.1: 0.09 * (1 + ln(3)) ≈ 0.19
        expected = 0.09 * (1 + __import__("math").log(3))
        assert score == pytest.approx(expected, abs=0.05)


# ── Penalize ────────────────────────────────────────────────────────────


class TestPenalize:
    """REQ-13: penalize_url reduces credibility on crawl failure."""

    async def test_penalize_halves_credibility(self, registry, store):
        key = _topic_key("fail")
        store[key] = json.dumps([
            {
                "url": "https://broken.com/page",
                "domain": "broken.com",
                "topics": ["fail"],
                "credibility": 0.8,
                "last_crawled": datetime.now().isoformat(),
                "crawl_count": 2,
                "last_error": "",
            },
        ])
        registry.penalize_url("https://broken.com/page", ["fail"])
        entries = json.loads(store[key])
        entry = next(e for e in entries if e["url"] == "https://broken.com/page")
        assert entry["credibility"] == 0.4  # 0.8 * 0.5
        assert entry["last_error"] == "crawl_failed"


# ── Topic extraction ────────────────────────────────────────────────────


class TestTopicNormalization:
    """REQ-11: _topic_key normalizes topics correctly."""

    def test_lowercase_and_underscores(self):
        assert _topic_key("AI Hardware") == "topic:ai_hardware"
        assert _topic_key("market share") == "topic:market_share"
        assert _topic_key("  spaces  ") == "topic:__spaces__"  # preserves edge case


class TestAgeDays:
    """REQ-14: _age_days computes correct age."""

    def test_age_computation(self):
        now = datetime(2026, 7, 17)
        assert _age_days("2026-07-10T00:00:00", now) == 7
        assert _age_days("2026-07-17T00:00:00", now) == 0
        assert _age_days("", now) == 999
        assert _age_days("invalid", now) == 999
