@echo off
REM =====================================================================
REM  Civ5 VP Autoplay Headless Bridge launcher
REM
REM  Plays games in civ5-headless (c5h queue) and reports each worker slot
REM  to the hypervisor as a runner; finished games' stats.db go to its
REM  DuckDB. All configuration is passed via AUTOPLAY_HEADLESS_* variables.
REM  Pass --autostart to start playing without pressing Start in the webapp.
REM =====================================================================
setlocal

REM --- cd to repo root (two levels up from this script) ----------------
pushd "%~dp0..\.."

REM --- Bridge configuration (env vars consumed by HeadlessConfig) ------
set "AUTOPLAY_HEADLESS_HYPERVISOR_URL=http://localhost:5000"
REM  civ5-headless checkout; its civ5headless.toml selects the pinned game
REM  database (the modpack) the games play.
set "AUTOPLAY_HEADLESS_C5H_DIR=%USERPROFILE%\Documents\civ5-headless"
REM  The games play on the bridge's own copy of the game folder with this
REM  modpack (headless_data\game\<folder>), made from the Steam install the
REM  first time, so Steam's Assets\DLC\<folder> can be removed afterwards.
set "AUTOPLAY_HEADLESS_MODPACK_FOLDER=VP_MODPACK_5_4_8_NEUTRALS"
set "AUTOPLAY_HEADLESS_SPEC=%AUTOPLAY_HEADLESS_C5H_DIR%\pinned\specs\communitu-standard.json"
REM  Name the games are ingested under on the hypervisor (MP_AUTOPLAY_VP_*).
set "AUTOPLAY_HEADLESS_MODPACK=MP_AUTOPLAY_VP_5_4_8_NEUTRALS_headless"
set "AUTOPLAY_HEADLESS_WORK_DIR=%CD%\headless_data"
REM  Games at once (unpinned: Windows places each one-thread game), games per
REM  queue file, and the turn each game plays to unless --max-turn caps it.
set "AUTOPLAY_HEADLESS_WORKERS=24"
set "AUTOPLAY_HEADLESS_AFFINITY=none"
set "AUTOPLAY_HEADLESS_GAMES_PER_BATCH=1000"
set "AUTOPLAY_HEADLESS_TURNS=500"
set "AUTOPLAY_HEADLESS_CONTINUOUS=true"
REM  Queue defaults for every game (c5h run options by JSON name). No outer
REM  quotes on this `set` so inner double-quotes remain literal.
set AUTOPLAY_HEADLESS_JOB_DEFAULTS={"noMods": true, "detail": "summary", "maxSeconds": 14400, "stallSeconds": 900}
set "AUTOPLAY_HEADLESS_HEARTBEAT_INTERVAL_SEC=2"

REM --- Force unbuffered Python stdio so log lines stream to the console ---
set "PYTHONUNBUFFERED=1"

REM --- Ensure uv is on PATH (fallback to pip --user install location) --
where uv >nul 2>&1 || set "PATH=%APPDATA%\Python\Python311\Scripts;%APPDATA%\Python\Python312\Scripts;%PATH%"

echo [run_headless] Syncing dependencies via uv...
uv sync || (echo uv sync failed & set "ERR=1" & goto :end)

echo [run_headless] HYPERVISOR_URL=%AUTOPLAY_HEADLESS_HYPERVISOR_URL%
echo [run_headless] C5H_DIR=%AUTOPLAY_HEADLESS_C5H_DIR%
echo [run_headless] MODPACK=%AUTOPLAY_HEADLESS_MODPACK% (%AUTOPLAY_HEADLESS_MODPACK_FOLDER%) WORKERS=%AUTOPLAY_HEADLESS_WORKERS%
uv run python -u -m autoplay.headless %*
set ERR=%ERRORLEVEL%

:end
popd
echo.
if not "%ERR%"=="0" (
    echo === run_headless exited with code %ERR% ===
)
if /i not "%~1"=="--no-pause" (
    echo Press any key to close...
    pause >nul
)
endlocal & exit /b %ERR%
