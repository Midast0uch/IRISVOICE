"""Inspect what Bing returns for a direct search URL."""
import asyncio
from playwright.async_api import async_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")


async def main():
    pw = await async_playwright().start()
    b = await pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    c = await b.new_context(user_agent=UA, viewport={"width": 1366, "height": 768}, locale="en-US")
    p = await c.new_page()
    await p.goto("https://www.bing.com/search?q=latest+Zig+release", wait_until="domcontentloaded", timeout=25000)
    await asyncio.sleep(3)
    txt = await p.inner_text("body")
    html = await p.content()
    print("title:", await p.title())
    print("text len:", len(txt))
    print("text[:500]:", repr(txt[:500]))
    for marker in ["captcha", "challenge", "unusual traffic", "verify", "blocked", "sign in"]:
        print(f"  {marker!r} in html:", marker in html.lower())
    await b.close()
    await pw.stop()


asyncio.run(main())
