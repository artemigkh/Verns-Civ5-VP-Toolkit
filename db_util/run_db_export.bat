@echo off
setlocal enabledelayedexpansion

REM =====================================================================
REM  Civ5 VP DB export launcher (double-click friendly)
REM
REM  What this does:
REM    1. Resolves repo root from this script location.
REM    2. Ensures uv is available.
REM    3. Runs `uv sync`.
REM    4. Runs db_util\db_export.py.
REM
REM  Optional environment overrides:
REM    DB_EXPORT_CIV5_CACHE_DIR   (default: %USERPROFILE%\Documents\My Games\Sid Meier's Civilization 5\cache)
REM    DB_EXPORT_OUTPUT_DIR       (default: <repo>\db_util\out)
REM =====================================================================

set "RC=0"
set "SCRIPT_DIR=%~dp0"
set "NO_PAUSE=0"
set "SCRIPT_ARGS="

:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--no-pause" (
    set "NO_PAUSE=1"
) else (
    set "SCRIPT_ARGS=!SCRIPT_ARGS! "%~1""
)
shift
goto :parse_args

:args_done

pushd "%SCRIPT_DIR%.." >nul
set "REPO_ROOT=%CD%"

echo [run_db_export] Working directory: %REPO_ROOT%

if "%DB_EXPORT_CIV5_CACHE_DIR%"=="" set "DB_EXPORT_CIV5_CACHE_DIR=%USERPROFILE%\Documents\My Games\Sid Meier's Civilization 5\cache"
if "%DB_EXPORT_OUTPUT_DIR%"=="" set "DB_EXPORT_OUTPUT_DIR=%REPO_ROOT%\db_util\out"

set "PYTHONUNBUFFERED=1"

where uv >nul 2>&1
if errorlevel 1 (
    set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\uv\bin;%APPDATA%\Python\Python312\Scripts;%APPDATA%\Python\Python311\Scripts;%PATH%"
    where uv >nul 2>&1
    if errorlevel 1 (
        echo [run_db_export] uv not found. Installing via official installer...
        powershell -ExecutionPolicy ByPass -NoProfile -Command ^
            "irm https://astral.sh/uv/install.ps1 | iex"
        if errorlevel 1 (
            echo [run_db_export] uv installation failed.
            set "RC=1"
            goto :end
        )

        set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\uv\bin;%APPDATA%\Python\Python312\Scripts;%APPDATA%\Python\Python311\Scripts;%PATH%"
        where uv >nul 2>&1
        if errorlevel 1 (
            echo [run_db_export] uv is still not on PATH. Open a new terminal and retry.
            set "RC=1"
            goto :end
        )
    )
)

echo [run_db_export] Syncing dependencies via uv...
uv sync
if errorlevel 1 (
    echo [run_db_export] uv sync failed.
    set "RC=1"
    goto :end
)

echo [run_db_export] Civ5 cache: %DB_EXPORT_CIV5_CACHE_DIR%
echo [run_db_export] Output dir: %DB_EXPORT_OUTPUT_DIR%

if not defined SCRIPT_ARGS (
    uv run python db_util\db_export.py --civ5-cache-dir "%DB_EXPORT_CIV5_CACHE_DIR%" --output-dir "%DB_EXPORT_OUTPUT_DIR%"
) else (
    uv run python db_util\db_export.py !SCRIPT_ARGS!
)
set "RC=%ERRORLEVEL%"

:end
popd >nul
echo.
if not "%RC%"=="0" (
    echo === run_db_export exited with code %RC% ===
)
if "%NO_PAUSE%"=="0" (
    echo Press any key to close...
    pause >nul
)
endlocal & exit /b %RC%
