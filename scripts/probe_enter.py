"""Bounded test: does type + Enter submit Bing and produce result links?"""
import asyncio
from playwright.async_api import async_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")


async def main():
    pw = await async_playwright().start()
    b = await pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    c = await b.new_context(user_agent=UA, viewport={"width": 1366, "height": 768}, locale="en-US")
    p = await c.new_page()
    await p.goto("https://www.bing.com/", wait_until="domcontentloaded", timeout=25000)
    box = await p.query_selector("textarea[name='q'], input[name='q']")
    print("box:", bool(box))
    await box.fill("latest Zig release")
    await box.press("Enter")
    try:
        await p.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception as e:
        print("wait err:", e)
    await asyncio.sleep(2)
    html = await p.content()
    hrefs = [a for a in await p.eval_on_selector_all("a[href]", "els => els.map(e => e.href)") if "ziglang" in a]
    print("url:", p.url)
    print("html len:", len(html))
    print("ziglang links:", hrefs[:5])
    await b.close()
    await pw.stop()


asyncio.run(main())
