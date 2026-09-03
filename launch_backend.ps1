#!/usr/bin/env pwsh
Start-Process -FilePath "C:\dev\IRISVOICE\venv\Scripts\python.exe" -ArgumentList "start-backend.py" -WorkingDirectory "C:\dev\IRISVOICE" -WindowStyle Hidden
Write-Host "LAUNCHED"
exit 0
