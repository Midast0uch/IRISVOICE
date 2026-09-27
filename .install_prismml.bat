@echo off
REM Install the freshly built PrismML binaries into the folder the app searches
REM (llama.cpp-prismml\bin), keeping one backup of the previous install, and
REM VERIFY the result before claiming success. Writes .install_done.txt.
REM
REM Hardened 2026-09-27. The old version could not fail: every `copy /y ... >nul`
REM hid its error in a detached console, INSTALL_DONE was written without a
REM check, and it then reported the OLD binary's --version. A build that had
REM finished became an install that silently did nothing while the marker said
REM success. Now:
REM   - it REFUSES to run while llama-server.exe holds the DLLs (INSTALL_BLOCKED)
REM   - every copy is checked, and every file's size is compared afterwards
REM   - the installed binary must report the same --version as the built one
REM   - INSTALL_DONE is written only when all of that passed; otherwise
REM     INSTALL_FAILED, with per-file reasons in .install_done.txt.detail
REM
REM Run by FULL PATH from a detached shell - a bare name does nothing there.
REM   cmd /c C:\dev\IRISVOICE\.install_prismml.bat
REM From ANOTHER batch file, invoke it with `call`: a batch file run without
REM `call` replaces the caller, so this script's `exit /b` ends the whole chain.
set SRC=C:\dev\IRISVOICE\llama.cpp-prismml-src
set DST=C:\dev\IRISVOICE\llama.cpp-prismml
set DSTBIN=%DST%\bin
set SRCBIN=%SRC%\build\bin
set LOG=C:\dev\IRISVOICE\.install_done.txt
REM Every file the app needs from the build. ggml-rpc.dll is deliberately absent:
REM the fresh build does not produce it, so the existing one is left in place.
set FILES=ggml.dll ggml-base.dll ggml-cpu.dll ggml-cuda.dll llama.dll llama-common.dll llama-server.exe llama-server-impl.dll mtmd.dll
set FAILED=0
del /q "%LOG%.detail" 2>nul
del /q "%LOG%.copy" 2>nul

:wait
REM Any failure marker in either log ends the wait. FAILED covers
REM COMPILE_FAILED / CONFIGURE_FAILED / VCVARS_FAILED; _NOT_FOUND covers
REM CL_NOT_FOUND / NINJA_NOT_FOUND.
findstr /c:"FAILED" /c:"_NOT_FOUND" /c:"BINARY_MISSING" "%SRC%\build_compile.log" "%SRC%\build_config.log" >nul 2>&1
if not errorlevel 1 goto failed
findstr /c:"BUILD_DONE" "%SRC%\build_compile.log" >nul 2>&1
if not errorlevel 1 goto built
ping -n 21 127.0.0.1 >nul
goto wait

:built
REM Preflight. These DLLs are the ones the app loads, so while a model server
REM runs every copy fails with a sharing violation - which is the exact silent
REM failure this script used to produce. Refuse loudly: a partial copy is worse
REM than no copy.
tasklist /fi "imagename eq llama-server.exe" 2>nul | findstr /i "llama-server" >nul
if not errorlevel 1 goto locked

REM Keep one backup copy of the previous install.
if exist "%DST%\bin-bak-20260927" rmdir /s /q "%DST%\bin-bak-20260927"
xcopy /s /i /q "%DSTBIN%" "%DST%\bin-bak-20260927\" >nul 2>&1

REM Copy each file and CHECK it. The old version sent every error to >nul.
for %%F in (%FILES%) do (
  copy /y "%SRCBIN%\%%F" "%DSTBIN%\%%F" >> "%LOG%.copy" 2>&1
  if errorlevel 1 (
    echo COPY_FAILED %%F>> "%LOG%.detail"
    set FAILED=1
  )
)

REM Verify sizes - a truncated copy is a copy that reported success.
for %%F in (%FILES%) do (
  for %%A in ("%SRCBIN%\%%F") do (
    for %%B in ("%DSTBIN%\%%F") do (
      if not "%%~zA"=="%%~zB" (
        echo SIZE_MISMATCH %%F src=%%~zA dst=%%~zB>> "%LOG%.detail"
        set FAILED=1
      )
    )
  )
)

REM Verify identity: the installed binary must be the built binary. This catches
REM a stale build, a locked file and a wrong source path in one check.
"%SRCBIN%\llama-server.exe" --version > "%TEMP%\prism_src.txt" 2>&1
"%DSTBIN%\llama-server.exe" --version > "%TEMP%\prism_dst.txt" 2>&1
fc "%TEMP%\prism_src.txt" "%TEMP%\prism_dst.txt" >nul 2>&1
if errorlevel 1 (
  echo VERSION_MISMATCH built and installed binaries disagree>> "%LOG%.detail"
  set FAILED=1
)

if "%FAILED%"=="1" goto install_failed

del /q "%LOG%" 2>nul
echo INSTALL_DONE > "%LOG%"
"%DSTBIN%\llama-server.exe" --version >> "%LOG%" 2>&1
echo verified: every file size matches the build, and the installed --version equals the built one. >> "%LOG%"
exit /b 0

:install_failed
del /q "%LOG%" 2>nul
echo INSTALL_FAILED > "%LOG%"
echo the installed folder was NOT fully updated. Per-file reasons:>> "%LOG%"
type "%LOG%.detail" >> "%LOG%" 2>nul
"%DSTBIN%\llama-server.exe" --version >> "%LOG%" 2>&1
exit /b 1

:locked
del /q "%LOG%" 2>nul
echo INSTALL_BLOCKED > "%LOG%"
echo llama-server.exe is running and holds %DSTBIN%. Nothing was copied.>> "%LOG%"
echo Unload the model first:>> "%LOG%"
echo   curl -X POST http://127.0.0.1:8090/api/models/unload>> "%LOG%"
echo Then run this script again.>> "%LOG%"
exit /b 1

:failed
del /q "%LOG%" 2>nul
echo BUILD_FAILED > "%LOG%"
echo the build reported a failure, so nothing was installed. See>> "%LOG%"
echo   %SRC%\build_compile.log and build_config.log>> "%LOG%"
exit /b 1
