@echo off
setlocal enabledelayedexpansion

REM ==============================================================================
REM Polyweb Generic Worktree Setup Script
REM Usage:
REM   create_worktree.bat <branch-name> [mode|folder-name] [mode] [options]
REM ==============================================================================

if "%~1"=="" goto :usage

set "BRANCH=%~1"
shift

set "MODE=full"
set "FOLDER="
set "BASE=main"
set "BASE_GIVEN=0"
set "SLOT="
set "COPY_DB=0"
set "POS1="
set "POS2="

:parse_args
if "%~1"=="" goto :args_done

if /i "%~1"=="--base" (
    if "%~2"=="" (
        echo [ERROR] --base requires a git ref ^(branch, tag, or commit^).
        goto :usage_exit
    )
    set "BASE=%~2"
    set "BASE_GIVEN=1"
    shift & shift
    goto :parse_args
)
if /i "%~1"=="--slot" (
    if "%~2"=="" (
        echo [ERROR] --slot requires a worktree slot number 1-9.
        goto :usage_exit
    )
    set "SLOT=%~2"
    shift & shift
    goto :parse_args
)
if /i "%~1"=="--copy-db" (
    set "COPY_DB=1"
    shift
    goto :parse_args
)
set "ARG=%~1"
if "!ARG:~0,2!"=="--" (
    echo [ERROR] Unknown option '%~1'.
    goto :usage_exit
)
if not defined POS1 (
    set "POS1=%~1"
) else if not defined POS2 (
    set "POS2=%~1"
)
shift
goto :parse_args
:args_done

set "ARG2=%POS1%"
set "ARG3=%POS2%"

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
    set "FOLDER=polyweb-!SAFE_NAME!"
)

REM ------------------------------------------------------------------------------
REM Validate --slot: must be a single digit 1-9 (slot 0 is the main checkout)
REM ------------------------------------------------------------------------------
if defined SLOT (
    set "SLOT_VALID="
    for %%D in (1 2 3 4 5 6 7 8 9) do if "!SLOT!"=="%%D" set "SLOT_VALID=1"
    if not defined SLOT_VALID (
        echo [ERROR] Invalid --slot '!SLOT!': expected an integer 1-9 ^(slot 0 is the main checkout^).
        exit /b 1
    )
)

REM Detect the slot implied by a 'polyweb_wt_N' folder name (N = digit 1-9)
set "FOLDER_SLOT="
if /i "%FOLDER:~0,14%"=="polyweb_wt_" (
    set "SLOT_REST=%FOLDER:~14%"
    for %%D in (1 2 3 4 5 6 7 8 9) do if "!SLOT_REST!"=="%%D" set "FOLDER_SLOT=%%D"
)

if defined SLOT (
    if defined FOLDER_SLOT (
        if not "!SLOT!"=="!FOLDER_SLOT!" (
            echo [ERROR] --slot !SLOT! conflicts with folder name '%FOLDER%' ^(implies slot !FOLDER_SLOT!^).
            exit /b 1
        )
    )
) else if defined FOLDER_SLOT (
    set "SLOT=!FOLDER_SLOT!"
    echo [INFO] Worktree slot !SLOT! inferred from folder name '%FOLDER%'.
)

REM ------------------------------------------------------------------------------
REM Resolve the branch state and validate --base BEFORE creating anything
REM ------------------------------------------------------------------------------
set "BRANCH_STATE=new"
git show-ref --verify --quiet "refs/heads/%BRANCH%"
if not errorlevel 1 set "BRANCH_STATE=local"
if "%BRANCH_STATE%"=="new" (
    git show-ref --verify --quiet "refs/remotes/origin/%BRANCH%"
    if not errorlevel 1 set "BRANCH_STATE=remote"
)

if "%BRANCH_STATE%"=="new" (
    git rev-parse --verify --quiet "%BASE%^{commit}" >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] --base ref '%BASE%' does not resolve to a commit.
        exit /b 1
    )
) else if "%BASE_GIVEN%"=="1" (
    echo [INFO] Branch '%BRANCH%' already exists; --base '%BASE%' is ignored.
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
set "BASE_USED=%BASE%"
set "PORTS_USED=unchanged"
set "DB_USED=fresh"

echo.
echo -------------------------------------------------------
echo Setting up worktree: %TARGET_BRANCH%
echo Path: %TARGET_PATH%
echo Target mode: [%TARGET_MODE%]
echo -------------------------------------------------------

REM 1. Create Git Worktree (checks local, then remote, else creates new from --base)
if "%BRANCH_STATE%"=="local" (
    set "BASE_USED=existing branch"
    echo [1/6] Checking out existing local branch '%TARGET_BRANCH%' in worktree '%TARGET_PATH%'...
    git worktree add "%TARGET_PATH%" "%TARGET_BRANCH%"
) else if "%BRANCH_STATE%"=="remote" (
    set "BASE_USED=existing branch"
    echo [1/6] Checking out remote branch 'origin/%TARGET_BRANCH%' in worktree '%TARGET_PATH%'...
    git worktree add --track -b "%TARGET_BRANCH%" "%TARGET_PATH%" "origin/%TARGET_BRANCH%"
) else (
    echo [1/6] Branch not found locally or remotely. Creating new branch '%TARGET_BRANCH%' from '%BASE%'...
    git worktree add -b "%TARGET_BRANCH%" "%TARGET_PATH%" "%BASE%"
)

if errorlevel 1 (
    echo [ERROR] Failed to create git worktree for '%TARGET_BRANCH%'.
    exit /b 1
)

REM 2. Copy .env, assign slot ports, and optionally copy the database
if exist ".env" (
    echo [2/6] Copying root .env file to '%TARGET_PATH%\.env'...
    copy /Y ".env" "%TARGET_PATH%\.env" >nul
    if defined SLOT (
        set /a "MCP_PORT=8000+SLOT*10"
        set /a "API_PORT=8000+SLOT*10+1"
        set /a "VITE_PORT=5174+SLOT"
        echo [2/6] Assigning slot !SLOT! ports: POLYWEB_MCP_PORT=!MCP_PORT!, POLYWEB_API_PORT=!API_PORT!, VITE_PORT=!VITE_PORT!
        powershell -NoProfile -Command ^
            "$p = '!TARGET_PATH!\.env'; " ^
            "$b = [IO.File]::ReadAllBytes($p); " ^
            "$hasBom = ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF); " ^
            "$t = [IO.File]::ReadAllText($p); " ^
            "$nl = [Environment]::NewLine; " ^
            "$caret = [char]94; " ^
            "$map = [ordered]@{ POLYWEB_MCP_PORT = '!MCP_PORT!'; POLYWEB_API_PORT = '!API_PORT!'; VITE_PORT = '!VITE_PORT!' }; " ^
            "foreach ($k in $map.Keys) { " ^
            "  $pat = '(?m)' + $caret + $k + '=' + '[' + $caret + '\r\n]*'; " ^
            "  if ([regex]::IsMatch($t, $pat)) { " ^
            "    $t = [regex]::Replace($t, $pat, $k + '=' + $map[$k]) " ^
            "  } else { " ^
            "    if ($t.Length -gt 0 -and -not $t.EndsWith([string][char]10)) { $t += $nl } " ^
            "    $t += $k + '=' + $map[$k] + $nl " ^
            "  } " ^
            "}; " ^
            "$enc = New-Object System.Text.UTF8Encoding($hasBom); " ^
            "[IO.File]::WriteAllText($p, $t, $enc)"
        if errorlevel 1 (
            echo [ERROR] Failed to write worktree ports into '%TARGET_PATH%\.env'.
            exit /b 1
        )
        set "PORTS_USED=MCP=!MCP_PORT!, API=!API_PORT!, VITE=!VITE_PORT!"
    ) else (
        echo [WARNING] No slot resolved for folder '%TARGET_FOLDER%': .env ports were copied
        echo           unchanged from the main checkout and will collide if both run at once.
        echo           Re-run with '--slot N' or use a 'polyweb_wt_N' folder name.
    )
) else (
    echo [2/6] Warning: No .env file found in root repository. Skipping copy.
    echo [WARNING] No .env in the main checkout - worktree ports cannot be assigned.
)

if "%COPY_DB%"=="1" (
    if exist "polyweb.db" (
        echo [2/6] Copying polyweb.db to '%TARGET_PATH%\polyweb.db'...
        copy /Y "polyweb.db" "%TARGET_PATH%\polyweb.db" >nul
        set "DB_USED=copied"
        echo [WARNING] The copied polyweb.db contains stored provider credentials
        echo           and real request history - treat it as sensitive.
        echo [INFO] The copy opens only if it is at the alpha baseline revision;
        echo        an older database is refused with reset instructions.
    ) else (
        echo [2/6] [INFO] --copy-db given but no polyweb.db found in main checkout. Skipping copy.
    )
) else (
    echo [2/6] [INFO] polyweb.db is NOT copied - use --copy-db to opt in;
    echo           a fresh database will be created by 'polyweb-db upgrade'.
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
    echo [3/6] Ensuring database schema is current with 'uv run polyweb-db upgrade'...
    call uv run polyweb-db upgrade
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
    if exist "%TARGET_PATH%\polyweb-ui" (
        if exist "%~dp0..\..\polyweb-ui\.env.local" (
            echo [4/6] Copying UI .env.local to '%TARGET_PATH%\polyweb-ui\.env.local'...
            copy /Y "%~dp0..\..\polyweb-ui\.env.local" "%TARGET_PATH%\polyweb-ui\.env.local" >nul
        )
    )
) else (
    if exist "%TARGET_PATH%\polyweb-ui\package.json" (
        echo [4/6] Setting up UI dependencies in '%TARGET_PATH%\polyweb-ui'...
        pushd "%TARGET_PATH%\polyweb-ui"
        if exist "%~dp0..\..\polyweb-ui\.env.local" (
            copy /Y "%~dp0..\..\polyweb-ui\.env.local" ".env.local" >nul
        )
        call pnpm install --store-dir "%~dp0..\..\.pnpm-store"
        if errorlevel 1 (
            echo [ERROR] 'pnpm install' failed in '%TARGET_PATH%\polyweb-ui'.
            popd
            exit /b 1
        )
        echo [4/6] Generating Playwright BDD specs with 'pnpm bddgen'...
        call pnpm bddgen
        popd
    ) else (
        echo [4/6] [INFO] No polyweb-ui directory found on this branch. Skipping UI setup.
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
echo -------------------------------------------------------
echo [OK] Worktree setup complete.
echo   Branch : %TARGET_BRANCH%
echo   Base   : %BASE_USED%
echo   Path   : %TARGET_PATH%
echo   Mode   : %TARGET_MODE%
if defined SLOT (
    echo   Slot   : !SLOT!
) else (
    echo   Slot   : none
)
echo   Ports  : %PORTS_USED%
echo   DB     : %DB_USED%
echo -------------------------------------------------------
exit /b 0

:usage
echo [ERROR] Missing branch name argument.
:usage_exit
echo.
echo Usage:
echo   create_worktree.bat ^<branch-name^> [mode^|folder-name] [mode] [options]
echo.
echo Modes:
echo   docker (or bare, none)    - Fast passthrough: git checkout + .env only (skips uv ^& pnpm)
echo   backend (or be)           - Setup backend only (uv sync + polyweb-db upgrade)
echo   ui (or frontend, fe)      - Setup UI only (pnpm install + bddgen)
echo   full (or fullstack)       - Setup both backend and UI [default]
echo.
echo Options:
echo   --base ^<ref^>   Base ref for a NEW branch (default: main; ignored if the branch exists)
echo   --slot ^<N^>     Worktree slot 1-9; sets .env ports MCP 80N0 / API 80N1 / VITE 5174+N
echo   --copy-db      Copy the main checkout's polyweb.db (contains credentials/history).
echo                  A copy works only if the main database is already at the alpha
echo                  baseline; otherwise the new worktree refuses it with reset steps.
echo.
echo Examples:
echo   create_worktree.bat my-feature docker
echo   create_worktree.bat my-feature backend --base develop
echo   create_worktree.bat my-feature polyweb_wt_1 backend
echo   create_worktree.bat my-feature custom-folder-name docker --slot 3
exit /b 1
