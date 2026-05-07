@echo off
REM =====================================================================
REM  Civ5 VP Autoplay Hypervisor launcher
REM
REM  All configuration is passed to Python via AUTOPLAY_HV_* environment
REM  variables. Edit the values below to tune each knob.
REM =====================================================================
setlocal

REM --- cd to repo root (two levels up from this script) ----------------
pushd "%~dp0..\.."

REM --- Hypervisor configuration (env vars consumed by HypervisorConfig) -
set "AUTOPLAY_HV_STORAGE_ROOT=%CD%\data"
set "AUTOPLAY_HV_HOST=0.0.0.0"
set "AUTOPLAY_HV_PORT=5000"
set "AUTOPLAY_HV_RUNNER_TIMEOUT_SEC=120"

if not exist "%AUTOPLAY_HV_STORAGE_ROOT%" mkdir "%AUTOPLAY_HV_STORAGE_ROOT%"

REM --- Force unbuffered Python stdio so log lines stream to the console ---
set "PYTHONUNBUFFERED=1"

REM --- Ensure uv is on PATH (fallback to pip --user install location) --
where uv >nul 2>&1 || set "PATH=%APPDATA%\Python\Python311\Scripts;%APPDATA%\Python\Python312\Scripts;%PATH%"

echo [run_hypervisor] Syncing dependencies via uv...
uv sync || (echo uv sync failed & set "ERR=1" & goto :end)

echo [run_hypervisor] STORAGE_ROOT=%AUTOPLAY_HV_STORAGE_ROOT%
echo [run_hypervisor] Listening on %AUTOPLAY_HV_HOST%:%AUTOPLAY_HV_PORT%
uv run python -u -m autoplay.hypervisor
set ERR=%ERRORLEVEL%

:end
popd
echo.
if not "%ERR%"=="0" (
    echo === run_hypervisor exited with code %ERR% ===
)
if /i not "%~1"=="--no-pause" (
    echo Press any key to close...
    pause >nul
)
endlocal & exit /b %ERR%
