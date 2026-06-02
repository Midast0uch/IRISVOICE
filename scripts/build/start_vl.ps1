# =============================================================================
# LFM2.5-VL-450M Vision Server — Windows PowerShell Startup
# Starts llama-server with LFM2.5-VL-450M on port 8081
#
# REQUIREMENTS:
#   1. llama-server.exe in PATH (or set $env:LLAMA_SERVER below)
#   2. LFM2.5-VL-450M-Q4_0.gguf in %USERPROFILE%\models\LFM2.5-VL-450M\
#   3. mmproj-LFM2.5-VL-450m-Q8_0.gguf in same directory (CRITICAL)
#
# DOWNLOAD (run once):
#   python scripts\download_vl_model.py
# =============================================================================

$ModelDir = "$env:USERPROFILE\models\LFM2.5-VL-450M"
$Model    = "$ModelDir\LFM2.5-VL-450M-Q4_0.gguf"
$MmProj   = "$ModelDir\mmproj-LFM2.5-VL-450m-Q8_0.gguf"

# Find llama-server — look in PATH first, then common install dirs
$LlamaServer = (Get-Command llama-server.exe -ErrorAction SilentlyContinue)?.Source
if (-not $LlamaServer) {
    $Candidates = @(
        "$env:LOCALAPPDATA\llama.cpp\llama-server.exe",
        "C:\llama.cpp\llama-server.exe",
        "$env:ProgramFiles\llama.cpp\llama-server.exe"
    )
    foreach ($c in $Candidates) {
        if (Test-Path $c) { $LlamaServer = $c; break }
    }
}
if (-not $LlamaServer) {
    Write-Error "[ERROR] llama-server.exe not found. Install llama.cpp and add to PATH."
    exit 1
}

Write-Host "============================================" -ForegroundColor Cyan
Write-Host " LFM2.5-VL-450M Vision Server"
Write-Host " Port: 8081"
Write-Host " Model: $Model"
Write-Host "============================================" -ForegroundColor Cyan

if (-not (Test-Path $Model)) {
    Write-Error "[ERROR] Model not found: $Model"
    Write-Host "Run: python scripts\download_vl_model.py" -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $MmProj)) {
    Write-Error "[ERROR] mmproj not found: $MmProj  (REQUIRED for vision)"
    Write-Host "Run: python scripts\download_vl_model.py" -ForegroundColor Yellow
    exit 1
}

Write-Host "[INFO] Starting llama-server on port 8081..." -ForegroundColor Green

& $LlamaServer `
    --model $Model `
    --mmproj $MmProj `
    --alias lfm2.5-vl `
    --port 8081 `
    --host 127.0.0.1 `
    --n-gpu-layers 1 `
    --ctx-size 4096 `
    --image-max-tokens 256 `
    --verbose
