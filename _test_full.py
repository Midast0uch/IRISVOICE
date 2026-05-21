from playwright.sync_api import sync_playwright
import time
import requests

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    
    errors = []
    page.on('console', lambda msg: errors.append(f'{msg.type}: {msg.text}') if msg.type == 'error' else None)
    page.on('pageerror', lambda err: errors.append(f'PAGEERROR: {err}'))
    
    print('========== FULL VALIDATION TEST ==========\n')
    
    # Clear everything
    page.goto('http://localhost:8080/mode-select')
    time.sleep(2)
    page.evaluate("localStorage.clear()")
    page.reload()
    time.sleep(2)
    
    # 1. MODE SELECT + NAVIGATION
    print('--- 1. ModeSelect Page ---')
    print('  URL:', page.url)
    print('  Personal card visible:', page.locator('text=Personal Mode').count() > 0)
    print('  Developer card visible:', page.locator('text=Developer Mode').count() > 0)
    
    page.click('text=Personal Mode')
    time.sleep(3)
    print('  After click URL:', page.url)
    print('  localStorage mode:', page.evaluate("localStorage.getItem('iris-mode')"))
    print('  On dashboard:', '/' == page.url.replace('http://localhost:8080', ''))
    
    # 2. OVERVIEW PAGE (Personal mode)
    print('\n--- 2. Overview Page (Personal) ---')
    html = page.content()
    print('  Page title:', page.title())
    print('  Has sidebar:', page.locator('nav').count() > 0)
    print('  Has Launch Widget:', 'Launch Widget' in html)
    print('  Has metric cards:', 'Mode' in html and 'Uptime' in html)
    print('  DEV badge visible:', 'DEV' in html)
    print('  Theme toggle visible:', page.locator('button[aria-label*="Switch to"]').count() > 0)
    
    # 3. THEME TOGGLE
    print('\n--- 3. Theme Toggle ---')
    theme = page.evaluate("""() => {
        return document.documentElement.classList.contains('dark') ? 'dark' : 
               document.documentElement.classList.contains('light') ? 'light' : 'none';
    }""")
    print('  Current theme:', theme)
    
    toggle = page.locator('button[aria-label*="Switch to"]').first
    if toggle.count() > 0:
        toggle.click()
        time.sleep(1)
        new_theme = page.evaluate("""() => {
            return document.documentElement.classList.contains('dark') ? 'dark' : 
                   document.documentElement.classList.contains('light') ? 'light' : 'none';
        }""")
        print('  After toggle:', new_theme)
        print('  Theme changed:', new_theme != theme)
        
        # Screenshot light
        page.screenshot(path='c:/Users/midas/Desktop/IRISVOICE/iris-launcher/validate_theme_light.png')
        
        # Toggle back
        toggle.click()
        time.sleep(1)
        page.screenshot(path='c:/Users/midas/Desktop/IRISVOICE/iris-launcher/validate_theme_dark.png')
    else:
        print('  Theme toggle NOT found')
    
    # 4. DEVELOPER MODE
    print('\n--- 4. Developer Mode ---')
    page.goto('http://localhost:8080/mode-select')
    time.sleep(2)
    page.click('text=Developer Mode')
    time.sleep(3)
    print('  After click URL:', page.url)
    print('  localStorage mode:', page.evaluate("localStorage.getItem('iris-mode')"))
    html = page.content()
    print('  DEV badge visible:', 'DEV' in html)
    print('  Git in sidebar:', 'Git & Source' in html)
    print('  Diff Review in sidebar:', 'Diff Review' in html)
    print('  GitHub in sidebar:', 'GitHub' in html)
    print('  Rebuild in sidebar:', 'Rebuild' in html)
    
    # 5. GIT PAGE
    page.goto('http://localhost:8080/developer/git')
    time.sleep(2)
    html = page.content()
    print('\n--- 5. Git Page ---')
    print('  Live indicator:', 'Live' in html or 'Offline' in html)
    print('  Branch shown:', 'main' in html.lower())
    print('  Commit button:', 'Commit' in html)
    print('  Rollback button:', 'Rollback' in html)
    
    # 6. DIFF REVIEW PAGE
    page.goto('http://localhost:8080/developer/diff')
    time.sleep(2)
    html = page.content()
    print('\n--- 6. DiffReview Page ---')
    print('  Empty state:', 'No pending' in html or 'pending' in html.lower())
    print('  Approve button:', 'Approve' in html)
    print('  Reject button:', 'Reject' in html)
    
    # 7. PROJECTS PAGE
    page.goto('http://localhost:8080/projects')
    time.sleep(2)
    html = page.content()
    print('\n--- 7. Projects Page ---')
    print('  Add project button:', 'Add' in html or 'New' in html or '+' in html)
    print('  Project list:', 'Projects' in html)
    
    # 8. GITHUB PAGE
    page.goto('http://localhost:8080/developer/github')
    time.sleep(2)
    html = page.content()
    print('\n--- 8. GitHub Page ---')
    print('  Connect gate:', 'Connect' in html and 'GitHub' in html)
    
    # 9. TAILSCALE PAGE
    page.goto('http://localhost:8080/tailscale')
    time.sleep(2)
    html = page.content()
    print('\n--- 9. Tailscale Page ---')
    print('  Content found:', 'Tailscale' in html or 'tailscale' in html.lower())
    
    # 10. IDENTITY PAGE
    page.goto('http://localhost:8080/identity')
    time.sleep(2)
    html = page.content()
    print('\n--- 10. Identity Page ---')
    print('  Content found:', 'Identity' in html or 'Seed' in html or 'identity' in html.lower())
    
    # 11. FIRST RUN PAGE
    page.goto('http://localhost:8080/first-run')
    time.sleep(2)
    html = page.content()
    print('\n--- 11. FirstRun Page ---')
    print('  Content found:', 'Seed' in html or 'Setup' in html or 'First' in html)
    
    # 12. REBUILD PAGE
    page.goto('http://localhost:8080/developer/rebuild')
    time.sleep(2)
    html = page.content()
    print('\n--- 12. Rebuild Page ---')
    print('  Content found:', 'Rebuild' in html or 'Build' in html or 'build' in html.lower())
    
    # 13. BACKEND API
    print('\n--- 13. Backend API ---')
    try:
        r = requests.get('http://localhost:8000/api/mode', timeout=5)
        print('  Mode API:', r.status_code, r.json())
    except Exception as e:
        print('  Mode API error:', e)
    
    try:
        r = requests.get('http://localhost:8000/api/git/status', timeout=5)
        data = r.json()
        print('  Git status API:', r.status_code, 'branch=', data.get('branch', 'N/A'))
    except Exception as e:
        print('  Git status API error:', e)
    
    try:
        r = requests.get('http://localhost:8000/api/launcher/status', timeout=5)
        data = r.json()
        print('  Launcher status API:', r.status_code, 'mode=', data.get('mode', 'N/A'))
    except Exception as e:
        print('  Launcher status API error:', e)
    
    try:
        r = requests.get('http://localhost:8000/api/projects', timeout=5)
        data = r.json()
        print('  Projects API:', r.status_code, 'count=', len(data.get('projects', [])))
    except Exception as e:
        print('  Projects API error:', e)
    
    # 14. CONSOLE ERRORS
    print('\n--- 14. Console Errors ---')
    if errors:
        for e in errors[:10]:
            print('  ', e)
        if len(errors) > 10:
            print(f'  ... and {len(errors) - 10} more')
    else:
        print('  No console errors')
    
    browser.close()
    print('\n========== TEST COMPLETE ==========')
