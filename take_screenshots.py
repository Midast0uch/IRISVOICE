import subprocess
import time
import os
import sys

# Create screenshots directory
screenshots_dir = r'C:\Users\midas\Desktop\IRISVOICE\screenshots'
os.makedirs(screenshots_dir, exist_ok=True)
print(f"Screenshots dir: {screenshots_dir}")

# Check if servers are already running
import urllib.request

def check_server(url, timeout=2):
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except:
        return False

backend_running = check_server('http://localhost:8000')
frontend_running = check_server('http://localhost:3000')

print(f"Backend running: {backend_running}")
print(f"Frontend running: {frontend_running}")

# Start backend if not running
backend_proc = None
if not backend_running:
    print("Starting backend...")
    backend_proc = subprocess.Popen(
        [sys.executable, 'start-backend.py'],
        cwd=r'C:\Users\midas\Desktop\IRISVOICE',
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
    )
    print(f"Backend PID: {backend_proc.pid}")
    time.sleep(5)

# Start frontend if not running
frontend_proc = None
if not frontend_running:
    print("Starting frontend...")
    frontend_proc = subprocess.Popen(
        ['cmd', '/c', 'npm run dev'],
        cwd=r'C:\Users\midas\Desktop\IRISVOICE',
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
    )
    print(f"Frontend PID: {frontend_proc.pid}")
    time.sleep(10)

# Wait for servers to be ready
for i in range(30):
    if check_server('http://localhost:8000') and check_server('http://localhost:3000'):
        print("Both servers ready!")
        break
    print(f"Waiting for servers... {i+1}s")
    time.sleep(1)
else:
    print("WARNING: Servers may not be fully ready")

# Take screenshots using Playwright
try:
    from playwright.sync_api import sync_playwright
    print("Playwright available, taking screenshots...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1920, 'height': 1080})
        
        # Screenshot 1: localhost desktop view
        print("Navigating to localhost:3000...")
        page.goto('http://localhost:3000', timeout=30000)
        page.wait_for_timeout(3000)
        path1 = os.path.join(screenshots_dir, '01_localhost_desktop.png')
        page.screenshot(path=path1, full_page=True)
        print(f"Saved: {path1}")
        
        # Screenshot 2: Tailscale IP chat spotlight
        print("Navigating to Tailscale IP...")
        page.goto('http://100.117.236.6:3000', timeout=30000)
        page.wait_for_timeout(3000)
        path2 = os.path.join(screenshots_dir, '02_tailscale_chat_spotlight.png')
        page.screenshot(path=path2, full_page=True)
        print(f"Saved: {path2}")
        
        browser.close()
    
    print("All screenshots taken successfully!")
    
except ImportError:
    print("Playwright not available, trying alternate method...")
    # Try using Edge in headless mode
    edge_path = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
    if os.path.exists(edge_path):
        print("Using Edge for screenshots...")
        # This is a fallback - not ideal but might work
        pass
    else:
        print("No screenshot method available")

# Cleanup
if backend_proc:
    print("Stopping backend...")
    backend_proc.terminate()
if frontend_proc:
    print("Stopping frontend...")
    frontend_proc.terminate()

print("Done!")
