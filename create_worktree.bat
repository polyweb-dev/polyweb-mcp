@echo off
setlocal enabledelayedexpansion

REM ==============================================================================
REM FreeSearch Generic Worktree Setup Script
REM Usage:
REM   create_worktree.bat <branch-name> [worktree-folder-name]
REM
REM Examples:
REM   create_worktree.bat provider-firecrawl
REM   create_worktree.bat stage-4-integration
REM   create_worktree.bat feature/custom-feature freesearch-custom
REM ==============================================================================

if "%~1"=="" (
    echo [ERROR] Missing branch name argument.
    echo.
    echo Usage:
    echo   %~nx0 ^<branch-name^> [folder-name]
    echo.
    echo Example:
    echo   %~nx0 provider-firecrawl
    echo   %~nx0 stage-4-integration
    exit /b 1
)

set "BRANCH=%~1"
set "FOLDER=%~2"
if "%FOLDER%"=="" (
    REM Strip standard prefix slashes if present in branch name for folder safety
    set "SAFE_NAME=%BRANCH:/=-%"
    set "FOLDER=freesearch-!SAFE_NAME!"
)

call :setup_worktree "%BRANCH%" "%FOLDER%"
exit /b %ERRORLEVEL%

REM ------------------------------------------------------------------------------
REM Helper Function to Setup a Single Worktree
REM ------------------------------------------------------------------------------
:setup_worktree
set "TARGET_BRANCH=%~1"
set "TARGET_FOLDER=%~2"
set "TARGET_PATH=..\%TARGET_FOLDER%"

echo.
echo -------------------------------------------------------
echo Setting up worktree: %TARGET_BRANCH% at %TARGET_PATH%
echo -------------------------------------------------------

REM 1. Create Git Worktree (creates branch if it doesn't exist)
git show-ref --verify --quiet refs/heads/%TARGET_BRANCH%
if errorlevel 1 (
    echo [1/3] Creating branch '%TARGET_BRANCH%' and worktree at '%TARGET_PATH%'...
    git worktree add -b "%TARGET_BRANCH%" "%TARGET_PATH%" main
) else (
    echo [1/3] Checking out existing branch '%TARGET_BRANCH%' in worktree '%TARGET_PATH%'...
    git worktree add "%TARGET_PATH%" "%TARGET_BRANCH%"
)

if errorlevel 1 (
    echo [ERROR] Failed to create git worktree for '%TARGET_BRANCH%'.
    exit /b 1
)

REM 2. Copy .env file if present in main repo
if exist ".env" (
    echo [2/3] Copying .env file to '%TARGET_PATH%\.env'...
    copy /Y ".env" "%TARGET_PATH%\.env" >nul
) else (
    echo [2/3] Warning: No .env file found in root repository. Skipping copy.
)

REM 3. Run uv sync in target worktree to create clean virtualenv
echo [3/3] Initializing virtual environment with 'uv sync' in '%TARGET_PATH%'...
pushd "%TARGET_PATH%"
uv sync
if errorlevel 1 (
    echo [ERROR] 'uv sync' failed in '%TARGET_PATH%'.
    popd
    exit /b 1
)
popd

echo [OK] Worktree '%TARGET_BRANCH%' ready at '%TARGET_PATH%'.
exit /b 0
