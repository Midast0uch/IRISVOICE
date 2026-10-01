"""Same-site link extraction and ranking (specs/research-memory-chain-browser W3, D6).

One helper for both explorers: the crawl's same-site hop (orchestrator) and the
agent's ``browser_explore``. It reads links, keeps those on the SAME SITE as the page
they came from, and ranks them by relevance to the goal (goal tokens found in the
anchor text and the URL path). Nothing here fetches; the callers bound pages, depth
and time.

The two link regexes (markdown ``[text](url)`` and ``<a href>``) are the ones the
``crawler_query`` outlink section uses; that section lists absolute links only, this
module also resolves relative ones.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Tuple
from urllib.parse import urldefrag, urljoin, urlparse

_MD_LINK = re.compile(r"\[([^\]]{0,300})\]\(([^)\s]+)\)")
_HREF = re.compile(r"<a\s[^>]*?href=[\"']([^\"'<>\s]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_SKIP_EXT = re.compile(
    r"\.(pdf|jpe?g|png|gif|svg|webp|ico|css|js|zip|7z|rar|gz|tar|exe|msi|dmg|mp[34]|avi|mov|woff2?)$", re.I,
)
# Pages that act when opened (sign-out, cart, delete links) or hold no content.
_SKIP_PATH = re.compile(
    r"log(in|out)|sign(in|out|up)|register|cart|checkout|delete|remove|unsubscribe|subscribe|account|admin",
    re.I,
)
_STOP = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "what", "how", "are", "was", "who",
    "about", "page", "site", "find", "all", "any", "get", "has", "have", "can", "you", "your",
})
MAX_LINKS = 300


def _site(url: str) -> str:
    host = (urlparse(url).netloc or "").lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def same_site(a: str, b: str) -> bool:
    """True when both URLs are on the same host (``www.`` ignored)."""
    return bool(_site(a)) and _site(a) == _site(b)


def _norm(url: str) -> str:
    return urldefrag(url)[0].rstrip("/")


def extract_links(markdown: str, html: str, base_url: str) -> List[Tuple[str, str]]:
    """``[(absolute_url, anchor_text)]`` in document order, deduplicated, bounded.

    Relative links are resolved against ``base_url``; non-http(s) links are dropped.
    """
    found: List[Tuple[str, str]] = []
    seen: set = set()

    def add(href: str, text: str) -> None:
        if len(found) >= MAX_LINKS:
            return
        url = urljoin(base_url, (href or "").strip())
        if not url.lower().startswith(("http://", "https://")):
            return
        key = _norm(url)
        if key in seen:
            return
        seen.add(key)
        found.append((url, re.sub(r"\s+", " ", _TAG.sub(" ", text or "")).strip()[:120]))

    for m in _MD_LINK.finditer(markdown or ""):
        add(m.group(2), m.group(1))
    for m in _HREF.finditer(html or ""):
        add(m.group(1), m.group(2))
    return found


def goal_tokens(goal: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", (goal or "").lower()) if len(t) >= 3 and t not in _STOP}


def rank_same_site(
    links: Iterable[Tuple[str, str]], base_url: str, goal: str, *,
    exclude: Iterable[str] = (), limit: int = 4,
) -> List[str]:
    """The best ``limit`` same-site URLs for ``goal``, most relevant first.

    Score = goal tokens found in the anchor text plus goal tokens found in the URL
    path. A link with score 0 is not relevant and is never returned; the page itself,
    excluded URLs, files, and acting pages (log out, cart, delete) are skipped.
    """
    from backend.crawler.cite import _tok  # lazy: cite imports the orchestrator

    want = goal_tokens(goal)
    skip = {_norm(u) for u in exclude} | {_norm(base_url)}
    scored: List[Tuple[int, int, str]] = []
    for url, text in links:
        if not same_site(url, base_url) or _norm(url) in skip:
            continue
        path = urlparse(url).path
        if _SKIP_EXT.search(path) or _SKIP_PATH.search(path):
            continue
        score = len(want & _tok(text)) + len(want & _tok(path))
        if score > 0:
            scored.append((-score, len(path), url))
    scored.sort()
    out: List[str] = []
    for _s, _n, url in scored:
        if _norm(url) not in {_norm(u) for u in out}:
            out.append(url)
        if len(out) >= limit:
            break
    return out
