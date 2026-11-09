@echo off
setlocal enabledelayedexpansion

REM ==============================================================================
REM Polyweb Generic Worktree Cleanup Script
REM Usage:
REM   delete_worktree.bat <branch-or-folder|--all> [--force|-f] [--keep-branch|-k] [--yes|-y]
REM
REM Examples:
REM   delete_worktree.bat quota-fix
REM   delete_worktree.bat ui-cq-refactor --force
REM   delete_worktree.bat polyweb-quota-fix --keep-branch
REM   delete_worktree.bat --all --force
REM ==============================================================================

set "TARGET="
set "FORCE=0"
set "KEEP_BRANCH=0"
set "AUTO_YES=0"
set "CLEAN_IMAGES=0"
set "DELETE_ALL=0"

:parse_args
if "%~1"=="" goto :args_done

if /i "%~1"=="--help" goto :usage
if /i "%~1"=="-h" goto :usage
if /i "%~1"=="--all" (
    set "DELETE_ALL=1"
    set "TARGET=ALL"
) else if /i "%~1"=="-a" (
    set "DELETE_ALL=1"
    set "TARGET=ALL"
) else if /i "%~1"=="--force" (
    set "FORCE=1"
    set "AUTO_YES=1"
) else if /i "%~1"=="-f" (
    set "FORCE=1"
    set "AUTO_YES=1"
) else if /i "%~1"=="--keep-branch" (
    set "KEEP_BRANCH=1"
) else if /i "%~1"=="-k" (
    set "KEEP_BRANCH=1"
) else if /i "%~1"=="--clean-images" (
    set "CLEAN_IMAGES=1"
) else if /i "%~1"=="--rmi" (
    set "CLEAN_IMAGES=1"
) else if /i "%~1"=="--yes" (
    set "AUTO_YES=1"
) else if /i "%~1"=="-y" (
    set "AUTO_YES=1"
) else (
    if not defined TARGET set "TARGET=%~1"
)
shift
goto :parse_args
:args_done

if not defined TARGET goto :usage

REM ------------------------------------------------------------------------------
REM 1. Validate Target and Current Workspace
REM ------------------------------------------------------------------------------
for /f "delims=" %%I in ('git rev-parse --show-toplevel 2^>nul') do set "RAW_ROOT=%%I"
if not defined RAW_ROOT (
    echo [ERROR] Must be run inside a Git repository.
    exit /b 1
)
set "CURRENT_ROOT=!RAW_ROOT:/=\!"
for %%I in ("!CURRENT_ROOT!\..") do set "PARENT_DIR=%%~fI"

REM If DELETE_ALL is requested, handle bulk cleanup
if "!DELETE_ALL!"=="1" goto :handle_delete_all

REM Guard main/master branches
if /i "%TARGET%"=="main" (
    echo [ERROR] Cannot delete the main repository branch.
    exit /b 1
)
if /i "%TARGET%"=="master" (
    echo [ERROR] Cannot delete the master repository branch.
    exit /b 1
)

REM Determine Branch Name from Target
set "BRANCH=%TARGET%"
set "STRIPPED=%TARGET:polyweb-=%"

git show-ref --verify --quiet "refs/heads/%TARGET%"
if not errorlevel 1 (
    set "BRANCH=%TARGET%"
) else (
    git show-ref --verify --quiet "refs/heads/%STRIPPED%"
    if not errorlevel 1 (
        set "BRANCH=%STRIPPED%"
    )
)

if /i "%BRANCH%"=="main" (
    echo [ERROR] Cannot delete the main repository branch.
    exit /b 1
)
if /i "%BRANCH%"=="master" (
    echo [ERROR] Cannot delete the master repository branch.
    exit /b 1
)

REM Safe folder name if branch contains slashes (e.g. ui/feature -> ui-feature)
set "SAFE_NAME=%BRANCH:/=-%"

REM ------------------------------------------------------------------------------
REM 2. Discover Worktree Directory
REM ------------------------------------------------------------------------------
set "WORKTREE_PATH="

REM First, check Git's registered worktrees
set "CURR_WT="
for /f "tokens=1,*" %%A in ('git worktree list --porcelain 2^>nul') do (
    if /i "%%A"=="worktree" (
        set "CURR_WT=%%B"
        set "CURR_WT=!CURR_WT:/=\!"
    ) else if /i "%%A"=="branch" (
        set "CURR_BRANCH=%%B"
        set "CURR_BRANCH=!CURR_BRANCH:refs/heads/=!"
        if /i "!CURR_BRANCH!"=="%BRANCH%" (
            set "WORKTREE_PATH=!CURR_WT!"
        ) else if /i "!CURR_WT!"=="!PARENT_DIR!\%TARGET%" (
            set "WORKTREE_PATH=!CURR_WT!"
            set "BRANCH=!CURR_BRANCH!"
        ) else if /i "!CURR_WT!"=="!PARENT_DIR!\polyweb-%TARGET%" (
            set "WORKTREE_PATH=!CURR_WT!"
            set "BRANCH=!CURR_BRANCH!"
        )
    )
)

if defined WORKTREE_PATH (
    set "WORKTREE_PATH=!WORKTREE_PATH:/=\!"
) else (
    REM If not in git worktree list, check common directory conventions
    if exist "!PARENT_DIR!\polyweb-%SAFE_NAME%" (
        set "WORKTREE_PATH=!PARENT_DIR!\polyweb-%SAFE_NAME%"
    ) else if exist "!PARENT_DIR!\%TARGET%" (
        set "WORKTREE_PATH=!PARENT_DIR!\%TARGET%"
    ) else if exist "!PARENT_DIR!\polyweb-%TARGET%" (
        set "WORKTREE_PATH=!PARENT_DIR!\polyweb-%TARGET%"
    )
)

REM Guard against deleting current repository
if defined WORKTREE_PATH (
    if /i "!WORKTREE_PATH!"=="!CURRENT_ROOT!" (
        echo [ERROR] Target worktree is the active repository: '!WORKTREE_PATH!'
        echo         Cannot delete the worktree you are currently working in.
        exit /b 1
    )
)

REM If neither worktree path nor git branch exist, nothing to do
git show-ref --verify --quiet "refs/heads/%BRANCH%"
set "BRANCH_EXISTS=%ERRORLEVEL%"

if not defined WORKTREE_PATH (
    if "%BRANCH_EXISTS%"=="1" (
        echo [ERROR] No worktree directory or Git branch found matching '%TARGET%'.
        exit /b 1
    )
)

REM ------------------------------------------------------------------------------
REM 3. Uncommitted Changes Check & User Confirmation
REM ------------------------------------------------------------------------------
if defined WORKTREE_PATH (
    if exist "!WORKTREE_PATH!" (
        for /f "delims=" %%S in ('git -C "!WORKTREE_PATH!" status --porcelain 2^>nul') do (
            if "!FORCE!"=="0" (
                echo [WARNING] Worktree has uncommitted changes or untracked files:
                git -C "!WORKTREE_PATH!" status -s
                echo Re-run with --force to delete anyway.
                exit /b 1
            )
        )
    )
)

if "!AUTO_YES!"=="0" (
    echo ==============================================================================
    echo  Polyweb Worktree Deletion
    echo ==============================================================================
    if defined WORKTREE_PATH (
        echo  Directory: !WORKTREE_PATH!
    ) else (
        echo  Directory: [already unlinked or not found]
    )
    if "!KEEP_BRANCH!"=="0" (
        echo  Branch:    !BRANCH! [will be deleted]
    ) else (
        echo  Branch:    !BRANCH! [will be KEPT]
    )
    echo ==============================================================================
    set /p "CONFIRM=Proceed with deletion? [y/N]: "
    if /i not "!CONFIRM!"=="y" if /i not "!CONFIRM!"=="yes" (
        echo [ABORT] Deletion cancelled by user.
        exit /b 0
    )
)

call :execute_deletion "!WORKTREE_PATH!" "!BRANCH!"
exit /b %ERRORLEVEL%

REM ==============================================================================
REM Handle Deletion of All Registered Worktrees
REM ==============================================================================
:handle_delete_all
echo ==============================================================================
echo  Polyweb Bulk Worktree Deletion (--all)
echo ==============================================================================

if "!AUTO_YES!"=="0" (
    set /p "CONFIRM=Are you sure you want to delete ALL non-main worktrees? [y/N]: "
    if /i not "!CONFIRM!"=="y" if /i not "!CONFIRM!"=="yes" (
        echo [ABORT] Deletion cancelled by user.
        exit /b 0
    )
)

set "WT_COUNT=0"
set "TMP_WT_FILE=%TEMP%\polyweb_worktrees_%RANDOM%.txt"
if exist "!TMP_WT_FILE!" del /f /q "!TMP_WT_FILE!" >nul 2>&1

set "T_WT="
for /f "tokens=1,*" %%A in ('git worktree list --porcelain 2^>nul') do (
    if /i "%%A"=="worktree" (
        set "T_WT=%%B"
        set "T_WT=!T_WT:/=\!"
    ) else if /i "%%A"=="branch" (
        set "T_BR=%%B"
        set "T_BR=!T_BR:refs/heads/=!"
        if /i not "!T_WT!"=="!CURRENT_ROOT!" (
            echo !T_WT!*!T_BR!>> "!TMP_WT_FILE!"
            set /a WT_COUNT+=1
        )
    ) else if /i "%%A"=="detached" (
        if /i not "!T_WT!"=="!CURRENT_ROOT!" (
            echo !T_WT!*detached>> "!TMP_WT_FILE!"
            set /a WT_COUNT+=1
        )
    )
)

if not exist "!TMP_WT_FILE!" (
    echo [INFO] No secondary worktrees found to delete.
    echo [OK] Done.
    exit /b 0
)

echo [INFO] Found !WT_COUNT! secondary worktree(s) to remove.
echo.

for /f "usebackq tokens=1,* delims=*" %%P in ("!TMP_WT_FILE!") do (
    echo ------------------------------------------------------------------------------
    echo Processing worktree: %%P [branch: %%Q]
    echo ------------------------------------------------------------------------------
    call :execute_deletion "%%P" "%%Q"
    echo.
)
if exist "!TMP_WT_FILE!" del /f /q "!TMP_WT_FILE!" >nul 2>&1

echo [OK] All secondary worktrees cleaned up successfully.
exit /b 0

REM ==============================================================================
REM Core Cleanup Execution Routine: :execute_deletion <path> <branch>
REM ==============================================================================
:execute_deletion
set "W_PATH=%~1"
set "W_BRANCH=%~2"

REM ------------------------------------------------------------------------------
REM Step 1: Tear down Docker Compose resources (containers, networks, volumes)
REM ------------------------------------------------------------------------------
if defined W_PATH (
    if exist "!W_PATH!" (
        where docker >nul 2>&1
        if not errorlevel 1 (
            set "HAS_COMPOSE=0"
            if exist "!W_PATH!\compose.yaml" set "HAS_COMPOSE=1"
            if exist "!W_PATH!\docker-compose.yml" set "HAS_COMPOSE=1"
            if "!HAS_COMPOSE!"=="1" (
                echo [1/6] Tearing down Docker Compose containers, networks, and volumes...
                pushd "!W_PATH!"
                if "!CLEAN_IMAGES!"=="1" (
                    call docker compose down --volumes --remove-orphans --rmi local >nul 2>&1
                ) else (
                    call docker compose down --volumes --remove-orphans >nul 2>&1
                )
                popd
            ) else (
                echo [1/6] [SKIP] No Docker Compose file found in worktree.
            )
        ) else (
            echo [1/6] [SKIP] Docker CLI not found.
        )
    ) else (
        echo [1/6] [SKIP] Worktree directory does not exist.
    )
) else (
    echo [1/6] [SKIP] No worktree directory found.
)

REM ------------------------------------------------------------------------------
REM Step 2: Unregister Worktree from Git
REM ------------------------------------------------------------------------------
if defined W_PATH (
    echo [2/6] Unregistering worktree from Git...
    if "!FORCE!"=="1" (
        call git worktree remove --force "!W_PATH!" >nul 2>&1
    ) else (
        call git worktree remove "!W_PATH!" >nul 2>&1
    )
) else (
    echo [2/6] [SKIP] No registered worktree path found in Git.
)

REM ------------------------------------------------------------------------------
REM Step 3: Release CodeGraph Daemons, Locks, and Background Handles
REM ------------------------------------------------------------------------------
if defined W_PATH (
    if exist "!W_PATH!" (
        echo [3/6] Releasing CodeGraph locks and background processes...
        powershell -NoProfile -Command ^
            "$wt = '%~1'; " ^
            "$wtNorm = $wt.TrimEnd('\'); " ^
            "$daemons = Join-Path $HOME '.codegraph\daemons'; " ^
            "if (Test-Path $daemons) { " ^
            "  Get-ChildItem \"$daemons\*.json\" -ErrorAction SilentlyContinue | ForEach-Object { " ^
            "    $c = Get-Content $_.FullName -ErrorAction SilentlyContinue | ConvertFrom-Json -ErrorAction SilentlyContinue; " ^
            "    if ($c.root -and ($c.root.TrimEnd('\') -eq $wtNorm -or $c.root -like ('*' + $wtNorm + '*'))) { " ^
            "      Stop-Process -Id $c.pid -Force -ErrorAction SilentlyContinue; " ^
            "      Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue; " ^
            "    } " ^
            "  }; " ^
            "} " ^
            "Get-CimInstance Win32_Process | Where-Object { " ^
            "  ($_.CommandLine -like '*codegraph*' -and $_.CommandLine -like ('*' + $wtNorm + '*')) -or " ^
            "  ($_.CommandLine -like ('*' + $wtNorm + '*') -and $_.ProcessId -ne $PID) " ^
            "} | ForEach-Object { " ^
            "  Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue " ^
            "}" >nul 2>&1
        if exist "!W_PATH!\.codegraph" (
            where codegraph >nul 2>&1
            if not errorlevel 1 (
                call codegraph uninit --force "!W_PATH!" >nul 2>&1
            )
        )
    ) else (
        echo [3/6] [SKIP] Worktree directory does not exist.
    )
) else (
    echo [3/6] [SKIP] No worktree directory found.
)

REM ------------------------------------------------------------------------------
REM Step 4: Clean up filesystem leftovers (node_modules, .venv, .stryker-tmp, etc.)
REM ------------------------------------------------------------------------------
if defined W_PATH (
    if exist "!W_PATH!" (
        echo [4/6] Removing filesystem directory and leftovers '!W_PATH!'...
        cmd /c rmdir /s /q "!W_PATH!" >nul 2>&1
        if exist "!W_PATH!" (
            timeout /t 1 /nobreak >nul 2>&1
            cmd /c rmdir /s /q "!W_PATH!" >nul 2>&1
        )
        if exist "!W_PATH!" (
            powershell -NoProfile -Command "Remove-Item -Recurse -Force '!W_PATH!' -ErrorAction SilentlyContinue" >nul 2>&1
        )
        if exist "!W_PATH!" (
            echo [WARNING] Some files in '!W_PATH!' could not be deleted.
            echo           Please close any open editors/terminals using this directory.
        ) else (
            echo [OK] Worktree directory removed completely.
        )
    ) else (
        echo [4/6] [OK] Directory already removed from disk.
    )
) else (
    echo [4/6] [SKIP] No worktree directory to remove.
)

REM ------------------------------------------------------------------------------
REM Step 5: Prune stale worktree metadata
REM ------------------------------------------------------------------------------
echo [5/6] Pruning stale Git worktree metadata...
call git worktree prune

REM ------------------------------------------------------------------------------
REM Step 6: Delete Git Branch
REM ------------------------------------------------------------------------------
if "!KEEP_BRANCH!"=="1" (
    echo [6/6] [SKIP] Keeping branch '!W_BRANCH!' [--keep-branch].
) else (
    if defined W_BRANCH if not "!W_BRANCH!"=="" if not "!W_BRANCH!"=="detached" (
        git show-ref --verify --quiet "refs/heads/!W_BRANCH!"
        if not errorlevel 1 (
            echo [6/6] Deleting Git branch '!W_BRANCH!'...
            if "!FORCE!"=="1" (
                call git branch -D "!W_BRANCH!"
            ) else (
                call git branch -d "!W_BRANCH!"
                if errorlevel 1 (
                    echo [WARNING] Branch '!W_BRANCH!' was not fully merged into main.
                    echo           To force delete it, run: git branch -D "!W_BRANCH!"
                    echo           Or rerun this script with --force.
                )
            )
        ) else (
            echo [6/6] [INFO] Branch '!W_BRANCH!' does not exist in local Git.
        )
    ) else (
        echo [6/6] [SKIP] No branch associated with worktree.
    )
)

echo [OK] Cleanup completed for '!W_PATH!'.
exit /b 0

REM ------------------------------------------------------------------------------
REM Usage Information
REM ------------------------------------------------------------------------------
:usage
echo [ERROR] Missing branch, worktree folder name, or --all option.
echo.
echo Usage:
echo   delete_worktree.bat ^<branch-or-folder^> [options]
echo   delete_worktree.bat --all [options]
echo.
echo Options:
echo   -a, --all           Delete ALL existing worktrees (except main repository)
echo   -f, --force         Force removal [even if dirty or unmerged]
echo   -k, --keep-branch   Delete worktree directory and registration, but keep the branch
echo   --clean-images      Also remove locally built Docker images (--rmi local)
echo   -y, --yes           Skip confirmation prompt
echo.
echo Examples:
echo   delete_worktree.bat quota-fix
echo   delete_worktree.bat ui-cq-refactor --force
echo   delete_worktree.bat polyweb-quota-fix --keep-branch
echo   delete_worktree.bat feature/AllSearchRanked --force --clean-images
echo   delete_worktree.bat --all --force
exit /b 1
