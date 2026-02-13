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

REM --- Activate Python venv if it exists ---
if exist "venv\Scripts\activate.bat" (
    echo [1/3] Activating Python virtual environment...
    call venv\Scripts\activate.bat
) else (
    echo [1/3] No venv found, using system Python
)

REM --- Start the backend server in a new window ---
echo [2/3] Starting IRIS Backend (FastAPI + Uvicorn)...
start "IRIS Backend" cmd /k "cd /d %~dp0 && python start-backend.py"

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
