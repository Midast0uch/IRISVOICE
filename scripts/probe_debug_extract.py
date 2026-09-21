"""Debug: why does extraction still return 0?"""
import asyncio
import re

from playwright.async_api import async_playwright

from backend.vision.search_discovery import _HREF_RE, _results_url, _unwrap_engine_redirect

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"


async def main():
    pw = await async_playwright().start()
    b = await pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    c = await b.new_context(user_agent=UA, viewport={"width": 1366, "height": 768}, locale="en-US")
    p = await c.new_page()
    await p.goto(_results_url("latest Zig release"), wait_until="domcontentloaded", timeout=25000)
    await p.wait_for_timeout(2500)
    html = await p.content()
    matches = list(_HREF_RE.finditer(html))
    print("HREF_RE matches:", len(matches))
    unwrapped = []
    for m in matches[:200]:
        u = _unwrap_engine_redirect(m.group(1))
        if "bing.com" not in u and "microsoft" not in u:
            unwrapped.append(u)
    print("unwrapped non-bing:", unwrapped[:8])
    await b.close()
    await pw.stop()


asyncio.run(main())
