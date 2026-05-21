from playwright.sync_api import sync_playwright
import time
import requests

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1280, 'height': 800})
    
    errors = []
    page.on('console', lambda msg: errors.append(f'{msg.type}: {msg.text}') if msg.type == 'error' else None)
    page.on('pageerror', lambda err: errors.append(f'PAGEERROR: {err}'))
    
    print('========== FOCUSED VALIDATION TEST ==========\n')
    
    # Setup: clear and set developer mode + github connected
    page.goto('http://localhost:8080/')
    time.sleep(1)
    page.evaluate("""() => {
        localStorage.clear();
        localStorage.setItem('iris-mode', 'developer');
        localStorage.setItem('iris-github-connected', 'true');
    }""")
    page.goto('http://localhost:8080/')
    time.sleep(3)
    
    print('--- Setup ---')
    print('  URL:', page.url)
    print('  Mode:', page.evaluate("localStorage.getItem('iris-mode')"))
    print('  GitHub:', page.evaluate("localStorage.getItem('iris-github-connected')"))
    
    # 1. OVERVIEW PAGE
    html = page.content()
    print('\n--- 1. Overview Page ---')
    print('  Launch Widget button:', 'Launch Widget' in html)
    print('  Metric cards (Mode/Uptime/Pending/Node):', 'Mode' in html and 'Uptime' in html and 'Pending' in html and 'Node ID' in html)
    print('  System Health section:', 'System Health' in html)
    print('  Git Status section:', 'Git Status' in html)
    print('  Backend online badge:', 'BACKEND ONLINE' in html)
    print('  DEV badge:', 'DEV' in html)
    print('  Theme toggle:', 'Switch to' in html)
    
    # 2. THEME TOGGLE
    print('\n--- 2. Theme Toggle ---')
    theme = page.evaluate("""() => document.documentElement.classList.contains('dark') ? 'dark' : 'light'""")
    print('  Before:', theme)
    toggle = page.locator('button[aria-label*="Switch to"]').first
    if toggle.count() > 0:
        toggle.click()
        time.sleep(1)
        new_theme = page.evaluate("""() => document.documentElement.classList.contains('dark') ? 'dark' : 'light'""")
        print('  After toggle:', new_theme)
        print('  Changed:', new_theme != theme)
        page.screenshot(path='c:/Users/midas/Desktop/IRISVOICE/iris-launcher/validate_light.png')
        toggle.click()
        time.sleep(1)
        page.screenshot(path='c:/Users/midas/Desktop/IRISVOICE/iris-launcher/validate_dark.png')
    else:
        print('  Toggle NOT found')
    
    # 3. SIDEBAR DEV ITEMS
    html = page.content()
    print('\n--- 3. Sidebar (Dev Mode) ---')
    print('  Overview:', 'Overview' in html)
    print('  Identity:', 'Identity' in html)
    print('  Projects:', 'Projects' in html)
    print('  Tailscale:', 'Tailscale' in html)
    print('  Git & Source:', 'Git & Source' in html)
    print('  Diff Review:', 'Diff Review' in html)
    print('  GitHub:', 'GitHub' in html)
    print('  Rebuild:', 'Rebuild' in html)
    
    # 4. GIT PAGE (with github connected)
    page.goto('http://localhost:8080/developer/git')
    time.sleep(3)
    html = page.content()
    print('\n--- 4. Git Page ---')
    print('  Title:', 'Git & Source Control' in html)
    print('  Live indicator:', 'Live' in html or 'offline' in html.lower())
    print('  Commit All button:', 'Commit All' in html)
    print('  Rollback button:', 'Rollback to Good' in html)
    print('  Branch badge:', 'BRANCH:' in html)
    print('  Commit history:', 'Commit History' in html)
    
    # 5. DIFF REVIEW PAGE (with github connected)
    page.goto('http://localhost:8080/developer/diff')
    time.sleep(3)
    html = page.content()
    print('\n--- 5. DiffReview Page ---')
    print('  Title:', 'Diff Review' in html)
    print('  Empty state:', 'No pending writes' in html or 'pending' in html.lower())
    print('  Approve button:', 'Approve' in html)
    print('  Reject button:', 'Reject' in html)
    
    # 6. PROJECTS PAGE
    page.goto('http://localhost:8080/projects')
    time.sleep(3)
    html = page.content()
    print('\n--- 6. Projects Page ---')
    print('  Title:', 'Projects' in html)
    print('  Add button:', 'Add' in html or 'New' in html)
    
    # 7. GITHUB PAGE
    page.goto('http://localhost:8080/developer/github')
    time.sleep(3)
    html = page.content()
    print('\n--- 7. GitHub Page ---')
    print('  Title:', 'GitHub Connection' in html)
    print('  Connect to GitHub:', 'Connect to GitHub' in html)
    print('  Authenticate button:', 'Authenticate' in html)
    
    # 8. TAILSCALE PAGE
    page.goto('http://localhost:8080/tailscale')
    time.sleep(3)
    html = page.content()
    print('\n--- 8. Tailscale Page ---')
    print('  Title:', 'Tailscale' in html or 'tailscale' in html.lower())
    
    # 9. IDENTITY PAGE
    page.goto('http://localhost:8080/identity')
    time.sleep(3)
    html = page.content()
    print('\n--- 9. Identity Page ---')
    print('  Title:', 'Identity' in html or 'identity' in html.lower())
    
    # 10. FIRST RUN PAGE
    page.goto('http://localhost:8080/first-run')
    time.sleep(3)
    html = page.content()
    print('\n--- 10. FirstRun Page ---')
    print('  Content:', 'Seed Phrase' in html or 'Setup' in html or 'First' in html)
    
    # 11. REBUILD PAGE
    page.goto('http://localhost:8080/developer/rebuild')
    time.sleep(3)
    html = page.content()
    print('\n--- 11. Rebuild Page ---')
    print('  Content:', 'Rebuild' in html or 'Build' in html or 'build' in html.lower())
    
    # 12. CONSOLE ERRORS
    print('\n--- 12. Console Errors ---')
    if errors:
        for e in errors[:10]:
            print('  ', e)
    else:
        print('  No errors')
    
    browser.close()
    print('\n========== DONE ==========')
