from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    
    print('========== DEBUG TEST ==========\n')
    
    # Clear everything
    page.goto('http://localhost:8080/')
    time.sleep(1)
    page.evaluate("localStorage.clear()")
    page.reload()
    time.sleep(2)
    
    print('After clear:')
    print('  URL:', page.url)
    print('  localStorage iris-mode:', page.evaluate("localStorage.getItem('iris-mode')"))
    print('  Page has ModeSelect:', 'Personal Mode' in page.content())
    print('  Page has Overview:', 'Launch IRIS' in page.content())
    
    # Set mode and reload
    page.evaluate("localStorage.setItem('iris-mode', 'developer')")
    page.reload()
    time.sleep(3)
    
    print('\nAfter setting developer mode:')
    print('  URL:', page.url)
    print('  localStorage iris-mode:', page.evaluate("localStorage.getItem('iris-mode')"))
    html = page.content()
    print('  Page has ModeSelect:', 'Personal Mode' in html)
    print('  Page has Overview:', 'Launch IRIS' in html)
    print('  Page has sidebar:', '<nav' in html.lower() or 'sidebar' in html.lower())
    print('  Page has ThemeToggle:', 'Switch to' in html)
    
    # Find ThemeToggle button
    buttons = page.query_selector_all('button')
    print(f'\n  Total buttons: {len(buttons)}')
    for btn in buttons[:10]:
        label = btn.get_attribute('aria-label') or ''
        text = btn.inner_text()[:40].replace('\n', ' ')
        print(f'    aria-label="{label}", text="{text}"')
    
    browser.close()
