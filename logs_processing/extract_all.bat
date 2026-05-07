@echo off
setlocal EnableDelayedExpansion

REM Extract every tar file in data\<MODPACK_VER>\complete into separate
REM per-bundle folders under data\<MODPACK_VER>\unpacked\all. Bundles whose
REM destination folder already exists are skipped.

if "%MODPACK_VER%"=="" set "MODPACK_VER=MP_AUTOPLAY_VP_5_2_3"

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%.." >nul
set "REPO_ROOT=%CD%"
popd >nul

set "SRC_DIR=%REPO_ROOT%\data\%MODPACK_VER%\complete"
set "DST_DIR=%REPO_ROOT%\data\%MODPACK_VER%\unpacked\all"

set "RC=0"

if not exist "%SRC_DIR%" (
    echo ERROR: Source directory not found: %SRC_DIR%
    set "RC=1"
    goto :end
)

if not exist "%DST_DIR%" mkdir "%DST_DIR%"

echo Modpack:  %MODPACK_VER%
echo Source:   %SRC_DIR%
echo Target:   %DST_DIR%
echo.

set /a TOTAL=0
set /a EXTRACTED=0
set /a SKIPPED=0

for /f "delims=" %%F in ('dir /b /a-d /o:n "%SRC_DIR%\*.tar"') do (
    set /a TOTAL+=1
    set "TARNAME=%%~nF"
    set "OUT=%DST_DIR%\!TARNAME!"
    if exist "!OUT!" (
        set /a SKIPPED+=1
        echo [!TOTAL!] SKIP   !TARNAME!
    ) else (
        echo [!TOTAL!] UNPACK !TARNAME!
        mkdir "!OUT!"
        tar -xf "%SRC_DIR%\%%F" -C "!OUT!"
        if errorlevel 1 (
            echo   ERROR: tar failed for %%F
            set "RC=1"
            goto :end
        )
        set /a EXTRACTED+=1
    )
)

echo.
echo Done. Total=!TOTAL!  Extracted=!EXTRACTED!  Skipped=!SKIPPED!
echo Output: %DST_DIR%

:end
echo.
if /i not "%~1"=="--no-pause" (
    if "%RC%"=="0" (
        echo Press any key to close...
    ) else (
        echo Script failed with exit code %RC%. Press any key to close...
    )
    pause >nul
)
endlocal & exit /b %RC%
