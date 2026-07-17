"""
CredibilityScorer (REQ-5, REQ-6).

Classifies each source into a type from the fixed table and computes a final
credibility score in [0,1] as:
    base_weight * freshness_factor * corroboration_factor * structural_factor

No network calls — type is derived from URL TLD/class heuristics.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from .crawler_engine import PageData
from .orchestrator import CredibilityMap, Passage

logger = logging.getLogger(__name__)

# Source-type table (REQ-6). Order matters: first match wins for ambiguous hosts.
_SOURCE_TYPES: list[tuple[str, float, re.Pattern]] = [
    ("primary_official", 0.9, re.compile(r"\.(gov|edu|mil)(\.[a-z]{2})?$|/rfc\d+|docs\.[a-z0-9-]+\.(com|io|dev)$", re.I)),
    ("academic", 0.85, re.compile(r"\.(edu)(\.[a-z]{2})?/|arxiv\.org|scholar\.|/paper/|doi\.org", re.I)),
    ("news", 0.7, re.compile(r"(reuters|apnews|bbc\.|nytimes|theguardian|bloomberg|wsj|cnbc|npr\.org|aljazeera)", re.I)),
    ("reference", 0.6, re.compile(r"(wikipedia\.org|wikimedia|wiki|britannica\.com)", re.I)),
    ("blog", 0.4, re.compile(r"(medium\.com|wordpress\.com|blog|substack\.com|dev\.to)", re.I)),
    ("forum", 0.3, re.compile(r"(reddit\.com|news\.ycombinator\.com|stackoverflow\.com|stackexchange\.com|quora\.com|discord\.com)", re.I)),
]
_UNKNOWN_WEIGHT = 0.5


def classify_source(url: str) -> str:
    """Return the source type for a URL (REQ-6 AC2)."""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return "unknown"
    for name, _w, pat in _SOURCE_TYPES:
        if pat.search(host):
            return name
    return "unknown"


def _base_weight(url: str) -> float:
    t = classify_source(url)
    for name, w, _p in _SOURCE_TYPES:
        if name == t:
            return w
    return _UNKNOWN_WEIGHT


def _freshness_factor(page: PageData) -> float:
    """Freshness from publish/update date; default 0.5 when unknown (REQ-5 AC5)."""
    meta = page.metadata or {}
    date_str = meta.get("published_time") or meta.get("modified_time") or meta.get("date")
    if not date_str:
        return 0.5
    try:
        from datetime import datetime, timezone
        parsed = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - parsed).days
        if age_days < 0:
            return 0.9
        if age_days < 180:
            return 0.9
        if age_days < 730:
            return 0.7
        return 0.5
    except Exception:
        return 0.5


def _structural_factor(page: PageData) -> float:
    """Structural quality: has content, citations, not paywalled/blocked."""
    text = page.markdown or page.html or ""
    if not text.strip():
        return 0.1
    score = 0.6
    if len(text) > 800:
        score += 0.2
    if re.search(r"https?://", text):
        score += 0.1  # has outbound citations
    meta = page.metadata or {}
    if meta.get("paywall") or "subscribe to read" in text.lower()[:500]:
        score -= 0.3
    return max(0.1, min(1.0, score))


def score_credibility(pages: list[PageData], passages: list[Passage]) -> CredibilityMap:
    """Compute per-source credibility (REQ-5 AC1-AC5)."""
    per_source: dict[str, float] = {}
    for page in pages:
        if page.error:
            continue
        base = _base_weight(page.url)
        fresh = _freshness_factor(page)
        struct = _structural_factor(page)
        # corroboration applied later (needs cross-source claim agreement)
        cred = base * fresh * struct
        per_source[page.url] = round(max(0.0, min(1.0, cred)), 3)

    # Corroboration boost: claims appearing in >=2 independent sources (REQ-5 AC4)
    _apply_corroboration(passages, per_source)

    return CredibilityMap(per_source=per_source, unsourced_claims=[], top_score=0.0)


def _apply_corroboration(passages: list[Passage], per_source: dict[str, float]) -> None:
    """Boost sources that agree on the same normalized claim snippet."""
    from collections import defaultdict
    norm: dict[str, set[str]] = defaultdict(set)
    for p in passages:
        key = re.sub(r"\W+", " ", p.text.lower())[:80]
        norm[key].add(p.url)
    for urls in norm.values():
        if len(urls) >= 2:
            for u in urls:
                if u in per_source:
                    per_source[u] = round(min(1.0, per_source[u] + 0.1), 3)
