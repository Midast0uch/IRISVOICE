@echo off
REM ============================================================================
REM IRIS Voice - Unified Startup Script
REM Launches both the Python backend and Next.js frontend together
REM ============================================================================

title IRIS Voice

echo ============================================
echo    IRIS Voice - Starting Application
echo ============================================
echo.

REM --- Locate project root (where this script lives) ---
cd /d "%~dp0"

REM --- Check for Python 3.12 (GPU version) or fallback to default ---
where py >nul 2>&1
if %errorlevel% equ 0 (
    REM Check if Python 3.12 is available
    py -3.12 --version >nul 2>&1
    if %errorlevel% equ 0 (
        set PYTHON_EXE=py -3.12
        echo [INFO] Using Python 3.12 with CUDA support
    ) else (
        set PYTHON_EXE=python
        echo [INFO] Python 3.12 not found, using default Python
    )
) else (
    set PYTHON_EXE=python
    echo [INFO] py launcher not found, using default Python
)

REM --- Start LFM2.5-VL vision server (optional — skip if model not downloaded) ---
if exist "%~dp0start_vl.bat" (
    echo [1/3] Starting LFM2.5-VL Vision Server (port 8081)...
    start "LFM-VL Vision" cmd /k "cd /d %~dp0 && start_vl.bat"
    timeout /t 5 /nobreak >nul
    echo [INFO] Vision server launched. If model not downloaded, it will exit cleanly.
) else (
    echo [INFO] start_vl.bat not found — skipping vision server
)

REM --- Start the backend server in a new window ---
echo [2/3] Starting IRIS Backend (FastAPI + Uvicorn)...
start "IRIS Backend" cmd /k "cd /d %~dp0 && %PYTHON_EXE% start-backend.py"

REM --- Give the backend a moment to initialize ---
timeout /t 3 /nobreak >nul

REM --- Start the Next.js frontend in this window ---
echo [3/3] Starting IRIS Frontend (Next.js)...
echo.
echo ============================================
echo    Both services are starting up!
echo    Backend:  http://127.0.0.1:8000
echo    Frontend: http://localhost:3000
echo ============================================
echo.

npm run dev
