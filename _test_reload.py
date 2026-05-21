from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    
    # Start at mode-select (no mode set initially)
    page.goto('http://localhost:8080/mode-select')
    time.sleep(2)
    
    print('Before setting mode:')
    print('  URL:', page.url)
    
    # Set mode in localStorage and reload
    page.evaluate("""() => {
        localStorage.setItem('iris-mode', 'developer');
        localStorage.setItem('iris-github-connected', 'true');
    }""")
    page.reload()
    time.sleep(3)
    
    print('\nAfter reload with developer mode:')
    print('  URL:', page.url)
    print('  localStorage mode:', page.evaluate("localStorage.getItem('iris-mode')"))
    
    text = page.evaluate("""() => document.body.innerText""")
    print('  Body text (first 1500 chars):')
    print(text[:1500])
    
    page.screenshot(path='c:/Users/midas/Desktop/IRISVOICE/iris-launcher/debug_after_reload.png')
    
    browser.close()
