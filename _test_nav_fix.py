from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    
    # Start fresh
    page.goto('http://localhost:8080/mode-select')
    time.sleep(2)
    page.evaluate("localStorage.clear()")
    page.reload()
    time.sleep(2)
    
    print('Before click:')
    print('  URL:', page.url)
    print('  localStorage mode:', page.evaluate("localStorage.getItem('iris-mode')"))
    
    # Click Personal Mode
    page.click('text=Personal Mode')
    time.sleep(3)
    
    print('\nAfter click Personal Mode:')
    print('  URL:', page.url)
    print('  localStorage mode:', page.evaluate("localStorage.getItem('iris-mode')"))
    
    text = page.evaluate("document.body.innerText")
    print('  Has Launch Widget:', 'Launch Widget' in text)
    print('  Has ModeSelect:', 'Personal Mode' in text)
    
    page.screenshot(path='c:/Users/midas/Desktop/IRISVOICE/iris-launcher/debug_after_click.png')
    
    browser.close()
