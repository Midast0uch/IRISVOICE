"""Test the APP's own BrowserSession + search_discovery against Bing, to see
whether the session-331 UA fix produces a real results page (vs a challenge)."""
import asyncio
import logging

logging.basicConfig(level=logging.INFO)


async def main():
    from backend.vision.browser_session import BrowserSession, SessionBounds
    from backend.vision.search_discovery import discover_urls_via_vision

    bounds = SessionBounds(max_actions=6, max_wall_ms=120_000, max_extractions=2)
    res = await discover_urls_via_vision(
        "latest Zig release", "probe-331", bounds=bounds,
    )
    print("RESULT urls=%r wall=%r unavailable=%r" % (res.urls, res.wall, res.unavailable))


asyncio.run(main())
