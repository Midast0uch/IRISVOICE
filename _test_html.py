from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    
    page.goto('http://localhost:8080/')
    time.sleep(1)
    page.evaluate("""() => {
        localStorage.clear();
        localStorage.setItem('iris-mode', 'developer');
        localStorage.setItem('iris-github-connected', 'true');
    }""")
    page.goto('http://localhost:8080/')
    time.sleep(3)
    
    html = page.content()
    # Extract text content only
    text = page.evaluate("""() => document.body.innerText""")
    
    print('URL:', page.url)
    print('HTML length:', len(html))
    print('Text length:', len(text))
    print('\n--- First 2000 chars of body text ---')
    print(text[:2000])
    
    page.screenshot(path='c:/Users/midas/Desktop/IRISVOICE/iris-launcher/debug_overview.png')
    
    browser.close()
