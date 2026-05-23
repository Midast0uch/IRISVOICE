# IRIS Screenshot Capture Script
$screenshotsDir = "C:\Users\midas\Desktop\IRISVOICE\screenshots"
New-Item -ItemType Directory -Path $screenshotsDir -Force | Out-Null
Write-Host "Screenshots directory: $screenshotsDir"

# Start backend
Write-Host "Starting backend..."
$backendJob = Start-Job -ScriptBlock {
    Set-Location "C:\Users\midas\Desktop\IRISVOICE"
    python start-backend.py
}
Write-Host "Backend job ID: $($backendJob.Id)"

# Start frontend
Write-Host "Starting frontend..."
$frontendJob = Start-Job -ScriptBlock {
    Set-Location "C:\Users\midas\Desktop\IRISVOICE"
    npm run dev
}
Write-Host "Frontend job ID: $($frontendJob.Id)"

# Wait for servers
Write-Host "Waiting for servers to start..."
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $backendReady = (Invoke-WebRequest -Uri "http://localhost:8000" -Method HEAD -TimeoutSec 2 -ErrorAction SilentlyContinue).StatusCode -eq 200
    } catch { $backendReady = $false }
    try {
        $frontendReady = (Invoke-WebRequest -Uri "http://localhost:3000" -Method HEAD -TimeoutSec 2 -ErrorAction SilentlyContinue).StatusCode -eq 200
    } catch { $frontendReady = $false }
    
    if ($backendReady -and $frontendReady) {
        Write-Host "Both servers ready after $($i+1) seconds!"
        break
    }
    if ($i % 5 -eq 0) {
        Write-Host "Still waiting... backend=$backendReady frontend=$frontendReady"
    }
}

# Take screenshots with Python/Playwright
Write-Host "Taking screenshots..."
$pyScript = @"
import sys
sys.path.insert(0, r'C:\Users\midas\Desktop\IRISVOICE')
from playwright.sync_api import sync_playwright
import os

d = r'$screenshotsDir'
os.makedirs(d, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1920, 'height': 1080})
    
    print('Screenshot 1: localhost:3000')
    page.goto('http://localhost:3000', timeout=30000)
    page.wait_for_timeout(4000)
    p1 = os.path.join(d, '01_localhost_desktop.png')
    page.screenshot(path=p1, full_page=True)
    print(f'Saved: {p1}')
    
    print('Screenshot 2: Tailscale IP')
    page.goto('http://100.117.236.6:3000', timeout=30000)
    page.wait_for_timeout(4000)
    p2 = os.path.join(d, '02_tailscale_chat_spotlight.png')
    page.screenshot(path=p2, full_page=True)
    print(f'Saved: {p2}')
    
    browser.close()

print('Done! Files:')
for f in os.listdir(d):
    print(f'  {f}')
"@

python -c $pyScript

# Stop jobs
Write-Host "Stopping servers..."
Stop-Job -Job $backendJob, $frontendJob -ErrorAction SilentlyContinue
Remove-Job -Job $backendJob, $frontendJob -ErrorAction SilentlyContinue

Write-Host "Complete!"
