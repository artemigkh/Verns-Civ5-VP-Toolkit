@echo off
REM run_all.bat -- regenerate every R visualization for the Civ5 VP report.
REM
REM Double-click this file from anywhere, or run:
REM   analysis\r_scripts\run_all.bat
REM Outputs are written to analysis\output\r_plots\.

setlocal EnableDelayedExpansion

REM Resolve repo paths relative to this script.
set "SCRIPT_DIR=%~dp0"
REM Strip trailing backslash.
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
for %%I in ("%SCRIPT_DIR%\..") do set "ANALYSIS_DIR=%%~fI"

REM Locate Rscript: prefer PATH, then fall back to standard install locations.
set "RSCRIPT="
for %%R in (Rscript.exe) do set "RSCRIPT=%%~$PATH:R"

if not defined RSCRIPT (
    if exist "C:\Program Files\R" (
        for /f "delims=" %%D in ('dir /b /ad /o-n "C:\Program Files\R\R-*" 2^>nul') do (
            if not defined RSCRIPT (
                if exist "C:\Program Files\R\%%D\bin\Rscript.exe" (
                    set "RSCRIPT=C:\Program Files\R\%%D\bin\Rscript.exe"
                )
            )
        )
    )
)

if not defined RSCRIPT (
    echo ERROR: Rscript not found. Install R or add it to PATH.
    pause
    exit /b 1
)

echo Using: %RSCRIPT%

REM All scripts assume CWD == analysis\ (so "r_scripts/common.R" and
REM "../data/..." resolve correctly).
pushd "%ANALYSIS_DIR%" || (
    echo ERROR: Could not cd to %ANALYSIS_DIR%
    pause
    exit /b 1
)

set SCRIPTS=01_victory_mix.R 02_winrate_by_civ.R 03_pseudo_dom_victory_mix.R 04_pseudo_dom_winrate_by_civ.R 05_religion_attainment.R 06_pantheon.R 07_founder.R 08_enhancer.R 09_reformation.R 10_religion_sankey.R 11_tech_era_ridgeline.R 12_era_progression.R 13_wonder_ridgeline.R 14_wonders_per_civ_lollipop.R 15_policy_branch_table.R 16_policy_branch_wins_bars.R 16_policy_branch_winrate_bars.R 17_policy_flow_sankey.R 19_vassalage_heatmap.R 20_victory_overview_composite.R 21_policies_overview_composite.R 22_winrate_version_compare.R make_composites.R

for %%S in (%SCRIPTS%) do (
    echo ==^> Rscript r_scripts\%%S
    "%RSCRIPT%" --vanilla "r_scripts\%%S"
    if errorlevel 1 (
        echo Rscript failed for r_scripts\%%S
        popd
        pause
        exit /b 1
    )
)

echo.
echo All R visualizations generated in output\r_plots\
popd
pause
endlocal
