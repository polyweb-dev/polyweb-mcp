@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%..\.."
set "UI_DIR=%REPO_ROOT%\freesearch-ui"

pushd "%UI_DIR%"

echo [1/2] Checking dependencies...
if not exist "node_modules\@stryker-mutator\core" (
    echo [INFO] Installing dependencies via pnpm...
    call pnpm install
    if errorlevel 1 (
        echo [ERROR] pnpm install failed.
        popd
        exit /b 1
    )
)

REM Parse concurrency: if first argument is a number (e.g. run_ui_mutation.bat 8), treat as concurrency
set "CONCURRENCY_FLAG="
if not "%~1"=="" (
    echo %~1| findstr /r "^[0-9][0-9]*$" >nul
    if not errorlevel 1 (
        set "CONCURRENCY_FLAG=--concurrency %~1"
        shift
    )
)

REM Fall back to CONCURRENCY environment variable if defined
if "%CONCURRENCY_FLAG%"=="" (
    if defined CONCURRENCY (
        set "CONCURRENCY_FLAG=--concurrency %CONCURRENCY%"
    )
)

REM Reconstruct remaining arguments after shift
set "REMAINING_ARGS="
:collect_args
if "%~1"=="" goto run_stryker
set "REMAINING_ARGS=%REMAINING_ARGS% %1"
shift
goto collect_args

:run_stryker
echo [2/2] Running Stryker mutation testing for UI %CONCURRENCY_FLAG% %REMAINING_ARGS%...
call pnpm exec stryker run %CONCURRENCY_FLAG% %REMAINING_ARGS%
set "EXIT_CODE=%ERRORLEVEL%"

if exist "coverage\stryker\index.html" (
    echo.
    echo Stryker mutation report written to:
    echo %UI_DIR%\coverage\stryker\index.html
)

popd
exit /b %EXIT_CODE%
