from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    
    page.goto('http://localhost:8080/mode-select')
    time.sleep(2)
    page.evaluate("localStorage.clear()")
    page.reload()
    time.sleep(2)
    
    print('Before click:')
    print('  URL:', page.url)
    
    # Wait for navigation after click
    page.click('text=Personal Mode')
    
    # Wait for URL to change
    for i in range(10):
        time.sleep(0.5)
        print(f'  Check {i+1}: URL = {page.url}')
        if page.url == 'http://localhost:8080/':
            break
    
    print('\nAfter click:')
    print('  Final URL:', page.url)
    print('  localStorage mode:', page.evaluate("localStorage.getItem('iris-mode')"))
    
    text = page.evaluate("document.body.innerText")
    print('  Has Launch Widget:', 'Launch Widget' in text)
    print('  Has ModeSelect:', 'Personal Mode' in text)
    
    browser.close()
