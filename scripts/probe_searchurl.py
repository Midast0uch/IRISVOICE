"""Test: navigate directly to Bing's search-results URL (markup-independent)."""
import asyncio
from playwright.async_api import async_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")


async def main():
    pw = await async_playwright().start()
    b = await pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    c = await b.new_context(user_agent=UA, viewport={"width": 1366, "height": 768}, locale="en-US")
    p = await c.new_page()
    url = "https://www.bing.com/search?q=latest%20Zig%20release"
    await p.goto(url, wait_until="domcontentloaded", timeout=25000)
    await asyncio.sleep(2)
    links = await p.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
    zig = [l for l in links if "ziglang" in l]
    ext = [l for l in links if l.startswith("http") and "bing.com" not in l and "microsoft" not in l and "msn.com" not in l]
    print("final url:", p.url)
    print("ziglang:", zig[:5])
    print("external sample:", ext[:6])
    await b.close()
    await pw.stop()


asyncio.run(main())
