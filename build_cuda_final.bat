@echo off
call "C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat"
set PATH=C:\Users\midas\AppData\Roaming\Python\Python313\scripts;%PATH%
cd /d C:\Users\midas\Desktop\IRISVOICE\llama.cpp
if exist build rmdir /s /q build
cmake -B build -S . -G "Visual Studio 17 2022" -A x64 -DGGML_CUDA=ON -DLLAMA_BUILD_SERVER=ON -DCMAKE_CUDA_FLAGS="-allow-unsupported-compiler" > build_config.txt 2>&1
if %ERRORLEVEL% neq 0 (
    echo CMAKE_FAILED
    exit /b 1
)
echo CMAKE_OK
cmake --build build --config Release --target llama-server --parallel 8 > build_output.txt 2>&1
if %ERRORLEVEL% neq 0 (
    echo BUILD_FAILED
    exit /b 1
)
echo BUILD_OK
dir build\bin\Release\llama-server.exe
