from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    
    page.goto('http://localhost:8080/mode-select')
    time.sleep(2)
    page.evaluate("localStorage.clear()")
    page.reload()
    time.sleep(3)
    
    print('Before click: URL =', page.url)
    
    page.click('text=Personal Mode')
    time.sleep(3)
    
    print('After click: URL =', page.url)
    print('Has Overview content:', 'System Overview' in page.content())
    print('Has ModeSelect:', 'Personal Mode' in page.content())
    
    browser.close()
