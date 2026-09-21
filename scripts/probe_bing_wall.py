import asyncio
from playwright.async_api import async_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")


async def main():
    pw = await async_playwright().start()
    b = await pw.chromium.launch(
        headless=True, args=["--disable-blink-features=AutomationControlled"]
    )
    c = await b.new_context(user_agent=UA, viewport={"width": 1366, "height": 768},
                            locale="en-US")
    p = await c.new_page()
    await p.goto("https://www.bing.com/", wait_until="domcontentloaded", timeout=25000)
    box = await p.query_selector("textarea[name='q'], input[name='q']")
    txt = await p.inner_text("body")
    head = txt[:2000].lower()
    print("search_box:", bool(box))
    print("'sign in' in first 2000:", "sign in" in head)
    print("'log in' in first 2000:", "log in" in head)
    print("first 260 text:", repr(txt[:260]))
    await b.close()
    await pw.stop()


asyncio.run(main())
