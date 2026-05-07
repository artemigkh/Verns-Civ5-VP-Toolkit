@echo off
setlocal EnableDelayedExpansion

REM Extract the first 5 tar files in data\<MODPACK_VER>\complete into
REM separate per-bundle folders under data\<MODPACK_VER>\unpacked\sample.

if "%MODPACK_VER%"=="" set "MODPACK_VER=MP_AUTOPLAY_VP_5_2_3"

REM Resolve repo root (parent of this script's directory).
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%.." >nul
set "REPO_ROOT=%CD%"
popd >nul

set "SRC_DIR=%REPO_ROOT%\data\%MODPACK_VER%\complete"
set "DST_DIR=%REPO_ROOT%\data\%MODPACK_VER%\unpacked\sample"

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

set /a COUNT=0
for /f "delims=" %%F in ('dir /b /a-d /o:n "%SRC_DIR%\*.tar"') do (
    if !COUNT! lss 5 (
        set /a COUNT+=1
        set "TARNAME=%%~nF"
        set "OUT=%DST_DIR%\!TARNAME!"
        if exist "!OUT!" (
            echo [!COUNT!/5] SKIP   !TARNAME! ^(already unpacked^)
        ) else (
            echo [!COUNT!/5] UNPACK !TARNAME!
            mkdir "!OUT!"
            tar -xf "%SRC_DIR%\%%F" -C "!OUT!"
            if errorlevel 1 (
                echo   ERROR: tar failed for %%F
                set "RC=1"
                goto :end
            )
        )
    )
)

echo.
echo Done. Extracted !COUNT! bundle(s) to %DST_DIR%

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
