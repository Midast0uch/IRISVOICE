Get-Process -Id 40292 -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, StartTime, @{N='MB';E={[math]::Round($_.WorkingSet/1MB,1)}} | Format-Table -AutoSize
Write-Host "---command line:---"
Get-CimInstance Win32_Process -Filter "ProcessId=40292" | Select-Object -ExpandProperty CommandLine
