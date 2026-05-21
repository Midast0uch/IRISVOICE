from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    
    page.goto('http://localhost:8080/developer/git')
    time.sleep(2)
    
    html = page.content()
    print('Git & Source Control (raw &):', 'Git & Source Control' in html)
    print('Git &amp; Source Control (encoded):', 'Git &amp; Source Control' in html)
    print('Git Source (no amp):', 'Git Source' in html)
    
    # Also check innerText
    text = page.evaluate("document.body.innerText")
    print('innerText Git & Source Control:', 'Git & Source Control' in text)
    
    browser.close()
