from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    
    page.goto('http://localhost:8080/mode-select')
    time.sleep(2)
    
    print('Before nav: URL =', page.url)
    
    # Directly set window.location.href
    page.evaluate("window.location.href = '/'")
    
    # Wait for URL to change
    for i in range(10):
        time.sleep(0.5)
        print(f'  Check {i+1}: URL = {page.url}')
        if page.url == 'http://localhost:8080/':
            break
    
    print('After nav: URL =', page.url)
    
    browser.close()
