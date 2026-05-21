Write-Host "=== Checking VHDX status ==="
$vhdx = "C:\Users\midas\AppData\Local\Packages\CanonicalGroupLimited.Ubuntu_79rhkp1fndgsc\LocalState\ext4.vhdx"

# Check if VHDX already mounted
$disks = Get-Disk -ErrorAction SilentlyContinue | Where-Object { $_.OperationalStatus -eq "Online" }
$found = $false
foreach ($d in $disks) {
    try {
        $path = (Get-VHD -DiskNumber $d.Number -ErrorAction SilentlyContinue).Path
        if ($path -and $path -eq $vhdx) {
            Write-Host "VHDX ALREADY MOUNTED as Disk $($d.Number)" -ForegroundColor Yellow
            $found = $true
        }
    } catch {}
}

if (-not $found) {
    Write-Host "VHDX not currently mounted - safe to proceed" -ForegroundColor Green
}

# Check if WSL process still holds it
$wsl = Get-Process wsl -ErrorAction SilentlyContinue
if ($wsl) {
    Write-Host "WSL processes running:" $wsl.Count -ForegroundColor Yellow
} else {
    Write-Host "No WSL processes running - safe" -ForegroundColor Green
}
