# One-command build for the Iris native audio C++ extension.
# Run from the repo root (where this script lives).
$ErrorActionPreference = "Stop"

$RepoRoot = $PSScriptRoot
if (-not $RepoRoot) { $RepoRoot = (Get-Location).Path }
$NativeDir = Join-Path $RepoRoot "backend/native"
$BuildDir = Join-Path $NativeDir "build"

Write-Host "=== Iris Native Audio Build ===" -ForegroundColor Cyan

# 1. Ensure build deps
$py = Join-Path $RepoRoot "venv/Scripts/python.exe"
if (-not (Test-Path $py)) { $py = "python" }
& $py -m pip install pybind11 numpy --quiet

# 2. Get sounddevice path and copy PortAudio binaries
$sdDir = & $py -c 'import sounddevice as sd, os; print(os.path.dirname(sd.__file__))'
$paHeaderDst = Join-Path $NativeDir "portaudio_include"
$paLibDst = Join-Path $NativeDir "portaudio_lib"

if (-not (Test-Path $paHeaderDst)) { New-Item -ItemType Directory -Path $paHeaderDst -Force | Out-Null }
if (-not (Test-Path $paLibDst)) { New-Item -ItemType Directory -Path $paLibDst -Force | Out-Null }

# Copy DLLs from sounddevice
$dllSrc = Join-Path $sdDir "_sounddevice_data/portaudio-binaries"
if (Test-Path $dllSrc) {
    Copy-Item (Join-Path $dllSrc "*.dll") $paLibDst -Force -ErrorAction SilentlyContinue
    # Also copy to native dir so .pyd finds it at runtime
    Copy-Item (Join-Path $dllSrc "*.dll") $NativeDir -Force -ErrorAction SilentlyContinue
}

# 3. Download PortAudio headers if missing
$paHeader = Join-Path $paHeaderDst "portaudio.h"
if (-not (Test-Path $paHeader)) {
    Write-Host "Downloading PortAudio headers..." -ForegroundColor Yellow
    $tmpTgz = Join-Path $env:TEMP "pa_stable.tgz"
    $tmpDir = Join-Path $env:TEMP "portaudio_extract"
    try {
        Invoke-WebRequest -Uri "http://www.portaudio.com/archives/pa_stable_v190700_20210406.tgz" -OutFile $tmpTgz -TimeoutSec 30
        if (-not (Test-Path $tmpDir)) { New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null }
        & tar -xzf $tmpTgz -C $tmpDir
        $found = Get-ChildItem -Path $tmpDir -Recurse -Filter "portaudio.h" | Select-Object -First 1
        if ($found) {
            $incDir = Join-Path $found.DirectoryName "../include"
            if (Test-Path $incDir) {
                Copy-Item (Join-Path $incDir "*.h") $paHeaderDst -Force
            } else {
                Copy-Item $found.FullName $paHeaderDst -Force
            }
            Write-Host "Headers extracted OK" -ForegroundColor Green
        }
    } catch {
        Write-Host "Header download failed, will use CMake FetchContent fallback" -ForegroundColor Yellow
    }
}

# 4. Configure via CMake
if (-not (Test-Path $BuildDir)) { New-Item -ItemType Directory -Path $BuildDir -Force | Out-Null }

$vsGenerator = "Visual Studio 17 2022"
$arch = "x64"

Write-Host "Configuring CMake..." -ForegroundColor Green
& cmake -S $NativeDir -B $BuildDir -G "$vsGenerator" -A $arch -DCMAKE_BUILD_TYPE=Release -DPython_EXECUTABLE="$py"

# 5. Build
Write-Host "Building..." -ForegroundColor Green
& cmake --build $BuildDir --config Release

# 6. Copy .pyd into backend/native/
$pyd = Get-ChildItem -Path $BuildDir -Recurse -Filter "iris_audio*.pyd" | Select-Object -First 1
if ($pyd) {
    Copy-Item $pyd.FullName $NativeDir -Force
    Write-Host "SUCCESS: $($pyd.Name) copied to backend/native/" -ForegroundColor Green
} else {
    Write-Host "ERROR: .pyd not found after build." -ForegroundColor Red
    exit 1
}

Write-Host "=== Build complete ===" -ForegroundColor Cyan
