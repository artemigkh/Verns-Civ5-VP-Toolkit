@echo off
REM =====================================================================
REM  Civ5 VP Autoplay — launch hypervisor and runner in two side-by-side
REM  console windows. Each window stays open after the process exits so
REM  logs remain visible. Close either window to kill that service.
REM =====================================================================
setlocal

set "SCRIPT_DIR=%~dp0"

REM `start "<title>" /D <cwd> cmd /K <cmd>` opens a new console window.
REM Using /K keeps it open after the process exits so you can read logs.
start "autoplay-hypervisor" cmd /K "%SCRIPT_DIR%run_hypervisor.bat"

REM Small delay so the hypervisor is listening before the runner tries to register.
timeout /T 15 /NOBREAK >nul

start "autoplay-runner" cmd /K "%SCRIPT_DIR%run_runner.bat"

endlocal
