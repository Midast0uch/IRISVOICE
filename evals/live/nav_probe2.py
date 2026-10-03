"""Backend-identical session open, standalone: same pool launch args, same context options."""
import asyncio, time, sys
sys.path.insert(0, r"C:\dev\IRISVOICE")
from backend.vision import browser_pool as bp
from backend.vision.browser_session import _context_options
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=bp._LAUNCH_ARGS)
        for i in range(3):
            ctx = await b.new_context(**_context_options()); p = await ctx.new_page(); t = time.monotonic()
            try:
                await p.goto("https://en.wikipedia.org", wait_until="domcontentloaded", timeout=60000); ok = "ok"
            except Exception as e: ok = type(e).__name__
            t2 = time.monotonic(); title = await p.title(); t3 = time.monotonic(); html = await p.content(); t4 = time.monotonic()
            print(f"try{i+1}: nav {t2-t:.1f}s {ok} title {t3-t2:.2f}s content {t4-t3:.2f}s ({len(html)} chars)", flush=True)
            await ctx.close()
        await b.close()
asyncio.run(main())
