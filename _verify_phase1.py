"""Phase 1 verification screenshots for terminal-chat-integration plan.

Interacts with the UI to build state rather than relying on localStorage injection.
"""
import asyncio
import os
from playwright.async_api import async_playwright

BASE = "http://localhost:3000?verify=chat"
OUTDIR = "verification/phase1"

async def capture(page, name):
    path = f"{OUTDIR}/{name}.png"
    await page.screenshot(path=path, full_page=False)
    print(f"[📸] {path}")

async def main():
    os.makedirs(OUTDIR, exist_ok=True)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()
        
        # Load app first so we can access localStorage
        print("Loading developer mode...")
        await page.goto(BASE, wait_until="networkidle")
        await page.evaluate("localStorage.clear();")
        await page.reload(wait_until="networkidle")
        # Wait for workspace to load (Suspense fallback: "Loading workspace...")
        await page.wait_for_timeout(3000)
        
        # === P1.2: Full layout ===
        # First click the + button to add virtual docs via FilePickerModal
        print("Adding tabs via FilePickerModal...")
        # The + New button contains text "New" and a Plus icon
        plus_btn = page.locator("button").filter(has_text="New").first
        await plus_btn.wait_for(state="visible", timeout=5000)
        await plus_btn.click()
        await page.wait_for_timeout(800)
        
        # Switch to Virtual Workspace tab
        virtual_tab = page.get_by_text("Virtual Workspace").first
        if await virtual_tab.is_visible():
            await virtual_tab.click()
            await page.wait_for_timeout(400)
        
        # Click architecture.md
        arch_doc = page.get_by_text("architecture.md").first
        if await arch_doc.is_visible():
            await arch_doc.click()
        await page.wait_for_timeout(600)
        
        # Add another tab
        plus_btn = page.locator("button").filter(has_text="New").first
        await plus_btn.click()
        await page.wait_for_timeout(800)
        spec_doc = page.get_by_text("spec.md").first
        if await spec_doc.is_visible():
            await spec_doc.click()
        await page.wait_for_timeout(600)
        
        # Close modal with Escape
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)
        
        # Take full layout screenshot
        await capture(page, "p1-2-full-layout")
        
        # === P1.13: Terminal collapsed ===
        print("Collapsing terminal...")
        terminal_header = page.get_by_text("Terminal").first
        if await terminal_header.is_visible():
            await terminal_header.click()
            await page.wait_for_timeout(600)
            await capture(page, "p1-13-terminal-collapsed")
            await terminal_header.click()  # re-expand
            await page.wait_for_timeout(600)
        
        # === P1.7: Archive dock hover ===
        print("Hovering archive dock...")
        archive_label = page.get_by_text("Archive", exact=False).first
        if await archive_label.is_visible():
            await archive_label.hover()
            await page.wait_for_timeout(400)
            await capture(page, "p1-7-archive-hover")
        
        # === P1.9: Resize width label ===
        print("Checking resize handle...")
        resize_handle = page.locator("div.cursor-col-resize").first
        try:
            await resize_handle.wait_for(state="visible", timeout=3000)
            box = await resize_handle.bounding_box()
            if box:
                await page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                await page.mouse.down()
                await page.mouse.move(box["x"] + box["width"]/2 + 50, box["y"] + box["height"]/2)
                await page.wait_for_timeout(400)
                await capture(page, "p1-9-resize-width-label")
                await page.mouse.up()
        except Exception as e:
            print(f"  Resize not available: {e}")
        
        # === P1.15: Zen mode (personal equivalent) ===
        print("Switching to zen mode...")
        focus_btn = page.locator("button").filter(has_text=re.compile(r"Full|Work|Chat|Zen")).first
        try:
            await focus_btn.wait_for(state="visible", timeout=3000)
            await focus_btn.click()  # work
            await page.wait_for_timeout(400)
            await focus_btn.click()  # chat
            await page.wait_for_timeout(400)
            await focus_btn.click()  # zen
            await page.wait_for_timeout(600)
            await capture(page, "p1-15-zen-mode")
        except Exception as e:
            print(f"  Focus toggle not available: {e}")
        
        await browser.close()
        print(f"\n✅ Phase 1 verification complete. Screenshots in {OUTDIR}/")

if __name__ == "__main__":
    import re
    asyncio.run(main())
