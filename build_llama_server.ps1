# One-command build script for llama-server with CUDA (Windows)
# Usage: .\build_llama_server.ps1
#
# Prerequisites:
#   - Visual Studio 2022 Build Tools (or full VS 2022)
#   - CMake >= 3.26
#   - CUDA Toolkit >= 12.0
#   - Git

param(
    [switch]$CPUOnly,      # Build without CUDA (fallback)
    [switch]$Clean        # Remove existing build before configuring
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$BuildDir = Join-Path $RepoRoot "llama.cpp" "build"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  IRIS llama-server Build Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Verify source exists
$LlamaSrc = Join-Path $RepoRoot "llama.cpp"
if (-not (Test-Path (Join-Path $LlamaSrc "CMakeLists.txt"))) {
    Write-Host "Cloning ggml-org/llama.cpp into llama.cpp/ ..." -ForegroundColor Yellow
    git clone --depth 1 https://github.com/ggml-org/llama.cpp.git $LlamaSrc
}

# Clean if requested
if ($Clean -and (Test-Path $BuildDir)) {
    Write-Host "Cleaning existing build directory..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $BuildDir
}

# Configure
Write-Host "`nConfiguring CMake..." -ForegroundColor Cyan
$CMakeArgs = @(
    "-B", $BuildDir,
    "-G", "Visual Studio 17 2022",
    "-A", "x64",
    "-DLLAMA_BUILD_SERVER=ON",
    "-DBUILD_SHARED_LIBS=OFF"
)

if ($CPUOnly) {
    Write-Host "  Mode: CPU-only (no GPU offload)" -ForegroundColor Yellow
    $CMakeArgs += "-DGGML_CUDA=OFF"
} else {
    Write-Host "  Mode: CUDA enabled" -ForegroundColor Green
    # Note: If this fails with "No CUDA toolset found", install CUDA integration
    # into VS BuildTools via the CUDA installer (custom install -> VS integration)
    $CMakeArgs += "-DGGML_CUDA=ON"
    $CMakeArgs += "-T", "v143,cuda=12.4"
}

& cmake @CMakeArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nCMake configuration FAILED." -ForegroundColor Red
    Write-Host "If CUDA error ('No CUDA toolset found'): install CUDA VS integration." -ForegroundColor Red
    Write-Host "  1. Re-run CUDA installer (e.g. cuda_12.4.x_windows.exe)" -ForegroundColor Red
    Write-Host "  2. Choose Custom install -> CUDA -> Visual Studio Integration" -ForegroundColor Red
    Write-Host "  3. Or manually copy files:" -ForegroundColor Red
    Write-Host "     Copy from: C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.4\extras\visual_studio_integration\MSBuildExtensions\" -ForegroundColor Red
    Write-Host "     Copy to:   C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Microsoft\VC\v170\BuildCustomizations\" -ForegroundColor Red
    Write-Host "  4. Then re-run: .\build_llama_server.ps1" -ForegroundColor Red
    Write-Host "  5. Or build CPU-only now: .\build_llama_server.ps1 -CPUOnly" -ForegroundColor Red
    exit 1
}

# Build
Write-Host "`nBuilding llama-server (this may take 10-30 minutes)..." -ForegroundColor Cyan
& cmake --build $BuildDir --target llama-server --config Release -j 4
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nBuild FAILED." -ForegroundColor Red
    exit 1
}

# Verify
$ExePath = Join-Path $BuildDir "bin\Release\llama-server.exe"
if (Test-Path $ExePath) {
    Write-Host "`nSUCCESS: llama-server built at:" -ForegroundColor Green
    Write-Host "  $ExePath" -ForegroundColor Green
    & $ExePath --version
} else {
    Write-Host "`nBuild reported success but executable not found." -ForegroundColor Yellow
}

Write-Host "`nNext steps:" -ForegroundColor Cyan
Write-Host "  1. Verify MTP flags: llama-server --help | Select-String spec" -ForegroundColor White
Write-Host "  2. Pick 'balanced_mtp' profile when loading an MTP GGUF model" -ForegroundColor White
