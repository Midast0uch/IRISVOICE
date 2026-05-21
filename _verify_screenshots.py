from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    
    # Use the browser preview proxy
    base = "http://127.0.0.1:64494"
    out = "c:/Users/midas/Desktop/IRISVOICE/iris-launcher"
    
    # 1. Mode Select
    page.goto(f"{base}/mode-select")
    time.sleep(2)
    page.screenshot(path=f"{out}/01_mode_select.png")
    print("01_mode_select.png saved")
    
    # 2. Click Personal Mode
    page.click('text=Personal Mode')
    time.sleep(3)
    page.screenshot(path=f"{out}/02_overview_personal.png")
    print("02_overview_personal.png saved")
    print(f"  URL: {page.url}")
    print(f"  Has Overview: {'System Overview' in page.content()}")
    
    # 3. Toggle theme
    toggle = page.locator('button[aria-label*="Switch to"]').first
    if toggle.count() > 0:
        toggle.click()
        time.sleep(1)
        page.screenshot(path=f"{out}/03_overview_light.png")
        print("03_overview_light.png saved")
        toggle.click()
        time.sleep(1)
    
    # 4. Switch to Developer Mode
    page.goto(f"{base}/mode-select")
    time.sleep(2)
    page.click('text=Developer Mode')
    time.sleep(3)
    page.screenshot(path=f"{out}/04_overview_dev.png")
    print("04_overview_dev.png saved")
    print(f"  URL: {page.url}")
    print(f"  Has DEV badge: {'DEV' in page.content()}")
    
    # 5. Git page
    page.goto(f"{base}/developer/git")
    time.sleep(3)
    page.screenshot(path=f"{out}/05_git.png")
    print("05_git.png saved")
    
    # 6. Diff page
    page.goto(f"{base}/developer/diff")
    time.sleep(3)
    page.screenshot(path=f"{out}/06_diff.png")
    print("06_diff.png saved")
    
    # 7. GitHub page
    page.goto(f"{base}/developer/github")
    time.sleep(3)
    page.screenshot(path=f"{out}/07_github.png")
    print("07_github.png saved")
    
    # 8. Projects page
    page.goto(f"{base}/projects")
    time.sleep(3)
    page.screenshot(path=f"{out}/08_projects.png")
    print("08_projects.png saved")
    
    browser.close()
    print("\nAll screenshots saved to iris-launcher/")
