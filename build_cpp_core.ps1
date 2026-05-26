# Build script for IRIS C++ Hybrid Core Memory Engine
# Run from repo root.
$ErrorActionPreference = "Stop"

$RepoRoot = $PSScriptRoot
if (-not $RepoRoot) { $RepoRoot = (Get-Location).Path }
$CoreDir = Join-Path $RepoRoot "src-tauri/src/iris_core"
$BuildDir = Join-Path $CoreDir "build"
$CMakeExe = "C:\Program Files\CMake\bin\cmake.exe"

Write-Host "=== IRIS C++ Core Build ===" -ForegroundColor Cyan

# 1. Ensure build deps
$py = Join-Path $RepoRoot "venv/Scripts/python.exe"
if (-not (Test-Path $py)) { $py = "python" }

# 2. Configure via CMake
if (-not (Test-Path $BuildDir)) { New-Item -ItemType Directory -Path $BuildDir -Force | Out-Null }

$vsGenerator = "Visual Studio 17 2022"
$arch = "x64"

Write-Host "Configuring CMake..." -ForegroundColor Green
& $CMakeExe -S $CoreDir -B $BuildDir -G "$vsGenerator" -A $arch -DCMAKE_BUILD_TYPE=Release

if ($LASTEXITCODE -ne 0) {
    Write-Host "CMake configuration failed. Trying fallback (plain SQLite3)..." -ForegroundColor Yellow
    # Retry with explicit SQLite3 paths from Python
    $pyInc = & $py -c "import sysconfig; print(sysconfig.get_path('include'))"
    $pyLib = & $py -c "import sysconfig; print(sysconfig.get_config_var('LIBDIR'))"
    & $CMakeExe -S $CoreDir -B $BuildDir -G "$vsGenerator" -A $arch `
        -DCMAKE_BUILD_TYPE=Release `
        -DSQLITE3_LIBRARY="$pyLib/sqlite3.lib" `
        -DSQLITE3_INCLUDE_DIR="$pyInc"
}

# 3. Build
Write-Host "Building..." -ForegroundColor Green
& $CMakeExe --build $BuildDir --config Release

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Build failed." -ForegroundColor Red
    exit 1
}

# 4. Verify DLL exists
$dll = Get-ChildItem -Path $BuildDir -Recurse -Filter "iris_core.dll" | Select-Object -First 1
if ($dll) {
    Write-Host "SUCCESS: $($dll.Name) built at $($dll.FullName)" -ForegroundColor Green
} else {
    Write-Host "ERROR: iris_core.dll not found after build." -ForegroundColor Red
    exit 1
}

# 5. Check backend/native/ copy
$nativeDir = Join-Path $RepoRoot "backend/native"
$nativeDll = Join-Path $nativeDir "iris_core.dll"
if (Test-Path $nativeDll) {
    Write-Host "SUCCESS: DLL copied to backend/native/iris_core.dll" -ForegroundColor Green
} else {
    Write-Host "WARNING: DLL not copied to backend/native/. Manual copy may be needed." -ForegroundColor Yellow
}

Write-Host "=== Build complete ===" -ForegroundColor Cyan
