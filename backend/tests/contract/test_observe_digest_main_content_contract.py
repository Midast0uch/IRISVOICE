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


# A shop's category page (live 2026-10-12): many <article> cards, a 50-link
# sidebar, no <main>. The digest was the FIRST card ("Sharp Objects £47.82")
# and the sidebar took 50 of the 60 element slots - the agent saw 4 of 20
# products and picked the wrong "cheapest" one.
_LIST_PAGE = (
    "<html><body><header>Books to Scrape We love being scraped!</header>"
    "<aside><ul>" + "".join(f"<li><a href='/c{i}'>Category {i}</a></li>" for i in range(50))
    + "</ul></aside><section>"
    + "".join(f"<article><h3><a href='/b{i}'>Book {i}</a></h3><p>£{40 - i}.50</p>"
              f"<button>Add to basket</button></article>" for i in range(20))
    + "</section></body></html>"
)


def test_a_list_page_digest_and_elements_carry_every_item_not_the_chrome():
    from playwright.async_api import async_playwright

    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(_LIST_PAGE)
                return await page.evaluate(_OBSERVE_JS, 60)
            finally:
                await browser.close()

    data = asyncio.run(run())
    assert "Book 0" in data["digest"] and "£21.50" in data["digest"], data["digest"][:300]
    assert "Category 7" not in data["digest"], "the sidebar is read as the page"
    names = [m["name"] for m in data["marks"]]
    assert "Book 19" in names, "the products were crowded out of the element list"
    assert names.index("Book 0") < names.index("Category 0") if "Category 0" in names else True


# ...and the navigation must survive a full page of items (live 2026-10-12: a
# home page whose 20 products filled every slot hid the category links; the
# agent guessed URLs and hit 404s).
_FULL_HOME = (
    "<html><body><aside><ul>" + "".join(f"<li><a href='/c{i}'>Category {i}</a></li>" for i in range(50))
    + "</ul></aside><section>"
    + "".join(f"<article><a href='/b{i}'><img alt='cover {i}'></a><h3><a href='/b{i}'>Book {i}</a></h3>"
              f"<button>Add to basket</button></article>" for i in range(40))
    + "</section></body></html>"
)


def test_navigation_links_keep_a_share_of_the_element_list():
    from playwright.async_api import async_playwright

    async def run():
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                page = await browser.new_page()
                await page.set_content(_FULL_HOME)
                return await page.evaluate(_OBSERVE_JS, 80)
            finally:
                await browser.close()

    names = [m["name"] for m in asyncio.run(run())["marks"]]
    assert sum(n.startswith("Category") for n in names) >= 20, "navigation crowded out"
    assert sum(n.startswith("Book") or n.startswith("cover") for n in names) >= 20
