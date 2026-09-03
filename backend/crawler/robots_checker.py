"""
Robots.txt Checker — polite crawling gate.

Quality-check gates applied:
  - urllib.robotparser is stdlib; no extra dependency.
  - Robots.txt is cached per domain for the session lifetime (dict with TTL).
  - Cache entries expire after 1 hour to avoid stale allow/block decisions.
  - Fetching robots.txt has a 5s timeout to avoid blocking the crawler.
  - Disallowed URLs are logged at WARNING level and returned as blocked.
  - No shared mutable state across event loop iterations (lock-free dict access
    is safe here because robots.txt checks run sequentially inside crawler tasks).
"""
from __future__ import annotations

import logging
import time
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)

_USER_AGENT = "IRIS-Agent/1.0"
_CACHE_TTL_SECONDS = 3600  # 1 hour
_FETCH_TIMEOUT = 5.0


class RobotsChecker:
    """Per-domain robots.txt cache with TTL."""

    def __init__(self) -> None:
        # domain → (RobotFileParser, fetched_at)
        self._cache: dict[str, tuple[Optional[RobotFileParser], float]] = {}

    async def is_allowed(self, url: str, user_agent: str = _USER_AGENT) -> bool:
        """
        Return True if user_agent is allowed to fetch url per robots.txt.
        Returns True (allowed) on any fetch failure so crawling is not silently blocked.
        """
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        rp = await self._get_parser(domain)
        if rp is None:
            return True  # Can't fetch robots.txt — assume allowed
        allowed = rp.can_fetch(user_agent, url)
        if not allowed:
            logger.warning("[RobotsChecker] %s blocked by robots.txt for %s", url, domain)
        return allowed

    async def _get_parser(self, domain: str) -> Optional[RobotFileParser]:
        now = time.monotonic()
        cached = self._cache.get(domain)
        if cached and (now - cached[1]) < _CACHE_TTL_SECONDS:
            return cached[0]

        robots_url = f"{domain}/robots.txt"
        try:
            async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT) as client:
                resp = await client.get(robots_url, follow_redirects=True)
                if resp.status_code == 200:
                    rp = RobotFileParser()
                    rp.parse(resp.text.splitlines())
                    self._cache[domain] = (rp, now)
                    return rp
                else:
                    # No robots.txt or error — cache as None (allowed)
                    self._cache[domain] = (None, now)
                    return None
        except Exception as exc:
            logger.debug("[RobotsChecker] could not fetch %s: %s", robots_url, exc)
            self._cache[domain] = (None, now)
            return None

    def clear_cache(self) -> None:
        self._cache.clear()


_checker: Optional[RobotsChecker] = None


def get_robots_checker() -> RobotsChecker:
    global _checker
    if _checker is None:
        _checker = RobotsChecker()
    return _checker
