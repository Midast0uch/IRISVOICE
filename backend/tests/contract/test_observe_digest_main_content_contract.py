"""browser_observe's text digest reads the page's MAIN content (live 2026-10-04).

Before: the digest was the first 600 characters of document.body.innerText -
on a Wikipedia article that is the header and menus. The blind node model
(mercury-2) never read the article text and asked the screenshot reader, which
misread facts ("The infobox height is 250.") 12-14 times a turn; the chat runs
took 166-263 s against 34-58 s when one reading happened to be right.

Now: the digest is the text of main / [role=main] / article / #mw-content-text
/ #content (else body), up to 1500 characters. Runs the real observe script in
a real headless Chromium.
"""

import asyncio

import pytest

pytest.importorskip("playwright.async_api")

from backend.vision.browser_session import _OBSERVE_JS  # noqa: E402

_PAGE = (
    "<html><body><header>" + "Jump to content Main menu Navigation Search Wikipedia " * 20
    + "</header><main><div id=mw-content-text><table>"
    "<tr><th>Elevation</th><td>5,895 m</td></tr>"
    "<tr><th>First ascent</th><td>6 October 1889</td></tr></table>"
    "<p>Kilimanjaro is a dormant volcano.</p></div></main></body></html>"
)


def test_the_digest_carries_the_article_not_the_menus():
    from playwright.async_api import async_playwright

    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(_PAGE)
                return await page.evaluate(_OBSERVE_JS, 120)
            finally:
                await browser.close()

    data = asyncio.run(run())
    assert "5,895 m" in data["digest"] and "6 October 1889" in data["digest"]
    assert "Jump to content" not in data["digest"]
