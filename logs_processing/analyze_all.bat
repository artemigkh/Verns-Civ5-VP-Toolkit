@echo off
setlocal EnableDelayedExpansion

REM Windows port of analyze_all_games.sh:
REM   1. ensure all bundles are extracted (extract_all.bat)
REM   2. mvn package the Scala Spark job
REM   3. spark-submit it locally against the full unpacked bundle set
REM
REM Configurable via MODPACK_VER (default MP_AUTOPLAY_VP_5_2_3).
REM Reads input from   data\<MODPACK_VER>\unpacked\all
REM Writes output to    data\<MODPACK_VER>\intermediate_csvs

if "%MODPACK_VER%"=="" set "MODPACK_VER=MP_AUTOPLAY_VP_5_2_3"

set "RC=0"
set "PUSHED=0"

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%.." >nul
set "REPO_ROOT=%CD%"
popd >nul

REM ----- Make sure all bundles are extracted before analyzing -----
echo === extract_all.bat ===
call "%SCRIPT_DIR%extract_all.bat" --no-pause
if errorlevel 1 (
    echo ERROR: extract_all.bat failed.
    set "RC=1"
    goto :end
)
echo.

REM ----- Toolchain (installed by the setup step) -----
if "%CONDA_DEFAULT_ENV%" NEQ "civ5spark" (
    echo Activating conda env civ5spark...
    call conda activate civ5spark || (
        echo ERROR: failed to activate conda env civ5spark.
        set "RC=1"
        goto :end
    )
)

set "SPARK_HOME=%USERPROFILE%\spark-civ5\spark-2.4.8-bin-hadoop2.7"
set "HADOOP_HOME=%USERPROFILE%\spark-civ5\hadoop"
set "PATH=%SPARK_HOME%\bin;%HADOOP_HOME%\bin;%PATH%"

if not exist "%SPARK_HOME%\bin\spark-submit.cmd" (
    echo ERROR: SPARK_HOME not found at %SPARK_HOME%
    set "RC=1"
    goto :end
)
if not exist "%HADOOP_HOME%\bin\winutils.exe" (
    echo ERROR: winutils.exe not found at %HADOOP_HOME%\bin
    set "RC=1"
    goto :end
)

REM ----- Paths -----
set "INPUT=%REPO_ROOT%\data\%MODPACK_VER%\unpacked\all"
set "OUTPUT=%REPO_ROOT%\data\%MODPACK_VER%\intermediate_csvs"

if not exist "%INPUT%" (
    echo ERROR: input dir not found: %INPUT%
    echo Run extract_all.bat first.
    set "RC=1"
    goto :end
)

REM Spark refuses to write to an existing output dir in non-overwrite mode,
REM but ProcessCiv5Logs writes to subfolders under args.output(). Make sure
REM the parent exists; sub-job dirs are managed by Spark's "overwrite" mode.
if not exist "%OUTPUT%" mkdir "%OUTPUT%"

echo MODPACK_VER : %MODPACK_VER%
echo INPUT       : %INPUT%
echo OUTPUT      : %OUTPUT%
echo SPARK_HOME  : %SPARK_HOME%
echo HADOOP_HOME : %HADOOP_HOME%
echo.

pushd "%SCRIPT_DIR%" >nul
set "PUSHED=1"

echo === mvn clean package ===
call mvn -q clean package
if errorlevel 1 (
    echo ERROR: mvn build failed.
    set "RC=1"
    goto :end
)

set "JAR=%SCRIPT_DIR%target\civ5-1.0.jar"
if not exist "%JAR%" (
    echo ERROR: build artifact not found: %JAR%
    set "RC=1"
    goto :end
)

echo.
echo === spark-submit ===
set "LOG=%SCRIPT_DIR%analyze_all.log"
echo Logging to %LOG%
call "%SPARK_HOME%\bin\spark-submit.cmd" ^
    --class civ5.ProcessCiv5Logs ^
    --master "local[*]" ^
    --driver-memory 12g ^
    --driver-java-options "-Dlog4j.configuration=file:./src/main/resources/log4j.properties" ^
    "%JAR%" ^
    --input "%INPUT%" ^
    --output "%OUTPUT%" 2>&1 | "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "$input | Tee-Object -FilePath '%LOG%'"
set "RC=%ERRORLEVEL%"

echo.
echo === spark-submit exit code: %RC% ===
echo Log: %LOG%

:end
if "%PUSHED%"=="1" popd >nul
echo.
if not "%RC%"=="0" (
    echo === Script failed with exit code %RC% ===
)
if /i not "%~1"=="--no-pause" (
    echo Press any key to close...
    pause >nul
)
endlocal & exit /b %RC%
