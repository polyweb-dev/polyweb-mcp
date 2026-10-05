@echo off
setlocal enabledelayedexpansion

REM ==============================================================================
REM FreeSearch Generic Worktree Setup Script
REM Usage:
REM   create_worktree.bat <branch-name> [mode|folder-name] [mode]
REM ==============================================================================

if "%~1"=="" goto :usage

set "BRANCH=%~1"
set "ARG2=%~2"
set "ARG3=%~3"

set "MODE=full"
set "FOLDER="

REM Check if ARG2 is a known mode
if /i "%ARG2%"=="backend" set "MODE=backend"
if /i "%ARG2%"=="be" set "MODE=backend"
if /i "%ARG2%"=="ui" set "MODE=ui"
if /i "%ARG2%"=="frontend" set "MODE=ui"
if /i "%ARG2%"=="fe" set "MODE=ui"
if /i "%ARG2%"=="full" set "MODE=full"
if /i "%ARG2%"=="fullstack" set "MODE=full"
if /i "%ARG2%"=="docker" set "MODE=docker"
if /i "%ARG2%"=="bare" set "MODE=docker"
if /i "%ARG2%"=="none" set "MODE=docker"

REM If ARG2 was not a recognized mode, it is a custom folder name
if /i not "%MODE%"=="full" (
    REM ARG2 was recognized as a mode
    set "FOLDER="
) else (
    if not "%ARG2%"=="" (
        set "FOLDER=%ARG2%"
        REM Check if ARG3 specifies the mode
        if /i "%ARG3%"=="backend" set "MODE=backend"
        if /i "%ARG3%"=="be" set "MODE=backend"
        if /i "%ARG3%"=="ui" set "MODE=ui"
        if /i "%ARG3%"=="frontend" set "MODE=ui"
        if /i "%ARG3%"=="fe" set "MODE=ui"
        if /i "%ARG3%"=="full" set "MODE=full"
        if /i "%ARG3%"=="fullstack" set "MODE=full"
        if /i "%ARG3%"=="docker" set "MODE=docker"
        if /i "%ARG3%"=="bare" set "MODE=docker"
        if /i "%ARG3%"=="none" set "MODE=docker"
    )
)

if "%FOLDER%"=="" (
    REM Strip standard prefix slashes if present in branch name for folder safety
    set "SAFE_NAME=%BRANCH:/=-%"
    set "FOLDER=freesearch-!SAFE_NAME!"
)

call :setup_worktree "%BRANCH%" "%FOLDER%" "%MODE%"
exit /b %ERRORLEVEL%

REM ------------------------------------------------------------------------------
REM Helper Function to Setup a Single Worktree
REM ------------------------------------------------------------------------------
:setup_worktree
set "TARGET_BRANCH=%~1"
set "TARGET_FOLDER=%~2"
set "TARGET_MODE=%~3"
set "TARGET_PATH=..\%TARGET_FOLDER%"

echo.
echo -------------------------------------------------------
echo Setting up worktree: %TARGET_BRANCH%
echo Path: %TARGET_PATH%
echo Target mode: [%TARGET_MODE%]
echo -------------------------------------------------------

REM 1. Create Git Worktree (checks local, then remote, else creates new from main)
git show-ref --verify --quiet refs/heads/%TARGET_BRANCH%
if not errorlevel 1 (
    echo [1/6] Checking out existing local branch '%TARGET_BRANCH%' in worktree '%TARGET_PATH%'...
    git worktree add "%TARGET_PATH%" "%TARGET_BRANCH%"
) else (
    git show-ref --verify --quiet refs/remotes/origin/%TARGET_BRANCH%
    if not errorlevel 1 (
        echo [1/6] Checking out remote branch 'origin/%TARGET_BRANCH%' in worktree '%TARGET_PATH%'...
        git worktree add --track -b "%TARGET_BRANCH%" "%TARGET_PATH%" "origin/%TARGET_BRANCH%"
    ) else (
        echo [1/6] Branch not found locally or remotely. Creating new branch '%TARGET_BRANCH%' from main...
        git worktree add -b "%TARGET_BRANCH%" "%TARGET_PATH%" main
    )
)

if errorlevel 1 (
    echo [ERROR] Failed to create git worktree for '%TARGET_BRANCH%'.
    exit /b 1
)

REM 2. Copy .env and database file if present in main repo
if exist ".env" (
    echo [2/6] Copying root .env file to '%TARGET_PATH%\.env'...
    copy /Y ".env" "%TARGET_PATH%\.env" >nul
) else (
    echo [2/6] Warning: No .env file found in root repository. Skipping copy.
)

if exist "freesearch.db" (
    echo [2/6] Copying freesearch.db to '%TARGET_PATH%\freesearch.db'...
    copy /Y "freesearch.db" "%TARGET_PATH%\freesearch.db" >nul
)

REM 3. Backend Setup (uv sync + database migration)
if /i "%TARGET_MODE%"=="ui" (
    echo [3/6] [SKIP] Mode is 'ui' - skipping backend 'uv sync'.
) else if /i "%TARGET_MODE%"=="docker" (
    echo [3/6] [SKIP] Mode is 'docker' - skipping backend 'uv sync'.
) else (
    echo [3/6] Initializing backend virtualenv with 'uv sync' in '%TARGET_PATH%'...
    pushd "%TARGET_PATH%"
    call uv sync
    if errorlevel 1 (
        echo [ERROR] 'uv sync' failed in '%TARGET_PATH%'.
        popd
        exit /b 1
    )
    echo [3/6] Ensuring database schema is current with 'uv run freesearch-db upgrade'...
    call uv run freesearch-db upgrade
    if errorlevel 1 (
        echo [WARNING] Database upgrade reported an issue in '%TARGET_PATH%'.
    )
    popd
)

REM 4. UI Setup (pnpm install + bddgen)
if /i "%TARGET_MODE%"=="backend" (
    echo [4/6] [SKIP] Mode is 'backend' - skipping UI dependency setup.
) else if /i "%TARGET_MODE%"=="docker" (
    echo [4/6] [SKIP] Mode is 'docker' - skipping UI dependencies.
    if exist "%TARGET_PATH%\freesearch-ui" (
        if exist "%~dp0..\..\freesearch-ui\.env.local" (
            echo [4/6] Copying UI .env.local to '%TARGET_PATH%\freesearch-ui\.env.local'...
            copy /Y "%~dp0..\..\freesearch-ui\.env.local" "%TARGET_PATH%\freesearch-ui\.env.local" >nul
        )
    )
) else (
    if exist "%TARGET_PATH%\freesearch-ui\package.json" (
        echo [4/6] Setting up UI dependencies in '%TARGET_PATH%\freesearch-ui'...
        pushd "%TARGET_PATH%\freesearch-ui"
        if exist "%~dp0..\..\freesearch-ui\.env.local" (
            copy /Y "%~dp0..\..\freesearch-ui\.env.local" ".env.local" >nul
        )
        call pnpm install --store-dir "%~dp0..\..\.pnpm-store"
        if errorlevel 1 (
            echo [ERROR] 'pnpm install' failed in '%TARGET_PATH%\freesearch-ui'.
            popd
            exit /b 1
        )
        echo [4/6] Generating Playwright BDD specs with 'pnpm bddgen'...
        call pnpm bddgen
        popd
    ) else (
        echo [4/6] [INFO] No freesearch-ui directory found on this branch. Skipping UI setup.
    )
)

REM 5. CodeGraph Initialization
where codegraph >nul 2>&1
if not errorlevel 1 (
    echo [5/6] Initializing CodeGraph index in '%TARGET_PATH%' with 'codegraph init -y'...
    pushd "%TARGET_PATH%"
    call codegraph init -y
    popd
) else (
    echo [5/6] [SKIP] 'codegraph' CLI not found. Skipping CodeGraph initialization.
)

echo.
echo [OK] Worktree '%TARGET_BRANCH%' ready at '%TARGET_PATH%' for [%TARGET_MODE%] development.
exit /b 0

:usage
echo [ERROR] Missing branch name argument.
echo.
echo Usage:
echo   create_worktree.bat ^<branch-name^> [mode^|folder-name] [mode]
echo.
echo Modes:
echo   docker (or bare) - Fast passthrough: git checkout + .env only (skips uv & pnpm)
echo   backend (or be)  - Setup backend only (uv sync)
echo   ui (or frontend) - Setup UI only (pnpm install + bddgen)
echo   full (default)   - Setup both backend and UI
echo.
echo Examples:
echo   create_worktree.bat my-feature docker
echo   create_worktree.bat my-feature ui
echo   create_worktree.bat my-feature backend
echo   create_worktree.bat my-feature full
echo   create_worktree.bat my-feature custom-folder-name docker
exit /b 1
