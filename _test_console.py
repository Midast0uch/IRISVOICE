from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    
    logs = []
    page.on('console', lambda msg: logs.append(msg.text))
    
    page.goto('http://localhost:8080/mode-select')
    time.sleep(2)
    page.evaluate("localStorage.clear()")
    page.reload()
    time.sleep(2)
    
    print('Before click: URL =', page.url)
    
    page.click('text=Personal Mode')
    time.sleep(4)
    
    print('After click: URL =', page.url)
    print('Console logs:')
    for log in logs:
        print('  ', log)
    if not logs:
        print('  (none)')
    
    browser.close()
