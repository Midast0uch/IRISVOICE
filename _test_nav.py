from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    
    print('========== NAVIGATION BUG TEST ==========\n')
    
    # Clear and reload
    page.goto('http://localhost:8080/mode-select')
    time.sleep(2)
    page.evaluate("localStorage.clear()")
    page.reload()
    time.sleep(2)
    
    print('Before click:')
    print('  URL:', page.url)
    
    # Capture console logs
    logs = []
    page.on('console', lambda msg: logs.append(msg.text))
    
    # Click Personal mode
    page.click('text=Personal Mode')
    time.sleep(4)
    
    print('After click:')
    print('  URL:', page.url)
    print('  localStorage mode:', page.evaluate("localStorage.getItem('iris-mode')"))
    
    print('\nConsole logs:')
    for log in logs:
        if 'Launcher' in log or 'error' in log.lower() or 'navigate' in log.lower():
            print('  ', log)
    if not logs:
        print('  (no console logs)')
    
    # Try manual navigation to verify react-router works
    print('\nManual navigation test:')
    page.evaluate("() => { window.history.pushState({}, '', '/'); }")
    page.reload()
    time.sleep(2)
    print('  After manual nav to /, URL:', page.url)
    print('  Has Overview content:', 'Launch IRIS' in page.content())
    
    browser.close()
