$vhdx = "C:\Users\midas\AppData\Local\Packages\CanonicalGroupLimited.Ubuntu_79rhkp1fndgsc\LocalState\ext4.vhdx"
Write-Host "Mounting VHDX read-only..."
try {
    $disk = Mount-VHD -Path $vhdx -Passthru -ReadOnly -NoDriveLetter -ErrorAction Stop
    $diskNum = $disk.Number
    Write-Host "SUCCESS: Mounted as Disk $diskNum"
    
    # Check if we can get partitions
    $parts = $disk | Get-Partition -ErrorAction SilentlyContinue
    if ($parts) {
        Write-Host "Partitions found:"
        $parts | Format-Table -AutoSize
    } else {
        Write-Host "No partitions detected (ext4 filesystem - Windows can't read it natively)"
    }
    
    # Dismount
    Dismount-VHD -Path $vhdx
    Write-Host "VHDX dismounted safely"
}
catch {
    Write-Host "ERROR: $_"
    Write-Host "VHDX may be in use or PowerShell Mount-VHD not available"
}
