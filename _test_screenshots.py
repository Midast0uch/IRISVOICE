from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    
    # Setup
    page.goto('http://localhost:8080/')
    time.sleep(1)
    page.evaluate("""() => {
        localStorage.clear();
        localStorage.setItem('iris-mode', 'developer');
        localStorage.setItem('iris-github-connected', 'true');
    }""")
    
    # 1. Overview (dark)
    page.goto('http://localhost:8080/')
    time.sleep(3)
    page.screenshot(path='c:/Users/midas/Desktop/IRISVOICE/iris-launcher/screenshot_overview_dark.png')
    
    # 2. Overview (light)
    toggle = page.locator('button[aria-label*="Switch to"]').first
    toggle.click()
    time.sleep(1)
    page.screenshot(path='c:/Users/midas/Desktop/IRISVOICE/iris-launcher/screenshot_overview_light.png')
    toggle.click()  # back to dark
    time.sleep(1)
    
    # 3. ModeSelect
    page.goto('http://localhost:8080/mode-select')
    time.sleep(2)
    page.screenshot(path='c:/Users/midas/Desktop/IRISVOICE/iris-launcher/screenshot_mode_select.png')
    
    # 4. Git Page
    page.goto('http://localhost:8080/developer/git')
    time.sleep(3)
    page.screenshot(path='c:/Users/midas/Desktop/IRISVOICE/iris-launcher/screenshot_git.png')
    
    # 5. DiffReview
    page.goto('http://localhost:8080/developer/diff')
    time.sleep(3)
    page.screenshot(path='c:/Users/midas/Desktop/IRISVOICE/iris-launcher/screenshot_diff.png')
    
    # 6. Projects
    page.goto('http://localhost:8080/projects')
    time.sleep(3)
    page.screenshot(path='c:/Users/midas/Desktop/IRISVOICE/iris-launcher/screenshot_projects.png')
    
    # 7. GitHub
    page.goto('http://localhost:8080/developer/github')
    time.sleep(3)
    page.screenshot(path='c:/Users/midas/Desktop/IRISVOICE/iris-launcher/screenshot_github.png')
    
    # 8. Personal mode sidebar
    page.goto('http://localhost:8080/mode-select')
    time.sleep(2)
    page.click('text=Personal Mode')
    time.sleep(3)
    page.screenshot(path='c:/Users/midas/Desktop/IRISVOICE/iris-launcher/screenshot_overview_personal.png')
    
    browser.close()
    print('Screenshots saved')
