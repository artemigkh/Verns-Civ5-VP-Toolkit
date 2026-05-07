@echo off
REM run_R.bat -- drag-and-drop launcher for a single R script.
REM
REM Usage:
REM   1. Drag an .R file from File Explorer onto this .bat file.
REM   2. Or run from a terminal: run_R.bat path\to\script.R
REM
REM The script is run with CWD = analysis\ so paths like
REM "r_scripts/common.R" and "../data/..." resolve correctly.
REM Output PNGs land under analysis\output\r_plots\.

setlocal EnableDelayedExpansion

REM Resolve repo paths relative to this script.
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
for %%I in ("%SCRIPT_DIR%\..") do set "ANALYSIS_DIR=%%~fI"

if "%~1"=="" (
    echo ERROR: No file provided.
    echo.
    echo Drag an .R file onto this .bat file, or run:
    echo     run_R.bat path\to\script.R
    pause
    exit /b 1
)

set "TARGET=%~f1"

if not exist "%TARGET%" (
    echo ERROR: File not found: %TARGET%
    pause
    exit /b 1
)

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

echo Using:  %RSCRIPT%
echo Script: %TARGET%
echo CWD:    %ANALYSIS_DIR%
echo.

pushd "%ANALYSIS_DIR%" || (
    echo ERROR: Could not cd to %ANALYSIS_DIR%
    pause
    exit /b 1
)

"%RSCRIPT%" --vanilla "%TARGET%"
set "RC=%ERRORLEVEL%"

popd

echo.
if "%RC%"=="0" (
    echo Done. Outputs are in analysis\output\r_plots\
) else (
    echo Rscript exited with code %RC%.
)
pause
endlocal
exit /b %RC%
