"""Why does extraction return 0 URLs on the real Bing results page?"""
import asyncio
import re

from playwright.async_api import async_playwright

from backend.vision.search_discovery import _extract_urls_from_html, _results_url

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")


async def main():
    pw = await async_playwright().start()
    b = await pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    c = await b.new_context(user_agent=UA, viewport={"width": 1366, "height": 768}, locale="en-US")
    p = await c.new_page()
    await p.goto(_results_url("latest Zig release"), wait_until="domcontentloaded", timeout=25000)
    await p.wait_for_timeout(2500)
    html = await p.content()
    urls = _extract_urls_from_html(html, 30)
    print("html len:", len(html))
    print("extracted via _extract_urls_from_html:", urls[:8])
    hrefs = re.findall(r"""href=["']([^"']+)["']""", html)
    ext = [h for h in hrefs if h.startswith("http") and "bing.com" not in h and "microsoft" not in h and "msn.com" not in h]
    print("raw external hrefs sample:", ext[:10])
    # Try the visible anchors via DOM
    anchors = await p.eval_on_selector_all(
        "a[href^='http']",
        "els => els.map(e => e.href).filter(h => !h.includes('bing.com') && !h.includes('microsoft'))",
    )
    print("DOM external anchors:", anchors[:10])
    await b.close()
    await pw.stop()


asyncio.run(main())
