@echo off
REM =====================================================================
REM  Plotly Explorer - GitHub Pages deploy build
REM
REM  Aggregates the stats DB and renders a single self-contained
REM  index.html into the repo-level docs folder for GitHub Pages.
REM
REM  All configuration is passed to Python via the env vars below.
REM =====================================================================
setlocal

REM --- cd to repo root (two levels up from this script) ----------------
pushd "%~dp0..\.."

REM --- Configuration (consumed by plotly_explorer.config) -------------
set "DB_TYPE=duckdb"
set "DB_PATH=data/MP_AUTOPLAY_VP_SQLITE_STATS_DEV/stats.duckdb"
set "INTERMEDIATE_DATA_DIR=data/MP_AUTOPLAY_VP_SQLITE_STATS_DEV/plotly_explorer_cache"
set "PUBLISH_DIR=docs"

set "PYTHONUNBUFFERED=1"

set "NOPAUSE=0"
set "PY_ARGS="

:collect_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--no-pause" (
    set "NOPAUSE=1"
) else (
    set "PY_ARGS=%PY_ARGS% %~1"
)
shift
goto :collect_args

:args_done

if not exist "%CD%\docs" mkdir "%CD%\docs"

REM --- Ensure uv is on PATH (fallback to pip --user install location) --
where uv >nul 2>&1 || set "PATH=%APPDATA%\Python\Python311\Scripts;%APPDATA%\Python\Python312\Scripts;%PATH%"

echo [plotly_explorer] Syncing dependencies via uv...
uv sync --project analysis/plotly_explorer || (echo uv sync failed & set "ERR=1" & goto :end)

echo [plotly_explorer] DB_PATH=%DB_PATH%
echo [plotly_explorer] PUBLISH_DIR=%PUBLISH_DIR%
uv run --project analysis/plotly_explorer python -u -m plotly_explorer --patch 5.3.3 --difficulty Emperor --mapscript "Communitu 3.2.0" --size "Standard"%PY_ARGS%
set ERR=%ERRORLEVEL%

if "%ERR%"=="0" (
    echo [plotly_explorer] Opening %PUBLISH_DIR%\index.html ...
    start "" "%CD%\docs\index.html"
)

:end
popd
echo.
if not "%ERR%"=="0" (
    echo === plotly_explorer exited with code %ERR% ===
)
if "%NOPAUSE%"=="0" (
    echo Press any key to close...
    pause >nul
)
endlocal & exit /b %ERR%
