from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    
    logs = []
    def on_console(msg):
        text = msg.text
        logs.append(text)
        if 'ModeSelect' in text or 'Navigating' in text or 'location' in text.lower():
            print('CONSOLE:', text)
    
    page.on('console', on_console)
    
    page.goto('http://localhost:8080/mode-select')
    time.sleep(2)
    page.evaluate("localStorage.clear()")
    page.reload()
    time.sleep(3)
    
    print('Before click: URL =', page.url)
    
    page.click('text=Personal Mode')
    time.sleep(5)
    
    print('After click: URL =', page.url)
    print('Total logs captured:', len(logs))
    
    # Also check all logs for our debug message
    found = [l for l in logs if 'ModeSelect' in l]
    print('Found ModeSelect logs:', len(found))
    for l in found:
        print('  ->', l)
    
    browser.close()
