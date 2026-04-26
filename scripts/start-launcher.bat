@echo off
:: Starts the iris-launcher Vite dev server.
:: Port is passed via PORT env variable by the preview harness,
:: or defaults to 5174 if run directly.
cd /d "C:\Users\midas\Desktop\dev\iris-launcher"
if "%PORT%"=="" set PORT=5174
"C:\Users\midas\.bun\bin\bun.exe" x vite --port %PORT%
