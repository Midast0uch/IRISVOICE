"""Inspect the actual anchor hrefs + result structure on Bing results."""
import asyncio

from playwright.async_api import async_playwright

from backend.vision.search_discovery import _results_url

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")


async def main():
    pw = await async_playwright().start()
    b = await pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    c = await b.new_context(user_agent=UA, viewport={"width": 1366, "height": 768}, locale="en-US")
    p = await c.new_page()
    await p.goto(_results_url("latest Zig release"), wait_until="networkidle", timeout=30000)
    await p.wait_for_timeout(2000)
    all_hrefs = await p.eval_on_selector_all("a", "els => els.map(e => e.getAttribute('href')).filter(Boolean)")
    print("total anchors:", len(all_hrefs))
    print("sample hrefs:")
    for h in all_hrefs[:25]:
        print("   ", h[:110])
    # b_algo is Bing's result container
    n = await p.eval_on_selector_all("li.b_algo", "els => els.length")
    print("li.b_algo count:", n)
    h2 = await p.eval_on_selector_all("li.b_algo h2 a", "els => els.map(e => e.href)")
    print("b_algo h2 links:", h2[:10])
    await b.close()
    await pw.stop()


asyncio.run(main())
