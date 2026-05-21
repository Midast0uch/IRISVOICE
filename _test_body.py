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
    text = page.evaluate("document.body.innerText")
    print('  Body text:', text[:200])
    
    page.click('text=Personal Mode')
    time.sleep(3)
    
    print('\nAfter click:')
    print('  URL:', page.url)
    text = page.evaluate("document.body.innerText")
    print('  Body text:', text[:500] if text else '(empty)')
    print('  Body length:', len(text) if text else 0)
    
    page.screenshot(path='c:/Users/midas/Desktop/IRISVOICE/iris-launcher/debug_click_result.png')
    
    browser.close()
