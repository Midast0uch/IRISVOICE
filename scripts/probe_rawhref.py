"""See the raw HREF_RE matches from real Bing HTML."""
import asyncio

from playwright.async_api import async_playwright

from backend.vision.search_discovery import _HREF_RE, _results_url

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"


async def main():
    pw = await async_playwright().start()
    b = await pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    c = await b.new_context(user_agent=UA, viewport={"width": 1366, "height": 768}, locale="en-US")
    p = await c.new_page()
    await p.goto(_results_url("latest Zig release"), wait_until="domcontentloaded", timeout=25000)
    await p.wait_for_timeout(2500)
    html = await p.content()
    ms = [m.group(1) for m in _HREF_RE.finditer(html)]
    for u in ms:
        if "ck/a" in u:
            print("MATCH ck/a:", u[:160])
    print("total hrefs:", len(ms), "with ck/a:", sum('ck/a' in u for u in ms))
    # count raw ck/a occurrences in html
    print("raw 'ck/a' count in html:", html.count("ck/a"))
    idx = html.find("ck/a")
    print("context:", html[idx-30:idx+180] if idx >= 0 else "none")
    await b.close()
    await pw.stop()


asyncio.run(main())
