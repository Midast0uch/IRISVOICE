from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    
    print('========== THEME TEST ==========\n')
    
    page.goto('http://localhost:8080/')
    time.sleep(1)
    page.evaluate("() => { localStorage.setItem('iris-mode', 'developer'); }")
    page.goto('http://localhost:8080/')
    time.sleep(2)
    
    theme = page.evaluate("""() => {
        const html = document.documentElement;
        return html.classList.contains('dark') ? 'dark' : 
               html.classList.contains('light') ? 'light' : 'none';
    }""")
    print('Current theme:', theme)
    print('localStorage theme:', page.evaluate("() => localStorage.getItem('iris-theme')") or 'dark (default)')
    
    buttons = page.query_selector_all('button')
    toggle_btn = None
    for btn in buttons:
        label = btn.get_attribute('aria-label') or ''
        if 'Switch' in label:
            toggle_btn = btn
            print('Found theme toggle button with aria-label:', label)
            break
    
    if toggle_btn:
        toggle_btn.click()
        time.sleep(2)
        new_theme = page.evaluate("""() => {
            const html = document.documentElement;
            return html.classList.contains('dark') ? 'dark' : 
                   html.classList.contains('light') ? 'light' : 'none';
        }""")
        print('Theme after toggle:', new_theme)
        print('localStorage theme after toggle:', page.evaluate("() => localStorage.getItem('iris-theme')"))
        print('Theme changed:', new_theme != theme)
        
        page.screenshot(path='c:/Users/midas/Desktop/IRISVOICE/iris-launcher/theme_light.png')
        print('Light theme screenshot saved')
        
        toggle_btn.click()
        time.sleep(2)
        page.screenshot(path='c:/Users/midas/Desktop/IRISVOICE/iris-launcher/theme_dark.png')
        print('Dark theme screenshot saved')
    else:
        print('Theme toggle button NOT FOUND')
        for btn in buttons[:15]:
            label = btn.get_attribute('aria-label') or ''
            text = btn.inner_text()[:30]
            print(f'  Button: aria-label="{label}", text="{text}"')
    
    browser.close()
