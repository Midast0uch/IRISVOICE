# Start both services as detached processes
param()

$root = "C:\dev\IRISVOICE"

Write-Host "Starting backend..."
$be = Start-Process -FilePath "python" -ArgumentList "main.py" -WorkingDirectory "$root\backend" -WindowStyle Hidden -PassThru
Write-Host "Backend PID: $($be.Id)"

Start-Sleep -Seconds 3

Write-Host "Starting frontend..."
$fe = Start-Process -FilePath "npm" -ArgumentList "run dev" -WorkingDirectory $root -WindowStyle Hidden -PassThru
Write-Host "Frontend PID: $($fe.Id)"

# Write PIDs to file for monitoring
@"
BACKEND_PID=$($be.Id)
FRONTEND_PID=$($fe.Id)
"@ | Out-File -FilePath "$root\.iris-pids\pids.txt" -Encoding ascii

Write-Host "Services started. PIDs saved to .iris-pids\pids.txt"
