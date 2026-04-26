@echo off
REM ============================================================================
REM LFM2.5-VL Vision Server — Windows Startup
REM Starts llama-server with LFM2.5-VL-1.6B on port 8081
REM
REM REQUIREMENTS:
REM   1. llama-server.exe installed (cmake build with LLAMA_AVX2=ON)
REM   2. LFM2.5-VL-1.6B-Q4_0.gguf downloaded to %USERPROFILE%\models\LFM2.5-VL-1.6B\
REM   3. mmproj-LFM2.5-VL-1.6B-Q4_0.gguf downloaded to same directory (CRITICAL)
REM
REM Without the mmproj file, the server starts but returns blank on all images.
REM
REM Download models:
REM   python -c "from huggingface_hub import hf_hub_download; import os; base=os.path.expanduser('~/models/LFM2.5-VL-1.6B/'); os.makedirs(base,exist_ok=True); hf_hub_download('LiquidAI/LFM2.5-VL-1.6B-GGUF','LFM2.5-VL-1.6B-Q4_0.gguf',local_dir=base); hf_hub_download('LiquidAI/LFM2.5-VL-1.6B-GGUF','mmproj-LFM2.5-VL-1.6B-Q4_0.gguf',local_dir=base)"
REM ============================================================================

set MODEL=%USERPROFILE%\models\LFM2.5-VL-1.6B\LFM2.5-VL-1.6B-Q4_0.gguf
set MMPROJ=%USERPROFILE%\models\LFM2.5-VL-1.6B\mmproj-LFM2.5-VL-1.6B-Q4_0.gguf

echo ============================================
echo  LFM2.5-VL Vision Server
echo  Port: 8081
echo  Model: %MODEL%
echo ============================================

REM Verify model files exist
if not exist "%MODEL%" (
    echo [ERROR] Model file not found: %MODEL%
    echo Run the download command above to get the model files.
    pause
    exit /b 1
)

if not exist "%MMPROJ%" (
    echo [ERROR] mmproj file not found: %MMPROJ%
    echo This file is REQUIRED. Without it, vision returns blank.
    echo Run the download command above to get the model files.
    pause
    exit /b 1
)

echo [INFO] Starting llama-server on port 8081...
llama-server.exe ^
  --model "%MODEL%" ^
  --mmproj "%MMPROJ%" ^
  --port 8081 ^
  --host 127.0.0.1 ^
  --n-gpu-layers 1 ^
  --ctx-size 4096 ^
  --image-max-tokens 256

REM If llama-server.exe is not in PATH, try common install locations:
REM set PATH=%PATH%;C:\Program Files\llama.cpp\bin
