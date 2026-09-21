import asyncio
from playwright.async_api import async_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")


async def probe(stealth: bool):
    pw = await async_playwright().start()
    b = await pw.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"] if stealth else [],
    )
    kw = {}
    if stealth:
        kw = dict(
            user_agent=UA,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )
    ctx = await b.new_context(**kw)
    p = await ctx.new_page()
    await p.goto("https://www.bing.com/", wait_until="domcontentloaded", timeout=20000)
    box = await p.query_selector("textarea[name='q'], input[name='q']")
    txt = (await p.inner_text("body"))[:200]
    ua = await p.evaluate("navigator.userAgent")
    print(f"stealth={stealth} search_box={bool(box)} ua={ua[:60]}")
    print(f"   text: {txt!r}")
    await b.close()
    await pw.stop()


async def main():
    await probe(False)
    await probe(True)


asyncio.run(main())
