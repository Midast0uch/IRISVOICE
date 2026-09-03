@echo off
echo Cleaning up Node processes and lock files...
taskkill /F /IM node.exe 2>nul
if exist "dist\dev\lock" del "dist\dev\lock"
echo.
echo Clearing Next.js cache...
if exist "dist" rmdir /s /q "dist"
if exist ".next" rmdir /s /q ".next"
echo.
echo Installing dependencies...
npm install
echo.
echo Starting IRIS Widget...
npm run dev:tauri
