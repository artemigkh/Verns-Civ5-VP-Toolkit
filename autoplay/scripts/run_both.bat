@echo off
REM =====================================================================
REM  Civ5 VP Autoplay — launch hypervisor and runner in two side-by-side
REM  console windows. Each window stays open after the process exits so
REM  logs remain visible. Close either window to kill that service.
REM =====================================================================
setlocal

set "RC=0"
set "SCRIPT_DIR=%~dp0"

REM `start "<title>" /D <cwd> cmd /K <cmd>` opens a new console window.
REM Using /K keeps it open after the process exits so you can read logs.
start "autoplay-hypervisor" cmd /K "%SCRIPT_DIR%run_hypervisor.bat"
if errorlevel 1 (
    echo ERROR: failed to start hypervisor window.
    set "RC=1"
    goto :end
)

REM Small delay so the hypervisor is listening before the runner tries to register.
timeout /T 15 /NOBREAK >nul

start "autoplay-runner" cmd /K "%SCRIPT_DIR%run_runner.bat"
if errorlevel 1 (
    echo ERROR: failed to start runner window.
    set "RC=1"
    goto :end
)

:end
echo.
if not "%RC%"=="0" (
    echo === run_both failed with exit code %RC% ===
) else (
    echo Launched hypervisor and runner in separate windows.
)
if /i not "%~1"=="--no-pause" (
    echo Press any key to close this launcher window...
    pause >nul
)
endlocal & exit /b %RC%
