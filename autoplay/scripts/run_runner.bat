@echo off
REM =====================================================================
REM  Civ5 VP Autoplay Runner launcher
REM
REM  All configuration is passed to Python via AUTOPLAY_RUNNER_* environment
REM  variables. Edit the values below to tune each knob.
REM =====================================================================
setlocal

REM --- cd to repo root (two levels up from this script) ----------------
pushd "%~dp0..\.."

REM --- Runner configuration (env vars consumed by RunnerConfig) --------
set "AUTOPLAY_RUNNER_HYPERVISOR_URL=http://localhost:5000"
set "AUTOPLAY_RUNNER_USER_DIR=%USERPROFILE%\Documents\My Games\Sid Meier's Civilization 5"
set "AUTOPLAY_RUNNER_INSTALL_DIR=%USERPROFILE%\Desktop\pure_vp\Sid Meier's Civilization V"
set "AUTOPLAY_RUNNER_STARTUP_TIMEOUT_SEC=600"
set "AUTOPLAY_RUNNER_TURN_TIMEOUT_SEC=600"
set "AUTOPLAY_RUNNER_REGISTRATION_TIMEOUT_SEC=180"
set "AUTOPLAY_RUNNER_HEARTBEAT_INTERVAL_SEC=2"
REM  List values must be valid JSON arrays for pydantic-settings to parse them.
REM  NOTE: No outer quotes on this `set` so inner double-quotes remain literal.
set AUTOPLAY_RUNNER_LOG_IGNORE_PATTERNS=["CitySites_*","TradePlayerRouteLog_*"]
REM  When 1/true, install patched_files/d3d9.dll over <INSTALL_DIR>/d3d9.dll on
REM  startup. When 0/false (default), any existing d3d9.dll there is removed.
set "AUTOPLAY_RUNNER_USE_BLANK_D3D9_PROXY=true"

REM --- Force unbuffered Python stdio so log lines stream to the console ---
set "PYTHONUNBUFFERED=1"

REM --- Ensure uv is on PATH (fallback to pip --user install location) --
where uv >nul 2>&1 || set "PATH=%APPDATA%\Python\Python311\Scripts;%APPDATA%\Python\Python312\Scripts;%PATH%"

echo [run_runner] Syncing dependencies via uv...
uv sync || (echo uv sync failed & set "ERR=1" & goto :end)

echo [run_runner] HYPERVISOR_URL=%AUTOPLAY_RUNNER_HYPERVISOR_URL%
echo [run_runner] INSTALL_DIR=%AUTOPLAY_RUNNER_INSTALL_DIR%
uv run python -u -m autoplay.runner
set ERR=%ERRORLEVEL%

:end
popd
echo.
if not "%ERR%"=="0" (
    echo === run_runner exited with code %ERR% ===
)
if /i not "%~1"=="--no-pause" (
    echo Press any key to close...
    pause >nul
)
endlocal & exit /b %ERR%
