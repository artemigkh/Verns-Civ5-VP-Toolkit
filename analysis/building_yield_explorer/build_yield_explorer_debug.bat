@echo off
REM =====================================================================
REM  Building Yield Explorer — debug build
REM
REM  Aggregates the stats DB and renders a single self-contained
REM  index.html (GitHub-Pages ready) into PUBLISH_DIR.
REM
REM  All configuration is passed to Python via the env vars below.
REM =====================================================================
setlocal

REM --- cd to repo root (two levels up from this script) ----------------
pushd "%~dp0..\.."

REM --- Configuration (consumed by building_yield_explorer.config) ------
set "DB_TYPE=sqlite"
set "DB_PATH=misc/building_yields/stats.db"
set "INTERMEDIATE_DATA_DIR=misc/building_yields/cache"
set "PUBLISH_DIR=misc/building_yields/public"

set "PYTHONUNBUFFERED=1"

REM --- Ensure uv is on PATH (fallback to pip --user install location) --
where uv >nul 2>&1 || set "PATH=%APPDATA%\Python\Python311\Scripts;%APPDATA%\Python\Python312\Scripts;%PATH%"

echo [build_yield_explorer] Syncing dependencies via uv...
uv sync --project analysis/building_yield_explorer || (echo uv sync failed & set "ERR=1" & goto :end)

echo [build_yield_explorer] DB_PATH=%DB_PATH%
echo [build_yield_explorer] PUBLISH_DIR=%PUBLISH_DIR%
uv run --project analysis/building_yield_explorer python -u -m building_yield_explorer %*
set ERR=%ERRORLEVEL%

if "%ERR%"=="0" (
    echo [build_yield_explorer] Opening %PUBLISH_DIR%\index.html ...
    start "" "%CD%\misc\building_yields\public\index.html"
)

:end
popd
echo.
if not "%ERR%"=="0" (
    echo === build_yield_explorer exited with code %ERR% ===
)
if /i not "%~1"=="--no-pause" (
    echo Press any key to close...
    pause >nul
)
endlocal & exit /b %ERR%
