@echo off
REM =====================================================================
REM  Civ5 VP Autoplay Runner — fresh-machine setup
REM
REM  This script bootstraps a brand-new Windows machine to act as a
REM  runner. It:
REM    1. Installs the `uv` Python package manager (via the official
REM       PowerShell installer) if it isn't already on PATH.
REM    2. Pre-installs the pinned Python interpreter (3.12) via uv.
REM    3. Runs `uv sync` to install all locked project dependencies into
REM       a project-local virtual environment.
REM
REM  After this script completes successfully you can launch the runner
REM  with `autoplay\scripts\run_runner.bat`.
REM =====================================================================
setlocal enabledelayedexpansion

set "RC=0"

REM --- cd to repo root (two levels up from this script) ----------------
pushd "%~dp0..\.."

echo [setup_runner] Working directory: %CD%

REM --- 1) Install uv if missing ---------------------------------------
where uv >nul 2>&1
if errorlevel 1 (
    echo [setup_runner] uv not found on PATH; installing via official installer...
    powershell -ExecutionPolicy ByPass -NoProfile -Command ^
        "irm https://astral.sh/uv/install.ps1 | iex"
    if errorlevel 1 (
        echo [setup_runner] uv install script failed.
        set "RC=1"
        goto :end
    )

    REM uv installs into %USERPROFILE%\.local\bin or similar — make it visible
    REM for the rest of this script (a new shell will pick it up automatically).
    set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\uv\bin;%APPDATA%\Python\Python312\Scripts;%PATH%"

    where uv >nul 2>&1
    if errorlevel 1 (
        echo [setup_runner] uv still not found after install. You may need to
        echo                 open a new shell so PATH updates take effect.
        set "RC=1"
        goto :end
    )
) else (
    echo [setup_runner] uv already installed.
)

uv --version

REM --- 2) Install the pinned Python interpreter -----------------------
echo [setup_runner] Installing CPython 3.12 via uv...
uv python install 3.12 || (
    echo [setup_runner] uv python install failed.
    set "RC=1"
    goto :end
)

REM --- 3) Sync project dependencies into a venv -----------------------
echo [setup_runner] Installing project dependencies (uv sync)...
uv sync || (
    echo [setup_runner] uv sync failed.
    set "RC=1"
    goto :end
)

echo.
echo [setup_runner] Setup complete. Next steps:
echo   * Place the Civ5 VP install at the path referenced by AUTOPLAY_RUNNER_INSTALL_DIR
echo     (default: %%USERPROFILE%%\Desktop\pure_vp\Sid Meier's Civilization V).
echo   * Set AUTOPLAY_RUNNER_HYPERVISOR_URL in autoplay\scripts\run_runner.bat
echo     to the LAN address of your hypervisor.
echo   * Launch the runner with: autoplay\scripts\run_runner.bat
echo.

:end
popd
echo.
if not "%RC%"=="0" (
    echo === setup_runner failed with exit code %RC% ===
)
if /i not "%~1"=="--no-pause" (
    echo Press any key to close...
    pause >nul
)
endlocal & exit /b %RC%
