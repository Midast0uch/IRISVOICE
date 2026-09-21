import asyncio
from playwright.async_api import async_playwright


async def main():
    pw = await async_playwright().start()
    b = await pw.chromium.launch(headless=True)
    ctx = await b.new_context()
    p = await ctx.new_page()
    await p.goto("https://www.bing.com/", wait_until="domcontentloaded", timeout=20000)
    html = await p.content()
    txt = (await p.inner_text("body"))[:600]
    ua = await p.evaluate("navigator.userAgent")
    print("UA:", ua)
    print("LEN html:", len(html))
    print("--- first 400 visible text ---")
    print(txt[:400])
    low = html.lower()
    print("--- login markers in first 5000 chars ---")
    for m in ("sign in", "log in", "password"):
        print(repr(m), "present:", m in low[:5000])
    box = await p.query_selector("textarea[name='q'], input[name='q']")
    print("search box found:", bool(box))
    await b.close()
    await pw.stop()


asyncio.run(main())
